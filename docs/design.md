# Design decisions

## Use Claude's configuration instead of patching its executable

Claude Code supports user-level [`modelPicker`](https://code.claude.com/docs/en/settings-reference#modelpicker) entries. The installed 2.1.272 build also accepts `behavesAs` on a row, which supplies client-side effort/tool handling without changing the model ID sent upstream. We use a Sonnet 5 handling profile and apply per-model effort caps from Codex's actual catalog. This profile is a compatibility choice, not a claim that GPT has Sonnet's pricing or capabilities.

Gateway `/v1/models` discovery alone is insufficient: Claude Code [filters those results to IDs containing `claude` or `anthropic`](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery). Updating the native picker from Codex's official [`model/list`](https://developers.openai.com/codex/app-server) avoids fabricated model aliases and manual registration.

## Reuse CLIProxyAPI for protocol conversion

[LiteLLM's ChatGPT provider](https://docs.litellm.ai/docs/providers/chatgpt) supports subscription authentication and Responses requests, and its [Claude Code guide](https://docs.litellm.ai/docs/tutorials/claude_responses_api) covers an Anthropic-compatible endpoint. Its existence alone does not establish that every Claude tool flow works. Both projects have had compatibility defects, including [LiteLLM's Claude OAuth header handling](https://github.com/BerriAI/litellm/issues/29572) and [CLIProxyAPI's delayed tool-name streaming](https://github.com/router-for-me/CLIProxyAPI/issues/3471).

This implementation uses CLIProxyAPI 7.3.4 because its standalone macOS binary passed the local model/effort and subagent tool experiments without adding a Python dependency stack. We did not run an equivalent live LiteLLM comparison and do not claim that LiteLLM cannot work. The converter remains replaceable at the HTTP boundary.

## Keep one owner for rotating credentials

Copying a rotating refresh token into another application's auth store creates competing refresh owners. Here, CLIProxyAPI receives only a random local gateway credential. Its translated request returns to the gateway, which attaches the current Codex access token immediately before sending it to OpenAI. Expiring tokens are refreshed through the installed Codex app-server's `account/read` operation. The gateway serializes its own refresh attempts and rereads Codex's credential file for each request.

The app-server is used for authentication and model discovery. It does not execute the coding task: Claude Code remains responsible for tool permissions, file operations, and subagents. Implementing inference through Codex threads and experimental dynamic tools would introduce another agent loop and considerably more state.

## Preserve the user's existing Claude setup

Only Codex models pass through protocol conversion. Claude requests keep their original request bodies, credentials, and beta headers and go to the pre-install Anthropic endpoint. User settings receive a local base URL, one authentication header, picker rows, and effort caps. No global API key or replacement Opus/Sonnet/Haiku alias is installed.

Settings writes are atomic. A private original snapshot supports recovery, while normal removal deletes only owned values instead of restoring an entire old settings file. The same synchronization function drives the manual command and five-minute service refresh.

## Compatibility scope

Anthropic [does not support routing Claude Code to non-Claude models](https://code.claude.com/docs/en/llm-gateway). Codex's subscription backend is not a general public Anthropic-compatible API. Native configuration and the official Codex auth/model interface reduce maintenance work, but cannot guarantee compatibility with every future release. Actual tested behavior is recorded separately from these implementation choices.
