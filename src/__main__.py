import argparse
import json
import os
import sys
from pathlib import Path

from .codex import discover_models


def main(argv=None):
    parser = argparse.ArgumentParser(description="Use your Codex models in Claude Code.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--codex", default="codex", help="Codex executable used during installation")
    parser.add_argument("--state-dir", default="~/.local/share/gpt-in-claudecode", help="Private installation directory")
    parser.add_argument("--claude-dir", default=os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"), help="Claude user configuration directory")
    parser.add_argument("--bin-dir", default="~/.local/bin", help="Directory for the gpt-in-claude launcher")
    parser.add_argument("--port", type=int, default=18741, help="Local gateway port (default: 18741)")
    parser.add_argument("--proxy-binary", help="Use a trusted converter binary instead of the verified download")
    parser.add_argument("--no-service", action="store_true", help="Configure only; run serve yourself (development)")
    parser.add_argument("command", choices=["models", "install", "uninstall", "sync", "serve", "doctor", "restart"], help="install/uninstall: configure Claude; sync: refresh models; doctor: health checks")
    parser.add_argument("--json", action="store_true", help="Print models as JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            from .install import install
            install(args)
        elif args.command == "uninstall":
            from .install import uninstall
            uninstall(Path(args.state_dir).expanduser().absolute())
        elif args.command == "sync":
            from .sync import sync_models
            config = sync_models(Path(args.state_dir).expanduser().absolute())
            print(f"Synchronized {len(config['models'])} Codex models.")
        elif args.command == "serve":
            from .runtime import serve
            serve(Path(args.state_dir).expanduser().absolute())
        elif args.command == "doctor":
            from .doctor import doctor
            result = doctor(Path(args.state_dir).expanduser().absolute())
            print(json.dumps(result, indent=2))
            if not result["ok"]:
                raise SystemExit(1)
        elif args.command == "restart":
            from .service import register
            from .settings import read_json
            config = read_json(Path(args.state_dir).expanduser() / "config.json")
            if not config or config.get("installed") is False:
                raise ValueError("No installation found")
            register(config)
            print("Gateway restarted.")
        else:
            from .settings import claude_model_id, read_json
            config = read_json(Path(args.state_dir).expanduser() / "config.json", {})
            models = discover_models(config.get("codex", args.codex), config.get("codex_home"))
            if args.json:
                print(json.dumps(models))
            else:
                for model in models:
                    print(f"{claude_model_id(model['id'])}: {', '.join(model['efforts'])} (default: {model['default_effort']})")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
