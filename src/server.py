"""Loopback HTTP boundary for Claude Code and the protocol converter."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import http.client
import json
import logging
import threading
from urllib.parse import urlsplit

from .codex import access_credentials, model_aliases
from .network import tls_context


HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length"}


def connect(base):
    url = urlsplit(base)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Upstream URL must not contain credentials, query, or fragment")
    if url.scheme == "https":
        conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=600, context=tls_context())
    elif url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}:
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=600)
    else:
        raise ValueError("Upstream must use HTTPS or loopback HTTP")
    return conn, url.path.rstrip("/")


def make_server(config):
    credential_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if self.path != "/health":
                self.error(404, "Unknown endpoint")
                return
            try:
                conn, prefix = connect(config["proxy_url"])
                conn.timeout = 2
                conn.request("GET", prefix + "/v1/models", headers={"Authorization": "Bearer " + config["key"]})
                response = conn.getresponse()
                ready = response.status == 200
                conn.close()
            except (OSError, http.client.HTTPException):
                ready = False
            if not ready:
                self.error(503, "Protocol converter is starting or unavailable")
                return
            data = b'{"service":"gpt-in-claudecode","status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def error(self, status, message):
            data = json.dumps({"type": "error", "error": {"type": "invalid_request_error" if status == 400 else "api_error", "message": message}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(data)

        def do_POST(self):
            internal = urlsplit(self.path).path == "/codex/responses"
            key = self.headers.get("x-gpt-in-claudecode-key", "")
            if internal:
                key = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(key, config["key"]):
                self.error(401, "Missing or invalid local gateway key")
                return
            if urlsplit(self.path).path not in {"/v1/messages", "/v1/messages/count_tokens", "/codex/responses"}:
                self.error(404, "Unknown endpoint")
                return
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("A single Content-Length is required")
                length = int(lengths[0])
                if not 0 < length <= 64 * 1024 * 1024:
                    raise ValueError("Request size must be between 1 byte and 64 MiB")
                body = self.rfile.read(length)
                payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
                    raise ValueError("A model string is required")
                blocked = HOP_HEADERS | {"x-gpt-in-claudecode-key"} | {s.strip().lower() for s in self.headers.get("Connection", "").split(",")}
                headers = {k: v for k, v in self.headers.items() if k.lower() not in blocked}
                headers["Accept-Encoding"] = "identity"
                if not internal:
                    payload["model"] = model_aliases(config["models"]).get(payload["model"], payload["model"])
                model = next((m for m in config["models"] if m["id"] == payload["model"]), None)
                if internal:
                    if not model or payload.get("reasoning", {}).get("effort") not in model["efforts"]:
                        raise ValueError("Converter requested an unavailable model or effort")
                    with credential_lock:
                        token, account = access_credentials(config)
                    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token, "Chatgpt-Account-Id": account, "Accept": "text/event-stream"}
                    for name in ["User-Agent", "Originator", "Version", "Session_id", "Session-Id", "X-Client-Request-Id", "OpenAI-Beta", "X-Codex-Turn-State", "X-Codex-Turn-Metadata"]:
                        if self.headers.get(name):
                            headers[name] = self.headers[name]
                    logging.info("codex_request model=%s effort=%s", model["id"], payload["reasoning"]["effort"])
                    self.forward(config["codex_base_url"], "/responses", body, headers)
                elif model:
                    effort = payload.get("output_config", {}).get("effort", model["default_effort"])
                    if effort not in model["efforts"]:
                        raise ValueError(f"{model['id']} supports only: {', '.join(model['efforts'])}")
                    payload.setdefault("output_config", {})["effort"] = effort
                    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + config["key"]}
                    self.forward(config["proxy_url"], self.path, json.dumps(payload).encode(), headers)
                elif payload["model"].startswith("claude-"):
                    self.forward(config["claude_base_url"], self.path, body, headers)
                else:
                    raise ValueError("Model is not in Codex's available list; run gpt-in-claude sync")
            except (ValueError, UnicodeError) as exc:
                self.error(400, str(exc))
            except RuntimeError as exc:
                self.error(503, str(exc))
            except (OSError, http.client.HTTPException):
                if not getattr(self, "sent_headers", False):
                    self.error(502, "Upstream connection failed; check gpt-in-claude doctor")
                self.close_connection = True

        def forward(self, base, path, body, headers):
            conn, prefix = connect(base)
            try:
                conn.request("POST", prefix + path, body, headers)
                response = conn.getresponse()
                if 300 <= response.status < 400:
                    self.error(502, "Upstream redirects are refused to protect credentials")
                    return
                self.send_response(response.status)
                blocked = HOP_HEADERS | {s.strip().lower() for s in response.getheader("Connection", "").split(",")}
                for key, value in response.getheaders():
                    if key.lower() not in blocked:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                self.sent_headers = True
                self.close_connection = True
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                conn.close()

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", config["port"]), Handler)
