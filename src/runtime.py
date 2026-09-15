"""Run the gateway, supervise its converter, and refresh models automatically."""

import logging
from logging.handlers import RotatingFileHandler
import signal
import socket
import subprocess
import threading

from .converter import write_config
from .server import make_server
from .settings import read_json
from .sync import sync_models


def serve(state):
    handler = RotatingFileHandler(state / "events.log", maxBytes=2_000_000, backupCount=2)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(message)s")
    config = read_json(state / "config.json")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config["proxy_url"] = f"http://127.0.0.1:{port}"
    server = make_server(config)
    converter = subprocess.Popen([config["proxy_binary"], "-config", str(write_config(config, port))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=state)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def refresh():
        while not stopped.is_set():
            try:
                sync_models(state)
            except (OSError, RuntimeError, ValueError) as exc:
                logging.warning("Model refresh failed; keeping last working catalog: %s", exc)
            stopped.wait(300)

    threading.Thread(target=refresh, daemon=True).start()
    try:
        while not stopped.wait(1):
            if converter.poll() is not None:
                raise RuntimeError("Protocol converter exited; launchd will restart the service")
            # A manual sync updates the same persisted catalog without restarting active streams.
            updated = read_json(state / "config.json")
            if updated["models"] != config["models"]:
                config["models"] = updated["models"]
                write_config(config, port)
                logging.info("Model catalog updated: %s models", len(config["models"]))
    finally:
        server.shutdown()
        server.server_close()
        converter.terminate()
        try:
            converter.wait(timeout=5)
        except subprocess.TimeoutExpired:
            converter.kill()
            converter.wait()
