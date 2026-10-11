import math
from datetime import datetime, timezone

IDENTITY = ("protocolVersion", "duelId", "duelGeneration", "decisionId", "actor")
TERMINAL = {"applied", "rejected", "cancelled", "expired"}


def utc_now():
    return datetime.now(timezone.utc)


def deadline(request):
    value = datetime.fromisoformat(request["deadline"].replace("Z", "+00:00"))
    if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("invalid_deadline")
    return value


def validate_request(request):
    if request.get("protocolVersion") != 1 or type(request.get("protocolVersion")) is not int:
        raise ValueError("unsupported_protocol")
    if type(request.get("actor")) is not int or request["actor"] not in (0, 1):
        raise ValueError("invalid_actor")
    for key in ("duelGeneration", "requestSequence"):
        if type(request.get(key)) is not int or request[key] < 1:
            raise ValueError("invalid_" + key)
    for key in ("duelId", "decisionId"):
        value = request.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(not (c.isalnum() or c in "-_") for c in value):
            raise ValueError("invalid_" + key)
    if request["rawRequest"]["decodeStatus"] != "complete":
        raise ValueError("unsupported_request")
    limits = request["constraints"]
    if any(type(limits.get(k)) is not int for k in ("min", "max")) or not 0 <= limits["min"] <= limits["max"] <= 4096:
        raise ValueError("invalid_selection_count")
    if any(type(limits.get(k)) is not bool for k in ("ordered", "allowEmpty")):
        raise ValueError("invalid_constraints")
    ids = [c["actionId"] for c in request["choices"]]
    if not ids or len(ids) != len(set(ids)) or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError("invalid_choices")
    deadline(request)
    return request


def validate_selection(request, selected, check_legality=True):
    limits = request["constraints"]
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        raise ValueError("invalid_action_ids")
    if not limits["min"] <= len(selected) <= limits["max"] or not selected and not limits["allowEmpty"]:
        raise ValueError("invalid_selection_count")
    candidates = {c["actionId"] for c in request["choices"]}
    if len(set(selected)) != len(selected) or not set(selected) <= candidates:
        raise ValueError("invalid_action_ids")
    if not check_legality:
        return
    legality = limits["legality"]
    if legality == "unknown":
        raise ValueError("unknown_legality")
    if legality == "single" and (limits["min"], limits["max"]) != (1, 1):
        raise ValueError("invalid_single_constraint")
    if legality == "allowed_selections":
        matches = any(selected == a if limits["ordered"] else set(selected) == set(a)
                      for a in limits["allowedSelections"] if len(a) == len(selected))
        if not matches:
            raise ValueError("illegal_selection")
    elif legality not in ("single", "independent"):
        raise ValueError("invalid_legality")


def validate_decision(request, response, now):
    if any(type(response.get(k)) is not type(request[k]) or response.get(k) != request[k] for k in IDENTITY):
        raise ValueError("identity_mismatch")
    if deadline(request) <= now:
        raise ValueError("expired")
    validate_selection(request, response["actionIds"])
    confidence = response.get("confidence")
    if confidence is not None and (type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError("invalid_confidence")
    return response
