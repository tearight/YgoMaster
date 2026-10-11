import json
import re
import time
from urllib.error import HTTPError
from .choices import build_question
from .context import DuelContext
from .metadata import CardCatalog, TextCatalog
from .protocol import IDENTITY, TERMINAL, deadline, utc_now, validate_decision
from .provider import RetryableError


class DecisionApp:
    def __init__(self, bridge, provider, cards=None, texts=None, clock=utc_now, sleep=time.sleep, trace=print):
        self.bridge, self.provider = bridge, provider
        self.cards, self.texts = cards or CardCatalog(), texts or TextCatalog()
        self.clock, self.sleep, self.trace = clock, sleep, trace
        self.context = DuelContext()
        self.states, self.responses, self.failures = {}, {}, {}

    def transition(self, decision_id, state, reason=None):
        self.states[decision_id] = state
        # Only identity and fixed reason codes; no headers, provider bodies, or credentials.
        self.trace(json.dumps({"decisionId": decision_id, "state": state, "reason": reason}))

    def still_pending(self, request):
        record = self.bridge.get(request["decisionId"])
        if record["state"] != "pending" or deadline(request) <= self.clock():
            self.context.acknowledge(record)
            state = "expired" if deadline(request) <= self.clock() else record["state"]
            self.transition(request["decisionId"], state)
            return False
        return True

    def process(self, request):
        decision_id = request["decisionId"]
        self.transition(decision_id, "received")
        self.transition(decision_id, "building")
        if (request["duelId"], request["duelGeneration"]) not in self.context.duels:
            if not self.context.restore(request, self.bridge.context(decision_id)):
                self.transition(decision_id, "cancelled", "duel_ended")
                return
        state = self.context.update(request)
        for card in state["duel"].get("cards", []):
            if card.get("identityVisible") is True:
                info = self.cards.get(card.get("cardId"))
                if info:
                    card.update(name=info["name"], description=info["description"])
        reference_groups = [state["selection"].get("sourceCards", [])]
        reference_groups += [item.get("cardReferences", []) for item in state["duel"].get("chain", []) + state["duel"].get("events", [])]
        reference_groups += [action["cardReferences"] for item in state["appliedDecisions"] for action in item["actions"]]
        for references in reference_groups:
            for card in references:
                if card.get("identityVisible") is True:
                    info = self.cards.get(card.get("cardId"))
                    if info:
                        card.update(name=info["name"], description=info["description"])
        question = build_question(request, state, self.cards, self.texts)
        state["requestKind"] = request["requestKind"]
        state["constraints"] = request["constraints"]
        self.transition(decision_id, "choosing")
        if getattr(self.provider, "human", False):
            self.provider.request_id = decision_id
        for attempt in range(4):
            if not self.still_pending(request):
                return
            try:
                timeout = min(getattr(self.provider, "max_wait", 30), (deadline(request) - self.clock()).total_seconds())
                chosen = self.provider.choose(state, question.criteria, max(0.01, timeout))
                break
            except RetryableError:
                if attempt == 3:
                    raise ValueError("provider_retry_exhausted") from None
                delay = 2 ** attempt
                if (deadline(request) - self.clock()).total_seconds() <= delay:
                    self.transition(decision_id, "expired")
                    return
                self.sleep(delay)
        if chosen.choice not in question.selections:
            raise ValueError("invalid_provider_choice")
        response = {key: request[key] for key in IDENTITY}
        response.update(actionIds=question.selections[chosen.choice], provider=chosen.provider,
                        model=chosen.model, confidence=chosen.confidence)
        validate_decision(request, response, self.clock())
        self.responses[decision_id] = response
        self.transition(decision_id, "validated")
        if not self.still_pending(request):
            return
        # Cache before submission so a lost HTTP response cannot trigger another Jev call.
        self.transition(decision_id, "submitted")
        self.bridge.publish_decision(response)
        self.transition(decision_id, "awaiting_applied")

    def step(self):
        for decision_id, failure in list(self.failures.items()):
            record = self.bridge.get(decision_id)
            if record["state"] == "pending":
                self.bridge.call("v1/acks", failure)
            self.failures.pop(decision_id, None)
        for decision_id, state in list(self.states.items()):
            if state not in ("validated", "submitted", "awaiting_applied"):
                continue
            record = self.bridge.get(decision_id)
            if record["state"] in TERMINAL:
                self.context.acknowledge(record)
                if record["state"] == "cancelled" and record.get("reason") in ("duel_end", "new_generation"):
                    req = record["request"]
                    self.context.end(req["duelId"], req["duelGeneration"])
                self.transition(decision_id, "done" if record["state"] == "applied" else record["state"])
                self.responses.pop(decision_id, None)
            elif record["state"] == "pending" and decision_id in self.responses:
                self.bridge.publish_decision(self.responses[decision_id])
                self.transition(decision_id, "awaiting_applied")
        for record in self.bridge.pending():
            request = record["request"]
            if request["decisionId"] in self.states:
                continue
            try:
                self.process(request)
            except OSError:
                if request["decisionId"] not in self.responses:
                    self.states.pop(request["decisionId"], None)
                raise
            except ValueError as error:
                reason = str(error)
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", reason):
                    reason = "invalid_request_or_provider_response"
                self.fail(request, reason)
            except (KeyError, TypeError):
                self.fail(request, "invalid_request_or_provider_response")
        # Bound terminal bookkeeping. The bridge remains authoritative after reconnect.
        if len(self.states) > 320:
            for key in list(self.states):
                if self.states[key] in TERMINAL | {"done", "failed"}:
                    self.states.pop(key)
                    if len(self.states) <= 256:
                        break

    def fail(self, request, reason):
        decision_id = request["decisionId"]
        failure = {key: request[key] for key in IDENTITY}
        failure.update(state="rejected", reason="app_" + reason)
        # Retain until the next step so a temporary bridge disconnect cannot lose the rejection.
        self.failures[decision_id] = failure
        self.transition(decision_id, "failed", reason)

    def run(self):
        self.trace(json.dumps({"state": "waiting"}))
        while True:
            try:
                self.step()
            except (OSError, HTTPError):
                self.trace(json.dumps({"state": "connection_wait"}))
            self.sleep(0.25)
