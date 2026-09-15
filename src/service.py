"""macOS launchd owns restart-on-failure and start-at-login."""

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time


LABEL = "io.github.tjdwls101010.gpt-in-claudecode"


def stop():
    target = f"gui/{os.getuid()}/{LABEL}"
    if subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0:
        subprocess.run(["launchctl", "bootout", target], check=True, capture_output=True)
        for _ in range(60):
            if subprocess.run(["launchctl", "print", target], capture_output=True).returncode != 0:
                return
            time.sleep(0.25)
        raise RuntimeError("macOS is still stopping the previous gateway; try again shortly")


def register(config):
    state = Path(config["state_dir"])
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    stop()
    value = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(state / "app/run.py"), "--state-dir", str(state), "serve"],
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "WorkingDirectory": str(state), "Umask": 0o077,
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "CODEX_HOME": config["codex_home"]},
        "StandardOutPath": "/dev/null", "StandardErrorPath": str(state / "service-error.log"),
    }
    path.write_bytes(plistlib.dumps(value))
    path.chmod(0o600)
    # launchd can acknowledge bootout before it releases the old registration.
    for _ in range(40):
        result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], capture_output=True, text=True)
        if result.returncode == 0:
            return
        if result.returncode != 5:
            break
        time.sleep(0.25)
    raise RuntimeError(f"Could not register the macOS service: {result.stderr.strip()}")


def unregister():
    stop()
    (Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist").unlink(missing_ok=True)
