from dataclasses import dataclass
from itertools import combinations, permutations
import re
from .protocol import validate_request, validate_selection


@dataclass
class ChoiceQuestion:
    criteria: dict[str, str]
    selections: dict[str, list[str]]


def card_label(reference, actor, cards):
    side = "자신" if reference["player"] == actor else "상대"
    zone = reference.get("zone", "위치 미확인 구역")
    position = reference.get("position")
    if type(position) is int and 0 <= position <= 12:
        zone = f"필드 구역 {position + 1}"
    slot = reference.get("index", 0) + 1
    if reference.get("identityVisible") is not True:
        name = "비공개 카드"
    else:
        info = cards.get(reference.get("cardId"))
        if info is None:
            raise ValueError("missing_card_name")
        name = info["name"]
    return f"{side} {zone} {slot}번째 카드 ‘{name}’"


def plain_text(text):
    return re.sub(r"@[0-9]", "", text)


def mixed_dialog_text(parts, request, cards, texts):
    result = []
    visible_cards = request["observation"].get("cards", []) + request["observation"].get("selectionContext", {}).get("sourceCards", [])
    visible_ids = {card.get("cardId") for card in visible_cards if card.get("identityVisible") is True}
    for part in parts:
        kind, value = part["type"], part["value"]
        if kind == 1:  # AddString: engine DLG ID
            text = texts.resolve("DLG", value)
            if not text:
                raise ValueError("unresolved_dialog_text")
            result.append(plain_text(text))
        elif kind == 2:  # AddCr
            result.append("\n")
        elif kind == 5:  # InsCard: replaces a string placeholder with the displayed card name
            info = cards.get(value) if value in visible_ids else None
            if not info or not result or "%s" not in result[-1]:
                raise ValueError("unresolved_dialog_substitution")
            result[-1] = result[-1].replace("%s", info["name"], 1)
        else:
            raise ValueError("unsupported_mixed_dialog_text")
    text = "".join(result)
    if re.search(r"%(?:\d+\$)?[sd]", text):
        raise ValueError("unresolved_dialog_substitution")
    return text


def render_choice(choice, request, cards, texts):
    kind, args = choice["semanticKind"], choice["arguments"]
    references = choice["cardReferences"]
    names = [card_label(ref, request["actor"], cards) for ref in references]
    card = ", ".join(names)
    if args.get("textResolved") is True and choice.get("text"):
        return choice["text"]
    verbs = {"activate": "효과를 발동한다", "attack": "공격을 선언한다", "summon": "일반 소환한다",
             "flip_summon": "반전 소환한다", "pendulum_summon": "펜듈럼 소환을 진행한다",
             "special_summon": "특수 소환한다", "set_monster": "뒷면 수비 표시로 세트한다", "set_spell": "세트한다",
             "change_position": "표시 형식을 변경한다", "sort_card": "순서를 지정한다"}
    if kind == "change_position" and card and args.get("positionName"):
        return f"{card}: {args['positionName']}로 변경한다"
    if kind in verbs and card:
        return f"{card}: {verbs[kind]}"
    if kind == "select_card" and card:
        role = request["observation"].get("selectionContext", {}).get("role", "unknown")
        role_label = {"cost": "코스트", "target": "대상", "material": "소재"}.get(role, "카드")
        return f"{role_label}로 선택한다: {card}"
    if kind == "discard_card" and card:
        remaining = request["observation"].get("selectionContext", {}).get("remainingCount")
        if type(remaining) is not int or remaining < 1:
            raise ValueError("invalid_discard_count")
        return f"{card}: 버린다 (앞으로 버려야 할 {remaining}장 중 한 장)"
    if kind == "decline":
        return "이 요청에서 효과를 발동하지 않고 진행한다"
    if kind == "check_effects" and args.get("effectPromptType") in (1, 2):
        return "현재 타이밍에 발동할 카드나 효과를 선택한다"
    if kind == "draw_card":
        return "드로우 페이즈의 카드를 뽑는다"
    if kind == "acknowledge":
        return "현재 안내를 확인하고 계속한다"
    if kind in ("yes", "no"):
        title = args.get("promptText")
        if not title:
            title = texts.resolve(args.get("textGroup", "DLG"), args.get("textId"))
        if not title:
            raise ValueError("unresolved_dialog_text")
        if re.search(r"%(?:\d+\$)?[sd]", title):
            raise ValueError("unresolved_dialog_substitution")
        explanation = mixed_dialog_text(args.get("mixedText", []), request, cards, texts)
        return f"{explanation + chr(10) if explanation else ''}‘{plain_text(title)}’에 {'동의한다' if kind == 'yes' else '동의하지 않는다'}"
    if kind == "dialog_option":
        text = texts.resolve(args.get("textGroup", "DLG"), args.get("textId"))
        if not text:
            raise ValueError("unresolved_dialog_text")
        if re.search(r"%(?:\d+\$)?[sd]", text):
            raise ValueError("unresolved_dialog_substitution")
        return plain_text(text)
    if kind == "phase" and args.get("phaseName"):
        return f"{args['phaseName']}로 진행한다"
    if kind == "place_card" and type(args.get("position")) is int:
        return f"{card + ': ' if card else ''}필드 구역 {args['position'] + 1}에 놓는다"
    if kind == "number" and type(args.get("value")) is int:
        return f"숫자 {args['value']}을 선택한다"
    if kind in ("attribute", "race", "position", "coin", "dice") and args.get("valueName"):
        return f"{args['valueName']}을 선택한다"
    raise ValueError("unresolved_choice_semantics")


def build_question(request, context, cards, texts):
    validate_request(request)
    limits = request["constraints"]
    if limits["legality"] == "unknown":
        raise ValueError("unknown_legality")
    labels = {c["actionId"]: render_choice(c, request, cards, texts) for c in request["choices"]}
    if limits["legality"] == "single":
        if len(labels) > 255:
            raise ValueError("choice_option_limit")
        return ChoiceQuestion(labels, {key: [key] for key in labels})
    if limits["legality"] == "allowed_selections":
        groups = iter(limits["allowedSelections"])
    elif limits["legality"] == "independent":
        # Only an engine-verified independent selection permits this enumeration.
        def selections():
            for count in range(limits["min"], limits["max"] + 1):
                if count == 0 and not limits["allowEmpty"]:
                    continue
                for group in (permutations(labels, count) if limits["ordered"] else combinations(labels, count)):
                    yield list(group)
        groups = selections()
    else:
        raise ValueError("invalid_legality")
    criteria, selections = {}, {}
    for index, group in enumerate(groups):
        if index >= 255:
            raise ValueError("choice_option_limit")
        validate_selection(request, group)
        key = f"selection_{index}"
        criteria[key] = "아무 카드도 선택하지 않는다" if not group else " → ".join(labels[item] for item in group)
        if limits["ordered"] and group:
            criteria[key] = "이 순서로 선택한다: " + criteria[key]
        selections[key] = list(group)
    if not criteria:
        raise ValueError("no_legal_choices")
    return ChoiceQuestion(criteria, selections)
