"""Expose model/effort pairs through Claude's named-subagent interface."""

import hashlib
import json
from pathlib import Path
import re

from .settings import claude_model_id, write_text


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def update_agents(config, remove=False):
    directory = Path(config["claude_dir"]) / "agents"
    previous = config.get("managed_agents", {})
    desired = {}
    if not remove:
        for model in config["models"]:
            slug = re.sub(r"[^a-z0-9-]", "-", model["id"].lower())
            for effort in model["efforts"]:
                name = f"codex-{slug}-{effort}"
                description = json.dumps(f"{model['name']} at {effort} effort with a 1M context window. Invoke this subagent without a model override or fork.")
                desired[name + ".md"] = f"---\nname: {name}\ndescription: {description}\nmodel: {claude_model_id(model['id'])}\neffort: {effort}\n---\n\nComplete the assigned task using the available tools. Follow the parent task's instructions and report concrete results.\n"
    managed = {}
    for name, digest in previous.items():
        path = directory / name
        if name not in desired and fingerprint(path) == digest:
            path.unlink()
    for name, content in desired.items():
        path = directory / name
        if path.exists() and fingerprint(path) != previous.get(name):
            continue
        write_text(path, content)
        managed[name] = hashlib.sha256(content.encode()).hexdigest()
    config["managed_agents"] = managed
