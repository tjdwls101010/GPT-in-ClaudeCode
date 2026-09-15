"""Pinned, checksum-verified CLIProxyAPI handles the wire-format conversion."""

import hashlib
import io
import platform
import tarfile
import urllib.request

from .settings import write_json
from .network import tls_context


VERSION = "7.3.4"
CHECKSUMS = {
    "arm64": ("aarch64", "42678f1ca09757dbdad0f71b2fb195be56b7575decabf2759b56aaeeacc773d6"),
    "x86_64": ("amd64", "e538047560991bc4c70070d4f9929643325b898dcc8327041c5203e6717db966"),
}


def download(state):
    if platform.system() != "Darwin" or platform.machine() not in CHECKSUMS:
        raise ValueError("Automatic installation currently supports macOS Apple Silicon and Intel")
    arch, expected = CHECKSUMS[platform.machine()]
    destination = state / f"cli-proxy-api-{VERSION}"
    if destination.exists():
        return destination
    url = f"https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/CLIProxyAPI_{VERSION}_darwin_{arch}.tar.gz"
    with urllib.request.urlopen(url, timeout=60, context=tls_context()) as response:
        archive = response.read(96 * 1024 * 1024)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("CLIProxyAPI checksum mismatch; installation stopped")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member, target in [("cli-proxy-api", destination), ("LICENSE", state / "CLIProxyAPI-LICENSE")]:
            source = tar.extractfile(member)
            if source is None:
                raise ValueError("Invalid converter archive")
            target.write_bytes(source.read())
    destination.chmod(0o700)
    return destination


def write_config(config, port):
    from pathlib import Path
    state = Path(config["state_dir"])
    value = {
        "host": "127.0.0.1", "port": port, "auth-dir": str(state / "converter-auth"),
        "api-keys": [config["key"]], "request-retry": 0, "logging-to-file": False,
        "request-log": False, "disable-image-generation": True,
        "streaming": {"keepalive-seconds": 15, "bootstrap-retries": 0},
        "remote-management": {"allow-remote": False, "secret-key": "", "disable-control-panel": True},
        "codex-api-key": [{
            "api-key": config["key"], "base-url": f"http://127.0.0.1:{config['port']}/codex",
            "models": [{"name": m["id"], "alias": m["id"], "display-name": m["name"], "thinking": {"levels": m["efforts"]}} for m in config["models"]],
        }],
    }
    path = state / "converter.json"
    write_json(path, value)
    return path
