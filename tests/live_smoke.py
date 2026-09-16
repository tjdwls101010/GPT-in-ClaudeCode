"""Opt-in live Claude Code validation; consumes the user's Codex allowance."""

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/share/gpt-in-claudecode")
    parser.add_argument("--matrix", action="store_true", help="Call every discovered model/effort combination")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    config = json.loads((args.state_dir / "config.json").read_text())
    settings = json.loads((Path(config["claude_dir"]) / "settings.json").read_text())
    isolated = {k: settings[k] for k in ["modelPicker", "modelSettings", "env"] if k in settings}
    env = {**os.environ, "ANTHROPIC_API_KEY": "local-smoke-client"}
    cases = [(m["id"], e) for m in config["models"] for e in (m["efforts"] if args.matrix else [m["default_effort"]])]

    def run(case):
        model, effort = case
        selected = model + "[1m]"
        started = time.monotonic()
        command = ["claude", "--bare", "--settings", json.dumps(isolated), "--model", selected, "--effort", effort, "--tools", "", "--system-prompt", "Be concise.", "--no-session-persistence", "-p", "Reply with exactly MODEL_MATRIX_OK.", "--output-format", "json"]
        result = subprocess.run(command, cwd=args.state_dir, env=env, capture_output=True, text=True, timeout=180)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            data = {"result": result.stderr[-500:]}
        context_window = data.get("modelUsage", {}).get(selected, {}).get("contextWindow")
        row = {"model": selected, "effort": effort, "context_window": context_window, "ok": result.returncode == 0 and data.get("result", "").strip() == "MODEL_MATRIX_OK" and context_window == 1000000, "seconds": round(time.monotonic() - started, 2), "result": data.get("result")}
        print(json.dumps(row), flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(run, cases))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2) + "\n")
    raise SystemExit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
