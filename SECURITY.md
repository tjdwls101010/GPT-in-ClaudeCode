# Security

Do not post Codex `auth.json`, Claude credentials, the gateway's `config.json`, or full request logs in an issue. A useful non-sensitive report includes OS, Python/Claude/Codex versions, `gpt-in-claude doctor` output, and a minimal reproduction without private prompts.

For a credential leak or other security vulnerability, use [GitHub private vulnerability reporting](https://github.com/tjdwls101010/GPT-in-ClaudeCode/security/advisories/new). Ordinary bugs can be reported through GitHub Issues.

The supported security surface is the current main branch. The gateway binds to loopback and requires a local secret for inference. It cannot isolate credentials from other processes running as the same operating-system user. Do not expose its ports to the network.
