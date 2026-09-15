# Contributing

Use Python 3.11 or newer. Source files belong directly in `src/`; keep tests in `tests/`. No Python runtime dependencies are needed.

Run `python3 -m unittest discover -s tests -v` before submitting a change. Test user-visible CLI and HTTP behavior. Use an external Codex/HTTP double for deterministic failure cases; do not couple tests to private helper functions. Reproduce a bug before fixing it.

For changes to routing or protocol configuration, also run `python3 tests/live_smoke.py --matrix` against your own installed integration. This consumes your Codex allowance. Verify a named GPT subagent with a different parent model for changes affecting subagents. Never include authentication files, full request transcripts, or private prompts in a pull request.

Keep protocol translation in CLIProxyAPI rather than duplicating it here. A converter upgrade must update its pinned checksum and include the live validation results. Installation changes must preserve unrelated settings and work on repeated installation and removal.
