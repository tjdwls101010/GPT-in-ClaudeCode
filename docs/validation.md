# Validation and compatibility

Measured on a local Apple Silicon Mac on **2026-09-15–16**, with **Claude Code 2.1.272**, **Codex CLI 0.154.0**, **CLIProxyAPI 7.3.4**, and **Python 3.12**. These are observed results, not a promise that every future host or model release is compatible.

## Live model/effort matrix

`python3 tests/live_smoke.py --matrix` completed **24/24** calls successfully through the installed gateway and the real Claude Code CLI. Every call returned the expected marker and reported its requested GPT model in `modelUsage`. Gateway metadata also recorded every requested model/effort pair at the final Codex hop.

| Model returned by Codex | Efforts exercised | Passed |
| --- | --- | --- |
| `gpt-6-astra` | low, medium, high, xhigh, max | 5/5 |
| `gpt-5.6-sol` | low, medium, high, xhigh, max | 5/5 |
| `gpt-5.6-terra` | low, medium, high, xhigh, max | 5/5 |
| `gpt-5.6-luna` | low, medium, high, xhigh, max | 5/5 |
| `gpt-5.5` | low, medium, high, xhigh | 4/4 |

The table is a test record, not a hardcoded registration list. The app queries Codex for the current account's models and effort choices. `ultra` is intentionally excluded.

## Real Claude Code flows

- **Native model menu:** opened `/model` in the interactive terminal, confirmed GPT rows alongside the original Claude choices, and exercised the effort arrows. Claude clamps GPT 5.5 to `xhigh` when a request asks for `max`.
- **Different-model subagent:** Luna parent invoked the generated `codex-gpt-5-6-sol-medium` agent. Claude recorded one completed subagent, model usage for both Luna and Sol, and a real `Read` call from Sol. The returned contents matched a randomly generated file. Final-hop metadata showed Sol with `medium` effort.
- **File tools:** a separate installed-gateway run read a file through a subagent and used `Write` in the parent; the written file matched the original contents.
- **Removal and reinstall:** uninstall restored the original Claude settings exactly, removed all 24 generated definitions, and stopped the launchd service. Reinstall restored five picker models and 24 generated agents; `doctor` reported all checks passing.
- **Claude update path:** ran `claude update`; it reported that 2.1.272 was already current. Settings remained usable. This was an updater-path check, not a cross-version upgrade measurement.
- **macOS TLS:** the local Python.org installation initially lacked a default CA bundle. Loading macOS's `/etc/ssl/cert.pem` resolved verified HTTPS without disabling certificate checks.

## Deterministic checks

`python3 -m unittest discover -s tests -v` covers the public CLI and HTTP boundaries: model discovery, generated subagents, repeated installation, preservation of user settings, removal, new and retired models, concurrent synchronization and reinstall, a separately configured `CODEX_HOME`, original upstream routing, local authentication, credential separation, and Codex-owned token refresh.

The Codex subprocess and upstream HTTP services are replaced only at their external boundaries. These tests do not spend model allowance. Live calls above separately exercise the real converter and providers.

A separate read-only code review found five ordinary installation/synchronization defects. Each received a reproduction test and a fix; the follow-up review confirmed all five fixed and found no further release-blocking defect within that scope.

## Limits of this verification

- The existing Claude account was at its session limit. Its real Haiku attempt reported that limit; successful Claude inference through the relay could not be measured in that window. Deterministic tests verify that Claude authorization, beta headers, body, and streaming bytes are forwarded unchanged.
- OAuth expiration and refresh ownership were exercised with an isolated Codex RPC fixture. The real user's credentials were not deliberately expired or modified to force a refresh.
- Short matrix prompts prove routing and effort propagation, not the quality of complex reasoning or indefinite stream stability. Long sessions, unusual MCP schemas, images, context compaction, and every Claude-specific feature are not exhaustively certified.
- Generated subagents use Claude's named-agent interface. Forked agents inherit the parent model; a separate `model` override can supersede an agent definition.
- The host compatibility profile does not make Claude's cost estimates or displayed account label accurate for GPT. Use Codex's own account/usage view for its allowance.
- Keychain-only Codex storage, Windows, Linux service installation, and organization policies that prohibit these models are outside the current installer support scope.
