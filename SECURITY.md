# Security

Second Opinion can place real orders in your brokerage account, so security reports are taken seriously.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting instead: the **Security** tab of this repository → **Report a vulnerability**. Include the version or commit, what you did, and what happened. You should hear back within a week.

Things that count, for example:

- any way an order, cancellation, or disconnect can run without the user's explicit confirmation;
- credentials (`.env` values, E*Trade tokens, SnapTrade user secrets) leaving the machine other than to the provider they belong to, or showing up in logs, page output, or the conversation;
- a crafted CSV, PDF transcription, filing, or web response that makes a script write outside the plugin's data directory or run code.

## How the plugin handles secrets

- Keys live in a plaintext `.env` file in the plugin's data directory, the same trust model as most developer tools. Only the installer writes that file; the scripts never write keys back or print secrets. One exception by design: E*Trade's authorize link, shown in the chat, carries the consumer key (not the secret), because E*Trade's login flow requires it in the URL.
- Brokerage passwords are entered in SnapTrade's or E*Trade's own pages, never in Claude or this plugin.
- Records are local JSON files under `~/.claude/plugins/data/second-opinion/`.
- Not local: requests to the data providers (SnapTrade, E*Trade, Yahoo Finance, SEC EDGAR, FRED), the conversation with the model, and report pages, which Claude Code publishes as private Artifacts on the user's claude.ai account.

## Supported versions

Only the latest release on `main` receives fixes.
