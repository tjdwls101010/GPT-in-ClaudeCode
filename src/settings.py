"""Merge only integration-owned settings; retain a private recovery snapshot."""

import json
import fcntl
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

from .codex import model_aliases


MAX_CONTEXT = "CLAUDE_CODE_MAX_CONTEXT_TOKENS"
MODEL_CAPABILITIES = "CLAUDE_CODE_MODEL_CAPABILITIES"


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


def claude_model_id(model_id):
    """Declare the client window; Claude strips this suffix before inference."""
    return model_id + "[1m]"


def restore_alias_environment(env, config):
    for key, entry in config.get("managed_alias_env", {}).items():
        if env.get(key) == entry["value"]:
            if entry["before"] is None:
                env.pop(key, None)
            else:
                env[key] = entry["before"]
        elif key == MODEL_CAPABILITIES and key in env:
            remaining = [rule for rule in env[key].split(";") if rule not in config.get("alias_capability_rules", [])]
            if any(remaining):
                env[key] = ";".join(remaining)
            else:
                env.pop(key, None)
    config["managed_alias_env"] = {}
    config["alias_capability_rules"] = []


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
    aliases = model_aliases(config["models"])
    previous_ids = {row["model"] for row in config.get("managed_rows", [])} | set(config.get("managed_aliases", {}))
    base_ids = {m["id"] for m in config["models"]}
    current_ids = {claude_model_id(model_id) for model_id in base_ids} | set(aliases)
    if settings.get("model") in base_ids:
        settings["model"] = claude_model_id(settings["model"])
    elif settings.get("model") in previous_ids - current_ids:
        settings["model"] = claude_model_id(config["models"][0]["id"])
    remove_model_settings(settings, config)
    env = settings.setdefault("env", {})
    restore_alias_environment(env, config)
    if aliases:
        rules = [f"{alias}=effort,xhigh_effort,max_effort,adaptive_thinking" for alias in aliases]
        values = {MAX_CONTEXT: "1000000", MODEL_CAPABILITIES: ";".join([env.get(MODEL_CAPABILITIES, ""), *rules]).lstrip(";")}
        config["managed_alias_env"] = {key: {"before": env.get(key), "value": value} for key, value in values.items()}
        config["alias_capability_rules"] = rules
        env.update(values)
    config["managed_aliases"] = aliases
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
        model_id = claude_model_id(model["id"])
        if model_id not in existing:
            row = {"model": model_id, "label": model["name"] + " (1M context)", "description": "Codex login · " + ", ".join(model["efforts"]), "behavesAs": "claude-sonnet-5"}
            picker["options"].append(row)
            config["managed_rows"].append(row)
    caps = {model["id"]: model["efforts"][-1] for model in config["models"]}
    caps.update({alias: caps[target] for alias, target in aliases.items()})
    for name, cap in caps.items():
        entry = model_settings.setdefault(name, {})
        if "maxEffortLevel" not in entry:
            entry["maxEffortLevel"] = cap
            config["managed_caps"][name] = cap
    write_json(path, settings)


def restore_settings(config):
    path = Path(config["claude_dir"]) / "settings.json"
    settings = read_json(path, {})
    original = read_json(Path(config["state_dir"]) / "settings-before.json", {})
    remove_model_settings(settings, config)
    env = settings.get("env", {})
    restore_alias_environment(env, config)
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
    if settings.get("model", "").removesuffix("[1m]") in {m["id"] for m in config["models"]} | set(config.get("managed_aliases", {})):
        if "model" in original:
            settings["model"] = original["model"]
        else:
            settings.pop("model", None)
    write_json(path, settings)
