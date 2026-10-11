import json
import math
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from .bridge import NoRedirect


@dataclass
class ProviderChoice:
    choice: str
    provider: str
    model: str
    confidence: float | None = None


class RetryableError(Exception):
    pass


class MockProvider:
    def choose(self, state, criteria, timeout):
        return ProviderChoice(next(iter(criteria)), "mock", "first-legal-test-only")


class JevProvider:
    def __init__(self, endpoint="https://api.typesafe.ai/v1/systemone", api_key=None):
        self.endpoint = endpoint
        self.api_key = api_key if api_key is not None else os.environ.get("JEV_API_KEY")
        if not self.api_key:
            raise ValueError("JEV_API_KEY is required in the app environment")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def choose(self, state, criteria, timeout):
        if not 1 <= len(criteria) <= 255:
            raise ValueError("choice_option_limit")
        payload = {"model": "jev-1.13.0", "state": state, "questions": {"action": {
            "type": "choice", "instructions": "현재 듀얼 상태와 선택 맥락을 바탕으로 승리에 가장 도움이 되는 합법적인 행동을 선택한다.",
            "criteria": criteria}}}
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        # Conservative byte bound without another tokenizer dependency; never silently truncate.
        if len(raw) > 30000:
            raise ValueError("jev_context_byte_budget")
        request = Request(self.endpoint, raw, {"Authorization": "Bearer " + self.api_key,
                                                "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw_response = response.read(1048577)
                if len(raw_response) > 1048576:
                    raise ValueError("jev_response_too_large")
                result = json.loads(raw_response)
        except HTTPError as error:
            code = error.code
            error.close()
            if code in (429, 529):
                raise RetryableError(f"jev_http_{code}") from None
            raise ValueError(f"jev_http_{code}") from None
        except (URLError, TimeoutError):
            raise RetryableError("jev_connection_failed") from None
        if (not isinstance(result, dict) or not isinstance(result.get("model"), str) or not result["model"] or
                len(result["model"]) > 4096 or not isinstance(result.get("answers"), dict) or
                not isinstance(result["answers"].get("action"), dict)):
            raise ValueError("invalid_jev_response")
        answer = result["answers"]["action"]
        confidence = answer.get("confidence")
        if (answer.get("type") != "choice" or answer.get("choice") not in criteria or
                type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("invalid_jev_choice")
        return ProviderChoice(answer["choice"], "jev", result["model"], confidence)
