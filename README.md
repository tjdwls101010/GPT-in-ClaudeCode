# GPT in Claude Code

Use your Codex models in Claude Code's **native `/model` menu**, including main conversations and subagents. New models appear automatically from your Codex account; existing Claude models keep their original login.

For **macOS**, **Python 3.11+**, **Claude Code 2.1.267+**, and an installed Codex CLI signed in with ChatGPT using file credential storage. GPT requests use your **Codex subscription allowance**. This is a community integration, not an officially supported OpenAI or Anthropic product.

```text
$ claude --model gpt-5.6-luna --effort low -p 'Reply with exactly INSTALLED_GATEWAY_OK.'
INSTALLED_GATEWAY_OK
```

## Install

Check that `claude --version` and `codex login status` work, then run:

```sh
git clone https://github.com/tjdwls101010/GPT-in-ClaudeCode.git
cd GPT-in-ClaudeCode
python3 -m src install
```

The installer downloads a checksum-verified CLIProxyAPI binary, installs a local background service, and adds the models to your Claude settings. It does not need `sudo`, Docker, pip packages, or changes to the Claude executable.

Expected output:

```text
Registered 5 Codex models. Restart Claude Code and open /model.
```

The count depends on your account. Restart Claude Code, type `/model`, and select a GPT model. Use **← / →** to select effort; press **s** to use the choice for this session or **Enter** to save it. `/effort` and `claude --effort` work too. Each model's supported maximum is applied; `ultra` is excluded.

Verify the installation:

```sh
~/.local/bin/gpt-in-claude doctor
~/.local/bin/gpt-in-claude models
```

`doctor` should report `"ok": true`. If `gpt-in-claude` is not on your PATH, use its full path as above.

## Subagents

The installer also creates a named subagent for **every supported model/effort pair**. They update automatically with the model menu. For example, ask:

```text
Use codex-gpt-5-6-sol-high to review these changes.
```

The Agent tool's `model` argument can be restricted to Claude aliases, so select the generated **subagent name** and omit a separate model override. Avoid fork mode when you want a different model; forks inherit the parent conversation's model. The generated definition supplies the real GPT model and effort.

For a task-specific agent, you can also put a definition in `.claude/agents/gpt-reviewer.md`:

```markdown
---
name: gpt-reviewer
description: Review code using a GPT subagent.
model: gpt-5.6-sol
effort: high
tools: Read, Glob, Grep
---

Read the requested code and return concrete, actionable findings.
```

Then ask Claude Code to use `gpt-reviewer` without overriding its model. The parent and subagent can use different models. Use a model from `gpt-in-claude models`; custom definitions are optional. The `effort` field selects the subagent's effort independently.

## New models and updates

- **Model releases:** the service queries Codex's `model/list` at startup and every five minutes. It updates Claude's model menu, generated subagents, and the converter together. Your installed Codex version and account determine which models are available. Open `/model` again or restart Claude Code to load changed settings.
- **Claude Code updates:** run `claude update` normally. The integration lives in user settings and a separate launchd service, so replacing the Claude executable does not remove it.
- **Login and restart:** launchd starts the service when you sign in to macOS and restarts it after a crash.
- **Integration updates:** run `git pull --ff-only`, then `python3 -m src install` from this repository. Existing unrelated settings are retained. The protocol converter is pinned to a tested release; its version is deliberately not upgraded silently.
- **Refresh now:** run `gpt-in-claude sync`. This is optional; model updates do not require a manual command.

Changes to Claude's configuration format or the upstream Codex protocol can still require an integration update. No binary patch needs to be reapplied.

## How it works

```text
Claude Code ── Claude model ── local gateway ── original Anthropic endpoint
            └─ Codex model ── local gateway ── CLIProxyAPI ── local gateway ── Codex
```

CLIProxyAPI converts Anthropic messages, tools, and streaming events to/from the Codex Responses format. The small local gateway handles routing and credentials. Claude's existing authorization is forwarded only to its original endpoint. GPT requests use the current Codex access token; the converter never receives your Codex refresh token or Claude credentials.

Codex owns token refresh through its app-server. The integration reads `~/.codex/auth.json` and does not write or clone it. If your Codex uses another `CODEX_HOME`, launch the installer with that environment variable set. Keychain-only Codex credential storage is not currently supported.

Both listeners bind to `127.0.0.1`. Inference requests require a random local secret. Credentials and installation state stay in `~/.local/share/gpt-in-claudecode/` with private permissions. Routine logs record model and effort, not prompts or tokens. Requests go to your existing Anthropic endpoint or OpenAI; no third-party hosted proxy is used.

## Troubleshooting and removal

| Symptom | Action |
| --- | --- |
| GPT models are missing | Run `gpt-in-claude doctor`, then `gpt-in-claude sync` and restart Claude Code. Organization-managed model restrictions still take precedence. |
| Gateway is unavailable | Run `gpt-in-claude restart`. Inspect `~/.local/share/gpt-in-claudecode/service-error.log` if startup fails. |
| Codex login is missing or expired | Run `codex login`. File storage is required; for a keychain-only setup, use `codex -c 'cli_auth_credentials_store="file"' login` and configure Codex to keep using file storage. |
| A provider reports a usage limit | Wait for that provider's allowance to reset. GPT uses Codex limits; Claude uses the existing Claude account/API limits. |
| Claude displays a dollar estimate or “Claude Max” on a GPT session | Those are Claude Code's own UI/account estimates. They are not GPT billing or Codex quota measurements. |
| Running with `--bare` | Supply the generated Claude settings explicitly with `--settings`; bare mode skips ordinary user settings and requires its own API-key setting. Normal interactive usage needs neither. |

Remove the integration:

```sh
gpt-in-claude uninstall
```

This stops the service and removes integration-owned settings and the launcher while preserving unrelated and later user edits. Recovery files remain in `~/.local/share/gpt-in-claudecode/`. Restart Claude Code afterward. Your Codex login remains intact.

## Development and evidence

Source files live directly in [`src/`](src/); tests live in [`tests/`](tests/). The Python runtime uses the standard library. [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) owns protocol conversion; this project owns installation, routing, and model synchronization.

```sh
python3 -m unittest discover -s tests -v
python3 tests/live_smoke.py --matrix
```

The first command is isolated and makes no model calls. The second is opt-in and consumes Codex allowance by calling every available model/effort combination through the installed Claude Code gateway. See [validation and compatibility notes](docs/validation.md) for measured results and their limits, and [design decisions](docs/design.md) for the choice of adapter.

## License

MIT. CLIProxyAPI is separately MIT-licensed; its license is downloaded alongside its binary. Claude Code and Codex retain their own licenses and service terms.
