from copy import deepcopy
from collections import deque


def visible_observation(observation):
    result = deepcopy(observation)
    for card in result.get("cards", []) + result.get("selectionContext", {}).get("sourceCards", []):
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
                "appliedDecisions": list(duel["history"])}

    def acknowledge(self, record):
        request = record["request"]
        key = (request["duelId"], request["duelGeneration"])
        if record["state"] == "applied" and key in self.duels:
            duel = self.duels[key]
            if request["decisionId"] not in duel["applied"]:
                duel["applied"].add(request["decisionId"])
                selected = set(record["decision"]["actionIds"])
                actions = deepcopy([c for c in request["choices"] if c["actionId"] in selected])
                for action in actions:
                    action["cardReferences"] = visible_observation({"cards": action["cardReferences"]})["cards"]
                duel["history"].append({"decisionId": request["decisionId"], "requestKind": request["requestKind"],
                                        "actionIds": record["decision"]["actionIds"], "actions": actions,
                                        "turn": request["observation"].get("turn"), "phase": request["observation"].get("phase")})
                duel["applied"] = {item["decisionId"] for item in duel["history"]}

    def end(self, duel_id, generation):
        self.duels.pop((duel_id, generation), None)
