"""Report actionable installation health without printing credentials."""

import json
from pathlib import Path
import subprocess
import urllib.request

from .codex import access_credentials
from .settings import read_json


def doctor(state):
    config = read_json(state / "config.json")
    if not config or config.get("installed") is False:
        raise ValueError("No installation found; run python3 -m src install")
    checks = []
    try:
        access_credentials(config)
        checks.append({"check": "Codex login", "ok": True})
    except RuntimeError as exc:
        checks.append({"check": "Codex login", "ok": False, "detail": str(exc)})
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config['port']}/health", timeout=3) as response:
            healthy = json.load(response).get("service") == "gpt-in-claudecode"
        checks.append({"check": "Gateway and converter", "ok": healthy})
    except OSError:
        checks.append({"check": "Gateway and converter", "ok": False, "detail": "Run gpt-in-claude restart; see service-error.log if it fails"})
    settings = read_json(Path(config["claude_dir"]) / "settings.json", {})
    env = settings.get("env", {})
    checks.append({"check": "Claude routing", "ok": env.get("ANTHROPIC_BASE_URL") == f"http://127.0.0.1:{config['port']}" and "x-gpt-in-claudecode-key: " + config["key"] in env.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines()})
    rows = {r["model"] for r in settings.get("modelPicker", {}).get("options", [])}
    checks.append({"check": "Model picker", "ok": all(m["id"] in rows for m in config["models"]), "models": len(config["models"])})
    agents = config.get("managed_agents", {})
    checks.append({"check": "Generated subagents", "ok": len(agents) == sum(len(m["efforts"]) for m in config["models"]) and all((Path(config["claude_dir"]) / "agents" / name).is_file() for name in agents), "agents": len(agents)})
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    return {"ok": all(c["ok"] for c in checks), "claude_version": version, "checks": checks}
