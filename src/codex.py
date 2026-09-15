"""Let the installed Codex own login, token refresh, and model discovery."""

import json
import base64
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

from . import __version__


EFFORTS = ("low", "medium", "high", "xhigh", "max")


class CodexRPC:
    def __init__(self, binary="codex", home=None):
        env = dict(os.environ)
        if home:
            env["CODEX_HOME"] = str(home)
        self.process = subprocess.Popen([binary, "app-server", "--stdio", "-c", 'cli_auth_credentials_store="file"'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        self.messages = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.messages.put(None)

    def call(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        while True:
            try:
                message = self.messages.get(timeout=30)
            except queue.Empty:
                raise RuntimeError(f"Codex timed out: {method}") from None
            if message is None:
                raise RuntimeError(f"Codex exited during {method}; run codex login status")
            if message.get("id") != self.sequence:
                continue
            if "error" in message:
                raise RuntimeError(f"Codex rejected {method}: {message['error'].get('message', 'RPC error')}")
            return message["result"]

    def __enter__(self):
        try:
            self.call("initialize", {"clientInfo": {"name": "gpt_in_claudecode", "version": __version__}})
            self.process.stdin.write('{"method":"initialized"}\n')
            self.process.stdin.flush()
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def discover_models(binary="codex", home=None):
    models = []
    with CodexRPC(binary, home) as rpc:
        cursor = None
        while True:
            result = rpc.call("model/list", {"includeHidden": False, "cursor": cursor})
            for entry in result["data"]:
                model = entry["model"]
                if entry.get("hidden") or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]*", model):
                    continue
                efforts = [e for e in EFFORTS if e in {r["reasoningEffort"] for r in entry["supportedReasoningEfforts"]}]
                if efforts:
                    default = entry.get("defaultReasoningEffort")
                    models.append({"id": model, "name": entry.get("displayName", model), "efforts": efforts, "default_effort": default if default in efforts else efforts[0]})
            cursor = result.get("nextCursor")
            if not cursor:
                break
    if not models:
        raise RuntimeError("Codex returned no usable GPT models; run codex login and try again")
    return models


def access_credentials(config):
    path = Path(config["codex_home"]) / "auth.json"

    def read():
        try:
            tokens = json.loads(path.read_text())["tokens"]
            token = tokens["access_token"]
            account = tokens["account_id"]
            claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            return token, account, claims["exp"]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError("Codex ChatGPT credentials unavailable; run codex login (file credential storage required)") from None

    token, account, expires = read()
    if expires < time.time() + 60:
        with CodexRPC(config["codex"], config["codex_home"]) as rpc:
            rpc.call("account/read", {"refreshToken": True})
        token, account, expires = read()
        if expires <= time.time():
            raise RuntimeError("Codex could not refresh its login; run codex login")
    return token, account
