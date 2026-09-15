"""Merge only integration-owned settings; retain a private recovery snapshot."""

import json
import fcntl
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


@contextmanager
def state_lock(state):
    with (state / "sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def write_text(path, value):
    path = Path(path)
    if path.is_symlink():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".gpt-in-claude-")
    try:
        with os.fdopen(fd, "w") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def remove_model_settings(settings, config):
    picker = settings.get("modelPicker", {})
    picker["options"] = [row for row in picker.get("options", []) if row not in config.get("managed_rows", [])]
    caps = settings.get("modelSettings", {})
    for name, cap in config.get("managed_caps", {}).items():
        entry = caps.get(name, {})
        if entry.get("maxEffortLevel") == cap:
            entry.pop("maxEffortLevel", None)
        if not entry:
            caps.pop(name, None)
    original = read_json(Path(config["state_dir"]) / "settings-before.json", {})
    if not caps and "modelSettings" not in original:
        settings.pop("modelSettings", None)
    if not picker.get("options") and "modelPicker" not in original:
        settings.pop("modelPicker", None)


def apply_settings(config):
    path = Path(config["claude_dir"]) / "settings.json"
    settings = read_json(path, {})
    if not isinstance(settings, dict):
        raise ValueError("Claude settings must be a JSON object")
    previous_ids = {row["model"] for row in config.get("managed_rows", [])}
    current_ids = {m["id"] for m in config["models"]}
    if settings.get("model") in previous_ids - current_ids:
        settings["model"] = config["models"][0]["id"]
    remove_model_settings(settings, config)
    env = settings.setdefault("env", {})
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{config['port']}"
    header = "x-gpt-in-claudecode-key: " + config["key"]
    others = [line for line in env.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines() if not line.lower().startswith("x-gpt-in-claudecode-key:")]
    env["ANTHROPIC_CUSTOM_HEADERS"] = "\n".join([*others, header])
    picker = settings.setdefault("modelPicker", {"options": []})
    existing = {row["model"] for row in picker["options"]}
    model_settings = settings.setdefault("modelSettings", {})
    config["managed_rows"] = []
    config["managed_caps"] = {}
    for model in config["models"]:
        if model["id"] not in existing:
            row = {"model": model["id"], "label": model["name"], "description": "Codex login · " + ", ".join(model["efforts"]), "behavesAs": "claude-sonnet-5"}
            picker["options"].append(row)
            config["managed_rows"].append(row)
        entry = model_settings.setdefault(model["id"], {})
        if "maxEffortLevel" not in entry:
            entry["maxEffortLevel"] = model["efforts"][-1]
            config["managed_caps"][model["id"]] = entry["maxEffortLevel"]
    write_json(path, settings)


def restore_settings(config):
    path = Path(config["claude_dir"]) / "settings.json"
    settings = read_json(path, {})
    original = read_json(Path(config["state_dir"]) / "settings-before.json", {})
    remove_model_settings(settings, config)
    env = settings.get("env", {})
    original_env = original.get("env", {})
    if env.get("ANTHROPIC_BASE_URL") == f"http://127.0.0.1:{config['port']}":
        if "ANTHROPIC_BASE_URL" in original_env:
            env["ANTHROPIC_BASE_URL"] = original_env["ANTHROPIC_BASE_URL"]
        else:
            env.pop("ANTHROPIC_BASE_URL", None)
    lines = [line for line in env.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines() if line != "x-gpt-in-claudecode-key: " + config["key"]]
    if lines:
        env["ANTHROPIC_CUSTOM_HEADERS"] = "\n".join(lines)
    else:
        env.pop("ANTHROPIC_CUSTOM_HEADERS", None)
    if not env and "env" not in original:
        settings.pop("env", None)
    if settings.get("model") in {m["id"] for m in config["models"]}:
        if "model" in original:
            settings["model"] = original["model"]
        else:
            settings.pop("model", None)
    write_json(path, settings)
