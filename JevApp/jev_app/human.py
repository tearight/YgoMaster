"""Local Jev-shaped HTTP endpoint whose answers come only from a person."""
import argparse
import json
import math
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 30000  # Same conservative request budget as the production Jev adapter.


def validate_query(query):
    if (not isinstance(query, dict) or not isinstance(query.get("model"), str) or
            not query["model"] or len(query["model"]) > 4096 or
            not isinstance(query.get("state"), (str, dict, list)) or
            not isinstance(query.get("questions"), dict) or not query["questions"]):
        raise ValueError("invalid_jev_query")
    for key, question in query["questions"].items():
        if not key or not isinstance(question, dict) or not isinstance(question.get("instructions"), (str, dict, list)):
            raise ValueError("invalid_question")
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "choice":
            if not isinstance(criteria, dict) or not 1 <= len(criteria) <= 255 or any(not name for name in criteria):
                raise ValueError("invalid_choice_criteria")
        elif kind == "noul":
            if criteria is not None and (not isinstance(criteria, dict) or not set(criteria) <= {"true", "false"}):
                raise ValueError("invalid_noul_criteria")
        elif kind == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
                raise ValueError("invalid_score_criteria")
        else:
            raise ValueError("unsupported_question_type")
        values = criteria.values() if isinstance(criteria, dict) else criteria or []
        if any(value is not None and not isinstance(value, (str, dict, list)) for value in values):
            raise ValueError("invalid_criteria_description")


def human_response(query, selections):
    if not isinstance(selections, dict) or set(selections) != set(query["questions"]):
        raise ValueError("answer_every_question")
    answers = {}
    for key, question in query["questions"].items():
        value, kind = selections[key], question["type"]
        if kind == "noul":
            if type(value) is not bool:
                raise ValueError("answer_must_be_boolean")
            answers[key] = {"type": "noul", "noul": int(value)}
            continue
        options = question["criteria"] if kind == "choice" else {str(i): label for i, label in enumerate(question["criteria"])}
        if (not isinstance(value, dict) or set(value) != set(options) or
                any(type(flag) is not bool for flag in value.values()) or sum(value.values()) != 1):
            raise ValueError("choose_exactly_one_true")
        chosen = next(option for option in options if value[option])
        answer = {"type": kind, "probabilities": {option: int(value[option]) for option in options}, "confidence": 1}
        if kind == "choice":
            answer["choice"] = chosen
        else:
            answer.update(score=int(chosen), legend={option: label if isinstance(label, str) else json.dumps(label, ensure_ascii=False)
                                                     for option, label in options.items()})
        answers[key] = answer
    return {"model": "human-dummy", "answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}


class HumanServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=49173):
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.jobs, self.lock = OrderedDict(), threading.Lock()

    def expire(self):
        for job in self.jobs.values():
            if job["status"] == "pending" and time.monotonic() >= job["deadline"]:
                job["status"] = "expired"
                job["event"].set()

    def queue(self, query, request_id, timeout):
        fingerprint = json.dumps(query, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with self.lock:
            self.expire()
            if request_id in self.jobs:
                job = self.jobs[request_id]
                if job["fingerprint"] != fingerprint:
                    raise ValueError("request_id_conflict")
                return job
            if sum(job["status"] == "pending" for job in self.jobs.values()) >= 8:
                raise ValueError("human_queue_full")
            # ponytail: retain 64 local jobs; persistent audit storage is outside this interface test.
            while len(self.jobs) >= 64:
                old = next(key for key, job in self.jobs.items() if job["status"] != "pending")
                self.jobs.pop(old)
            job = {"id": request_id, "query": query, "fingerprint": fingerprint, "status": "pending",
                   "deadline": time.monotonic() + timeout, "event": threading.Event(), "response": None}
            self.jobs[request_id] = job
            return job

    def view(self):
        with self.lock:
            self.expire()
            pending = [job for job in self.jobs.values() if job["status"] == "pending"]
            current = pending[0] if pending else None
            completed = [job for job in self.jobs.values() if job["status"] == "answered"]
            return {"pendingCount": len(pending), "job": None if current is None else
                    {"id": current["id"], "query": current["query"], "remainingSeconds": max(0, int(current["deadline"] - time.monotonic()))},
                    "lastResponse": completed[-1]["response"] if completed else None}

    def respond(self, request_id, selections=None, cancel=False):
        with self.lock:
            self.expire()
            job = self.jobs.get(request_id)
            if job is None or job["status"] != "pending":
                raise ValueError("request_no_longer_pending")
            response = None if cancel else human_response(job["query"], selections)
            job["response"], job["status"] = response, "cancelled" if cancel else "answered"
            job["event"].set()
            return {"state": job["status"], "response": response}

    def server_close(self):
        with self.lock:
            for job in self.jobs.values():
                if job["status"] == "pending":
                    job["status"] = "cancelled"
                    job["event"].set()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed(self):
        return (self.headers.get("Host") == self.server.origin.removeprefix("http://") and
                self.headers.get("Origin") in (None, self.server.origin))

    def reply(self, status, value, html=False):
        raw = value.encode() if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY or self.headers.get_content_type() != "application/json":
            raise ValueError("invalid_request_body")
        self.connection.settimeout(5)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete_request_body")
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non_finite_number")))

    def do_GET(self):
        if not self.allowed():
            self.reply(403, {"error": "local_origin_only"})
        elif self.path == "/":
            self.reply(200, Path(__file__).with_name("human.html").read_text(encoding="utf-8"), html=True)
        elif self.path == "/api/pending":
            self.reply(200, self.server.view())
        else:
            self.reply(404, {"error": "unknown_route"})

    def do_POST(self):
        if not self.allowed():
            self.reply(403, {"error": "local_origin_only"})
            return
        try:
            data = self.body()
            if self.path in ("/api/respond", "/api/cancel"):
                if not isinstance(data, dict) or not isinstance(data.get("jobId"), str):
                    raise ValueError("invalid_human_answer")
                self.reply(200, self.server.respond(data["jobId"], data.get("answers"), self.path == "/api/cancel"))
                return
            if self.path != "/v1/systemone":
                self.reply(404, {"error": "unknown_route"})
                return
            validate_query(data)
            timeout = float(self.headers.get("X-Human-Timeout", "600"))
            if not math.isfinite(timeout) or not .01 <= timeout <= 600:
                raise ValueError("invalid_human_timeout")
            request_id = self.headers.get("X-Human-Request-Id") or uuid.uuid4().hex
            if len(request_id) > 128 or not all(char.isalnum() or char in "-_" for char in request_id):
                raise ValueError("invalid_request_id")
            job = self.server.queue(data, request_id, timeout)
            answered = job["event"].wait(max(0, job["deadline"] - time.monotonic()))
            with self.server.lock:
                self.server.expire()
                if not answered and job["status"] == "pending":
                    job["status"] = "expired"
                    job["event"].set()
                status, response = job["status"], job["response"]
            self.reply(200 if status == "answered" else 408 if status == "expired" else 409,
                       response if status == "answered" else {"error": "human_" + status})
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            reason = str(error)
            known = {"request_id_conflict", "human_queue_full", "request_no_longer_pending", "answer_every_question",
                     "answer_must_be_boolean", "choose_exactly_one_true", "invalid_jev_query", "invalid_question",
                     "invalid_choice_criteria", "invalid_noul_criteria", "invalid_score_criteria", "unsupported_question_type",
                     "invalid_criteria_description", "invalid_human_timeout", "invalid_request_id", "invalid_human_answer"}
            reason = reason if reason in known else "invalid_request_body"
            self.reply(429 if reason == "human_queue_full" else 409 if reason in
                       {"request_id_conflict", "request_no_longer_pending"} else 422, {"error": reason})
        except (TimeoutError, ConnectionError):
            self.reply(408, {"error": "incomplete_request_body"})


def main():
    parser = argparse.ArgumentParser(description="Jev 역할을 사용자가 맡는 로컬 인터페이스")
    parser.add_argument("--port", type=int, default=49173)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    with HumanServer(args.port) as server:
        print("직접 선택 화면: " + server.origin, flush=True)
        print("Jev 형식 입력: " + server.origin + "/v1/systemone", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
