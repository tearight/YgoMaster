import base64
import copy
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "JevApp"))
from jev_app.app import DecisionApp
from jev_app.bridge import BridgeClient
from jev_app.choices import build_question, render_choice
from jev_app.context import DuelContext, visible_observation
from jev_app.metadata import CardCatalog, TextCatalog
from jev_app.protocol import IDENTITY, utc_now
from jev_app.provider import JevProvider, MockProvider, RetryableError


def request(decision_id, duel_id=None, generation=1, sequence=1, seconds=90):
    return {"protocolVersion": 1, "duelId": duel_id or decision_id, "duelGeneration": generation,
            "decisionId": decision_id, "requestSequence": sequence, "actor": 1, "requestKind": "phase",
            "rawRequest": {"decodeStatus": "complete"}, "observation": {"turn": 1, "cards": []},
            "choices": [{"actionId": "end", "semanticKind": "phase", "text": "", "cardReferences": [],
                         "arguments": {"phaseName": "엔드 페이즈"}}],
            "constraints": {"min": 1, "max": 1, "ordered": False, "allowEmpty": False, "legality": "single"},
            "deadline": (utc_now() + timedelta(seconds=seconds)).isoformat()}


def decision(req):
    result = {key: req[key] for key in IDENTITY}
    return dict(result, actionIds=["end"], provider="mock", model="test", confidence=0.9)


class BridgeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.token = base64.b64encode(os.urandom(32)).decode()
        (root / "external-ai.token").write_text(cls.token)
        cls.config = root / "ExternalAi.local.json"
        cls.config.write_text(json.dumps({"enabled": True, "prefix": f"http://127.0.0.1:{port}/",
                                          "tokenFile": "external-ai.token", "deadlineSeconds": 120}))
        cls.bridge = BridgeClient(cls.config)
        cls.process = subprocess.Popen([str(ROOT / "YgoMaster" / "YgoMaster.exe"), "--external-ai-bridge-only",
                                        "--external-ai-config", str(cls.config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(80):
            if cls.process.poll() is not None:
                raise RuntimeError("bridge exited: " + cls.process.communicate()[1].decode(errors="replace"))
            try:
                cls.bridge.pending()
                break
            except OSError:
                time.sleep(0.05)
        else:
            cls.process.terminate()
            raise RuntimeError("bridge did not become ready")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.communicate(timeout=5)
        cls.temp.cleanup()

    def assert_http(self, status, route, payload):
        with self.assertRaises(HTTPError) as result:
            self.bridge.call(route, payload)
        self.assertEqual(result.exception.code, status)
        result.exception.close()

    def test_idempotency_validation_and_lifecycle(self):
        req = request("lifecycle")
        self.assertEqual(self.bridge.call("v1/requests", req)["state"], "pending")
        self.bridge.call("v1/requests", dict(reversed(list(req.items()))))
        self.assertEqual(sum(r["request"]["decisionId"] == "lifecycle" for r in self.bridge.pending()), 1)
        altered = copy.deepcopy(req)
        altered["observation"]["turn"] = 2
        self.assert_http(409, "v1/requests", altered)
        invalid = decision(req)
        invalid["actionIds"] = ["missing"]
        self.assert_http(400, "v1/decisions", invalid)
        response = decision(req)
        self.assertEqual(self.bridge.publish_decision(response)["state"], "accepted")
        self.assertEqual(self.bridge.get("lifecycle")["state"], "accepted")
        self.assertEqual(self.bridge.publish_decision(response)["state"], "accepted")
        ack = {key: req[key] for key in IDENTITY}
        ack.update(state="applied", reason="engine_consumed")
        self.assertEqual(self.bridge.call("v1/acks", ack)["state"], "applied")
        self.assertEqual(self.bridge.call("v1/acks", ack)["state"], "applied")

    def test_generation_end_expiry_and_auth(self):
        old = request("generation-old", "generation-duel")
        self.bridge.call("v1/requests", old)
        self.bridge.call("v1/requests", request("generation-new", "generation-duel", 2))
        self.assertEqual(self.bridge.get(old["decisionId"])["state"], "cancelled")
        self.assert_http(409, "v1/decisions", decision(old))
        current = request("end-request")
        self.bridge.call("v1/requests", current)
        self.bridge.call("v1/duels/end", {key: current[key] for key in IDENTITY})
        self.assert_http(409, "v1/decisions", decision(current))
        expired = request("expired-request", seconds=-1)
        self.assert_http(409, "v1/requests", expired)
        original_token = self.bridge.token
        try:
            self.bridge.token = "bad-token"
            self.assert_http(401, "v1/requests", request("unauthorized"))
        finally:
            self.bridge.token = original_token
        bad = request("bad-version")
        bad["protocolVersion"] = 2
        self.assert_http(400, "v1/requests", bad)

    def test_ordered_legality_and_app_context(self):
        req = request("ordered")
        req["choices"].append(dict(req["choices"][0], actionId="next", arguments={"phaseName": "メインフェイズ2"}))
        req["constraints"].update(min=2, max=2, ordered=True, legality="allowed_selections", allowedSelections=[["next", "end"]])
        self.bridge.call("v1/requests", req)
        wrong = decision(req)
        wrong["actionIds"] = ["end", "next"]
        self.assert_http(400, "v1/decisions", wrong)
        traces = []
        app = DecisionApp(self.bridge, MockProvider(), trace=traces.append)
        app.process(req)
        record = self.bridge.get(req["decisionId"])
        self.assertEqual(record["decision"]["actionIds"], ["next", "end"])
        self.assertEqual(app.states["ordered"], "awaiting_applied")
        self.assertEqual(app.context.update(req)["appliedDecisions"], [])
        ack = dict({key: req[key] for key in IDENTITY}, state="applied", reason="fake_engine_consumed")
        self.bridge.call("v1/acks", ack)
        app.step()
        self.assertEqual(app.states["ordered"], "done")
        self.assertEqual(len(app.context.update(req)["appliedDecisions"]), 1)
        self.assertNotIn(self.token, "\n".join(traces))

    def test_separate_python_app_process(self):
        req = request("app-process")
        self.bridge.call("v1/requests", req)
        child = subprocess.Popen([sys.executable, "-m", "jev_app", "--bridge-config", str(self.config), "--provider", "mock"],
                                 cwd=ROOT / "JevApp", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                record = self.bridge.get(req["decisionId"])
                if record["state"] == "accepted":
                    break
                if child.poll() is not None:
                    self.fail("app process exited")
                time.sleep(0.05)
            self.assertEqual(record["state"], "accepted")
            self.assertEqual(record["decision"]["provider"], "mock")
            ack = dict({key: req[key] for key in IDENTITY}, state="applied", reason="fake_client_consumed")
            self.bridge.call("v1/acks", ack)
        finally:
            child.terminate()
            output, errors = child.communicate(timeout=5)
            self.assertNotIn(self.token.encode(), output + errors)

    def test_app_reports_unsupported_request_to_bridge(self):
        req = request("unrenderable")
        req["rawRequest"]["decodeStatus"] = "unsupported"
        self.bridge.call("v1/requests", req)
        app = DecisionApp(self.bridge, MockProvider(), trace=lambda _: None)
        app.step()
        self.assertEqual(app.states["unrenderable"], "failed")
        app.step()
        record = self.bridge.get("unrenderable")
        self.assertEqual(record["state"], "rejected")
        self.assertEqual(record["reason"], "app_unsupported_request")

    def test_context_metadata_keeps_hidden_cards_private(self):
        req = request("context-metadata")
        hidden = {"player": 0, "identityVisible": False, "cardId": 123, "name": "secret"}
        public = {"player": 1, "identityVisible": True, "cardId": 123}
        req["observation"].update(cards=[hidden, public], selectionContext={"role": "target", "sourceCards": [hidden, public]})
        self.bridge.call("v1/requests", req)
        observed = []
        class Provider:
            def choose(self, state, criteria, timeout):
                observed.append(copy.deepcopy(state))
                return MockProvider().choose(state, criteria, timeout)
        app = DecisionApp(self.bridge, Provider(), CardCatalog({123: {"name": "known", "description": "card rules"}}), trace=lambda _: None)
        app.process(req)
        self.assertNotIn("cardId", observed[0]["duel"]["cards"][0])
        self.assertNotIn("name", observed[0]["selection"]["sourceCards"][0])
        self.assertEqual(observed[0]["duel"]["cards"][1]["description"], "card rules")
        self.assertEqual(observed[0]["selection"]["sourceCards"][1]["name"], "known")


class ChoiceChecks(unittest.TestCase):
    def test_dialog_question_is_distinct_from_mixed_explanation(self):
        req = request("mixed-dialog")
        req["observation"]["cards"] = [{"player": 1, "identityVisible": True, "cardId": 123}]
        cards = CardCatalog({123: {"name": "Twin Twisters", "description": "rules"}})
        texts = TextCatalog({"DLG": {"33": "@3Destroy@0 another Spell or Trap card?", "581": '"@3%s@0" is activated.'}})
        choice = {"actionId": "yes", "semanticKind": "yes", "text": "", "cardReferences": [],
                  "arguments": {"textId": 33, "mixedText": [{"type": 1, "value": 581}, {"type": 5, "value": 123}]}}
        label = render_choice(choice, req, cards, texts)
        self.assertIn('"Twin Twisters" is activated.', label)
        self.assertIn("Destroy another Spell or Trap card?", label)
        self.assertNotIn("@3", label)
        req["observation"]["cards"][0]["identityVisible"] = False
        with self.assertRaisesRegex(ValueError, "unresolved_dialog_substitution"):
            render_choice(choice, req, cards, texts)
        req["observation"]["cards"][0]["identityVisible"] = True
        choice["arguments"]["mixedText"].append({"type": 8, "value": 2})
        with self.assertRaisesRegex(ValueError, "unsupported_mixed_dialog_text"):
            render_choice(choice, req, cards, texts)

    def test_game_text_ids_use_indexed_offsets_and_validate_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "en-US").mkdir()
            for group in ("DLG", "WORD"):
                (root / "en-US" / f"{group}_Indx.bytes").write_bytes(struct.pack("<III", 0, 4, 12))
                (root / "en-US" / f"{group}_Text.bytes").write_bytes(b"\0\0\0\0prompt\0\0")
            texts = TextCatalog.from_game(root)
            self.assertEqual(texts.resolve("DLG", 1), "prompt")
            (root / "en-US" / "DLG_Indx.bytes").write_bytes(struct.pack("<III", 0, 100, 12))
            with self.assertRaisesRegex(ValueError, "invalid_text_offset"):
                TextCatalog.from_game(root)

    def test_hidden_instance_labels_and_unknown_legality(self):
        req = request("labels")
        req["observation"]["selectionContext"] = {"role": "target", "parentDecisionId": None}
        cards = CardCatalog({123: {"name": "비공개카드테스트명", "description": "두 개의 효과"}})
        choice = {"actionId": "first", "semanticKind": "select_card", "text": "", "arguments": {},
                  "cardReferences": [{"player": 0, "zone": "필드", "index": 0, "identityVisible": False, "cardId": 123}]}
        self.assertNotIn("비공개카드테스트명", render_choice(choice, req, cards, TextCatalog()))
        visible = copy.deepcopy(choice)
        visible["cardReferences"][0]["identityVisible"] = True
        second = copy.deepcopy(visible)
        second["cardReferences"][0]["index"] = 1
        self.assertNotEqual(render_choice(visible, req, cards, TextCatalog()), render_choice(second, req, cards, TextCatalog()))
        visible["cardReferences"][0]["position"] = 7
        second["cardReferences"][0].update(index=0, position=8)
        self.assertNotEqual(render_choice(visible, req, cards, TextCatalog()), render_choice(second, req, cards, TextCatalog()))
        self.assertNotIn("두 개의 효과", render_choice(visible, req, cards, TextCatalog()))
        req["constraints"]["legality"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unknown_legality"):
            build_question(req, {}, cards, TextCatalog())
        observation = {"cards": [dict(choice["cardReferences"][0], name="secret", uniqueId=7)]}
        self.assertNotIn("cardId", visible_observation(observation)["cards"][0])

    def test_card_metadata_offsets_and_option_limit(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "index").write_bytes(struct.pack("<IIII", 0, 0, 999, 999))
            (root / "name").write_bytes("테스트카드\0".encode())
            (root / "desc").write_bytes(b"description\0")
            (root / "prop").write_bytes(struct.pack("<II", 123, 0))
            cards = CardCatalog.from_files(*(root / p for p in ("index", "name", "desc", "prop")))
            self.assertEqual(cards.get(123)["name"], "테스트카드")
            (root / "index").write_bytes(struct.pack("<IIII", 2, 0, 999, 999))
            with self.assertRaisesRegex(ValueError, "invalid_card_offset"):
                CardCatalog.from_files(*(root / p for p in ("index", "name", "desc", "prop")))
        req = request("many-options")
        req["choices"] = [dict(req["choices"][0], actionId=f"a{i}") for i in range(256)]
        with self.assertRaisesRegex(ValueError, "choice_option_limit"):
            build_question(req, {}, CardCatalog(), TextCatalog())

    def test_retry_cancels_before_second_call(self):
        req = request("retry")
        class Bridge:
            calls = 0
            submitted = []
            def get(self, _):
                self.calls += 1
                return {"request": req, "state": "pending" if self.calls == 1 else "expired"}
            def publish_decision(self, response):
                self.submitted.append(response)
        class Provider:
            calls = 0
            def choose(self, state, criteria, timeout):
                self.calls += 1
                raise RetryableError()
        bridge, provider = Bridge(), Provider()
        app = DecisionApp(bridge, provider, sleep=lambda _: None, trace=lambda _: None)
        app.process(req)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(bridge.submitted, [])
        self.assertEqual(app.states["retry"], "expired")

    def test_real_http_jev_envelope_and_bad_choice(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                criteria = received[-1]["questions"]["action"]["criteria"]
                answer = {"type": "choice", "choice": next(iter(criteria)) if len(received) == 1 else "not-a-choice", "confidence": .9}
                result = json.dumps({"model": "jev-1.13.0", "answers": {"action": answer}}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(result))); self.end_headers(); self.wfile.write(result)
            def log_message(self, *_):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            provider = JevProvider(f"http://127.0.0.1:{server.server_port}/", api_key="test-only-key")
            self.assertEqual(provider.choose({"turn": 1}, {"end": "엔드 페이즈로 진행한다"}, 5).choice, "end")
            self.assertEqual(received[0]["questions"]["action"]["type"], "choice")
            self.assertNotIn("test-only-key", json.dumps(received))
            with self.assertRaisesRegex(ValueError, "invalid_jev_choice"):
                provider.choose({}, {"end": "종료"}, 5)
        finally:
            server.shutdown(); thread.join(); server.server_close()


if __name__ == "__main__":
    unittest.main()
