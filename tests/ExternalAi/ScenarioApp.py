"""Test-only choices that exercise non-default engine inputs; never a Jev fallback."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "JevApp"))
from jev_app.app import DecisionApp
from jev_app.bridge import BridgeClient
from jev_app.metadata import CardCatalog, TextCatalog
from jev_app.provider import ProviderChoice


class ScenarioProvider:
    def __init__(self, scenario):
        self.scenario = scenario

    def choose(self, state, criteria, timeout):
        keys = list(criteria)
        selected = keys[0]
        if keys[0].startswith("discard_"):
            # Choose the last card so a native default at index zero cannot pass this check.
            selected = keys[-1]
        elif self.scenario == "deck-order":
            if state["selection"]["role"] == "deck_order":
                selected = keys[-1]
            elif "phase_5" in keys and any(action["semanticKind"] == "sort_card"
                    for decision in state["appliedDecisions"] for action in decision["actions"]):
                selected = "phase_5"
        elif self.scenario == "twin-target":
            sets = [key for key in keys if key.startswith("command_") and key.endswith("_7")]
            face_down = [card for card in state["duel"]["cards"] if card["player"] == state["actor"]
                         and 7 <= card.get("position", -1) <= 11 and card.get("faceUp") is False]
            if sets and len(face_down) < 2:
                selected = sets[0]
            else:
                if "yesno_1" in keys:
                    selected = "yesno_1"
                pairs = [key for key, text in criteria.items() if key.startswith("selection_") and " → " in text]
                if pairs:
                    selected = pairs[0]
        elif self.scenario == "chain-cost":
            sets = [key for key in keys if key.startswith("command_") and key.endswith("_7")]
            set_cards = [card for card in state["duel"]["cards"] if card["player"] == state["actor"]
                         and 7 <= card.get("position", -1) <= 11 and card.get("faceUp") is False]
            opposing_spell = any(card["player"] != state["actor"] and card.get("cardId") == 4812
                                  and card.get("faceUp") is True for card in state["duel"]["cards"])
            if sets and not set_cards:
                selected = sets[0]
            elif "effect_yes" in keys and opposing_spell and set_cards:
                selected = "effect_yes"
            elif "yesno_1" in keys:
                selected = "yesno_1"
            elif "phase_5" in keys:
                selected = "phase_5"
        print("QUESTION " + json.dumps({"selection": state["selection"], "criteria": criteria, "chosen": selected,
                                       "historyDecisionIds": [item["decisionId"] for item in state["appliedDecisions"]]}, ensure_ascii=False), flush=True)
        return ProviderChoice(selected, "mock", "scenario-fixture-test-only")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-config", required=True)
    parser.add_argument("--card-data", required=True)
    parser.add_argument("--scenario", choices=("basic", "discard-two", "twin-target", "chain-cost", "deck-order"), required=True)
    args = parser.parse_args()
    DecisionApp(BridgeClient(args.bridge_config), ScenarioProvider(args.scenario), CardCatalog.from_game(args.card_data),
                TextCatalog.from_game(args.card_data)).run()


if __name__ == "__main__":
    main()
