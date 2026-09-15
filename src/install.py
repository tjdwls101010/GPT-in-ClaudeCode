"""Install the user-owned launcher and configuration outside Claude's binaries."""

import os
import json
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import re
import time
import urllib.request

from .codex import discover_models
from .agents import update_agents
from .settings import apply_settings, read_json, restore_settings, state_lock, write_json


def install(args):
    state = Path(args.state_dir).expanduser().absolute()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    with state_lock(state):
        _install(args, state)


def _install(args, state):
    if not args.no_service:
        version = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True).stdout
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (2, 1, 267):
            raise ValueError("Claude Code 2.1.267 or newer is required; run claude update")
    saved = read_json(state / "config.json", {})
    if saved.get("installed") is False:
        saved = {}
    codex_home = saved.get("codex_home", str(Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()))
    models = discover_models(args.codex, codex_home)
    claude_dir = Path(saved.get("claude_dir", args.claude_dir)).expanduser().absolute()
    original = read_json(claude_dir / "settings.json", {})
    if not saved:
        write_json(state / "settings-before.json", original)
    config = saved or {
        "port": args.port,
        "key": secrets.token_urlsafe(32),
        "claude_dir": str(claude_dir),
        "bin_dir": str(Path(args.bin_dir).expanduser().absolute()),
        "codex_home": codex_home,
        "claude_base_url": os.environ.get("ANTHROPIC_BASE_URL") or original.get("env", {}).get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        "codex_base_url": "https://chatgpt.com/backend-api/codex",
    }
    config["codex"] = os.path.abspath(shutil.which(args.codex) or args.codex)
    from .converter import download
    config["proxy_binary"] = str(Path(args.proxy_binary).expanduser().absolute() if args.proxy_binary else download(state))
    config["models"] = models
    config["state_dir"] = str(state)
    config["service"] = not args.no_service
    config["installed"] = True
    if config["service"]:
        from .codex import access_credentials
        access_credentials(config)
    app = state / "app"
    source = Path(__file__).parent
    if source != app / "gpt_in_claudecode":
        shutil.copytree(source, app / "gpt_in_claudecode", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (app / "run.py").write_text("from gpt_in_claudecode.__main__ import main\nmain()\n")
    launcher = Path(config["bin_dir"]) / "gpt-in-claude"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, str(app / "run.py"), "--state-dir", str(state)]) + ' "$@"\n')
    launcher.chmod(0o755)
    write_json(state / "config.json", config)
    if config["service"]:
        from .service import register
        register(config)
        for attempt in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{config['port']}/health", timeout=1) as response:
                    if json.load(response).get("service") == "gpt-in-claudecode":
                        break
            except OSError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError(f"Service did not start. Claude settings were not changed; inspect {state / 'service-error.log'}")
    apply_settings(config)
    update_agents(config)
    write_json(state / "config.json", config)
    print(f"Registered {len(models)} Codex models. Restart Claude Code and open /model.")


def uninstall(state):
    with state_lock(state):
        _uninstall(state)


def _uninstall(state):
    config = read_json(state / "config.json")
    if not config:
        raise ValueError("No installation found")
    if config.get("service"):
        from .service import unregister
        unregister()
    restore_settings(config)
    update_agents(config, remove=True)
    launcher = Path(config["bin_dir"]) / "gpt-in-claude"
    if launcher.exists() and str(state / "app" / "run.py") in launcher.read_text():
        launcher.unlink()
    config["installed"] = False
    write_json(state / "config.json", config)
    print(f"Integration settings removed. Recovery files remain in {state}.")
