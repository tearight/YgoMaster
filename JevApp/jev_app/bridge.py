import base64
import json
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit, quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BridgeClient:
    def __init__(self, config_path):
        path = Path(config_path).resolve()
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        parsed = urlsplit(config["prefix"])
        if (not config["enabled"] or parsed.scheme != "http" or
                not ipaddress.ip_address(parsed.hostname).is_loopback or parsed.path != "/" or
                parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("invalid_loopback_config")
        self.prefix = config["prefix"]
        self.token = (path.parent / config["tokenFile"]).read_text().strip()
        if len(base64.b64decode(self.token, validate=True)) != 32:
            raise ValueError("invalid_bridge_token")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, route, data=None):
        body = None if data is None else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        request = Request(self.prefix + route.lstrip("/"), body, {
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with self.opener.open(request, timeout=5) as response:
            raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("response_too_large")
            return json.loads(raw)

    def pending(self):
        return self.call("v1/pending")["records"]

    def get(self, decision_id):
        return self.call("v1/requests/" + quote(decision_id, safe=""))

    def publish_decision(self, result):
        return self.call("v1/decisions", result)
