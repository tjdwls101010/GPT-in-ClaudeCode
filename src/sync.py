"""One synchronization path for the CLI and the background service."""

import time

from .codex import discover_models
from .agents import update_agents
from .settings import apply_settings, read_json, state_lock, write_json


def sync_models(state):
    with state_lock(state):
        config = read_json(state / "config.json")
        if not config or config.get("installed") is False:
            raise ValueError("Run the installer first")
        models = discover_models(config["codex"], config["codex_home"])
        if models != config["models"]:
            config["models"] = models
            apply_settings(config)
            update_agents(config)
        config["last_sync"] = time.time()
        write_json(state / "config.json", config)
        return config
