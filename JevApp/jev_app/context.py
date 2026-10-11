from copy import deepcopy
from collections import deque


def visible_observation(observation):
    result = deepcopy(observation)
    references = result.get("cards", []) + result.get("selectionContext", {}).get("sourceCards", [])
    for item in result.get("chain", []) + result.get("events", []):
        references += item.get("cardReferences", [])
    for card in references:
        if card.get("identityVisible") is not True:
            for key in ("cardId", "name", "description", "uniqueId", "attack", "defense", "attribute", "race", "level"):
                card.pop(key, None)
    return result


class DuelContext:
    def __init__(self):
        self.duels = {}

    def update(self, request):
        key = (request["duelId"], request["duelGeneration"])
        if key not in self.duels:
            # ponytail: at most eight live duels; memory history is intentionally bounded.
            if len(self.duels) >= 8:
                self.duels.pop(next(iter(self.duels)))
            self.duels[key] = {"history": deque(maxlen=64), "applied": set()}
        duel = self.duels[key]
        observation = visible_observation(request["observation"])
        return {"actor": request["actor"], "duel": observation,
                "selection": observation.get("selectionContext", {"role": "unknown", "parentDecisionId": None}),
                "appliedDecisions": list(duel["history"]), "appliedHistoryLimited": True}

    def restore(self, request, snapshot):
        if snapshot.get("protocolVersion") != 1 or any(snapshot.get(key) != request[key] for key in ("duelId", "duelGeneration", "actor")):
            raise ValueError("invalid_context_identity")
        if type(snapshot.get("ended")) is not bool or type(snapshot.get("historyLimited")) is not bool:
            raise ValueError("invalid_context_status")
        if snapshot["ended"]:
            self.end(request["duelId"], request["duelGeneration"])
            return False
        self.update(request)
        for record in snapshot["records"]:
            prior = record["request"]
            if record["state"] != "applied" or any(prior[key] != request[key] for key in ("duelId", "duelGeneration", "actor")) or prior["requestSequence"] >= request["requestSequence"]:
                raise ValueError("invalid_context_history")
            self.acknowledge(record)
        return True

    def acknowledge(self, record):
        request = record["request"]
        key = (request["duelId"], request["duelGeneration"])
        if record["state"] == "applied" and key in self.duels:
            duel = self.duels[key]
            if request["decisionId"] not in duel["applied"]:
                duel["applied"].add(request["decisionId"])
                by_id = {choice["actionId"]: choice for choice in request["choices"]}
                actions = deepcopy([by_id[action_id] for action_id in record["decision"]["actionIds"]])
                for action in actions:
                    action["cardReferences"] = visible_observation({"cards": action["cardReferences"]})["cards"]
                duel["history"].append({"decisionId": request["decisionId"], "requestKind": request["requestKind"],
                                        "actionIds": record["decision"]["actionIds"], "actions": actions,
                                        "turn": request["observation"].get("turn"), "phase": request["observation"].get("phase")})
                duel["applied"] = {item["decisionId"] for item in duel["history"]}

    def end(self, duel_id, generation):
        self.duels.pop((duel_id, generation), None)
