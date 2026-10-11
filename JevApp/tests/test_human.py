import json
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_app.human import HumanServer


class HumanInterface(unittest.TestCase):
    def setUp(self):
        self.server = HumanServer(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, route, body, headers=None):
        request = Request(self.server.origin + route, json.dumps(body).encode(),
                          {"Content-Type": "application/json", **(headers or {})})
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def pending(self):
        for _ in range(60):
            with self.opener.open(self.server.origin + "/api/pending", timeout=2) as response:
                view = json.load(response)
            if view["job"]:
                return view["job"]
            time.sleep(.02)
        self.fail("human query did not become pending")

    def assert_http(self, code, route, body, headers=None):
        with self.assertRaises(HTTPError) as failure:
            self.call(route, body, headers)
        self.assertEqual(failure.exception.code, code, failure.exception.read().decode())
        failure.exception.close()

    def test_person_answers_jev_types_with_only_binary_weights(self):
        query = {"model": "jev-1.13.0", "state": {"turn": 1}, "questions": {
            "action": {"type": "choice", "instructions": "행동 선택", "criteria": {"summon": "소환", "end": "턴 종료"}},
            "yes": {"type": "noul", "instructions": "효과를 발동할까요?"},
            "no": {"type": "noul", "instructions": "턴을 종료할까요?"},
            "level": {"type": "score", "instructions": "어느 수준인가요?", "criteria": ["낮음", "중간", "높음"]}}}
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(self.call, "/v1/systemone", query)
            job = self.pending()
            self.assertFalse(result.done())  # No automatic first-choice answer.
            selections = {"action": {"summon": False, "end": True}, "yes": True, "no": False,
                          "level": {"0": False, "1": False, "2": True}}
            invalid = {**selections, "yes": 1}
            self.assert_http(422, "/api/respond", {"jobId": job["id"], "answers": invalid})
            returned = self.call("/api/respond", {"jobId": job["id"], "answers": selections})
            response = result.result(timeout=2)
        self.assertEqual(returned["response"], response)
        self.assertEqual(response["model"], "human-dummy")
        self.assertEqual(response["answers"]["action"], {"type": "choice", "choice": "end", "confidence": 1,
                                                         "probabilities": {"summon": 0, "end": 1}})
        self.assertEqual(response["answers"]["yes"]["noul"], 1)
        self.assertEqual(response["answers"]["no"]["noul"], 0)
        self.assertEqual(response["answers"]["level"]["score"], 2)
        for key in ("action", "level"):
            self.assertTrue(all(type(value) is int and value in (0, 1) for value in response["answers"][key]["probabilities"].values()))
        self.assertEqual(response["usage"], {"input_tokens": 0, "output_tokens": 0})

    def test_retry_reuses_answer_and_late_or_foreign_submissions_fail(self):
        query = {"model": "jev-1.13.0", "state": "確認", "questions": {"ready": {"type": "noul", "instructions": "準備済み?"}}}
        headers = {"X-Human-Request-Id": "stable-request"}
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(self.call, "/v1/systemone", query, headers)
            job = self.pending()
            self.assert_http(403, "/api/respond", {"jobId": job["id"], "answers": {"ready": True}}, {"Origin": "https://example.com"})
            self.call("/api/respond", {"jobId": job["id"], "answers": {"ready": False}})
            response = result.result(timeout=2)
        self.assertEqual(self.call("/v1/systemone", query, headers), response)
        self.assertIsNone(self.server.view()["job"])
        self.assert_http(409, "/v1/systemone", {**query, "state": "changed"}, headers)
        self.assert_http(408, "/v1/systemone", query, {"X-Human-Request-Id": "expired-request", "X-Human-Timeout": ".02"})
        self.assert_http(409, "/api/respond", {"jobId": "expired-request", "answers": {"ready": True}})
        with ThreadPoolExecutor(max_workers=1) as pool:
            cancelled = pool.submit(self.call, "/v1/systemone", query, {"X-Human-Request-Id": "cancelled-request"})
            self.pending()
            self.call("/api/cancel", {"jobId": "cancelled-request"})
            with self.assertRaises(HTTPError) as failure:
                cancelled.result(timeout=2)
            self.assertEqual(failure.exception.code, 409)
            failure.exception.close()


if __name__ == "__main__":
    unittest.main()
