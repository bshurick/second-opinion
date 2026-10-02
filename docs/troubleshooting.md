# Troubleshooting

Scripts exit with the codes listed in [scripts.md](scripts.md). The data directory below is `~/.claude/plugins/data/second-opinion/` unless `SECOND_OPINION_DATA` is set.

| Symptom | Fix |
|---|---|
| Skills don't appear in Claude | Run `/reload-plugins` or start a new session. `claude plugin list` should show `second-opinion`. For a guided install, check that `~/.claude/skills/second-opinion` exists. |
| A script is blocked with "onboarding has not run" | Say "get started with Second Opinion" to answer the six questions, or "skip for now". The gate opens as soon as a profile exists. |
| Claude Code asks for approval before an order, cancel, or disconnect | That is the hard gate in `hooks/gate.sh`. Approve only if the command matches what you asked for. |
| An order command is blocked in bypass-permissions mode | Intended: a hook cannot ask for approval there. Start a session without bypass mode and confirm the order there. |
| exit 4 `CONFIG_MISSING` | A setting is missing. For brokerage scripts: no key, or only half of a pair (`SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY`, or `ETRADE_CONSUMER_KEY` and `ETRADE_CONSUMER_SECRET`). Re-run the installer or edit `.env` in the data directory. For debt-tracker and spending: nothing is recorded yet; record a statement or import an export first. |
| exit 6 `DEPENDENCY_MISSING` | Python packages did not install. Re-run the installer, or read `install.log` in the data directory. |
| exit 5, `snaptrade_code` 1083 ("Invalid userID or userSecret") | The key has no registered user. The plugin registers one and retries. If it persists, register a user with the key; do not rotate the key. |
| exit 5, `snaptrade_code` 1012 ("does not have a trade type available") | That brokerage offers only read connections. Claude falls back to a read-only connection. |
| exit 5 with `http_status` 401 (other) | Wrong consumer key, or the SDK signature patch failed to load (see `lib/second_opinion/client.py`). |
| exit 5 with `http_status` 429 | Rate limit. Personal keys allow 250 requests a minute overall and 10 a minute per account for holdings, balances, orders, and activities. Wait a minute. |
| `CONNECT_TIMEOUT` while connecting | The portal link expired after 5 minutes. Ask Claude to connect again. |
| Quotes look stale | Yahoo quotes are delayed. Real-time quotes come only from a live E*Trade direct session. |
| exit 4 `ETRADE_REAUTH` | Today's E*Trade token is gone. Claude shows the login link and asks for the code; or ask for the run without E*Trade (`--partial`). |
| exit 4 `ETRADE_NO_PENDING` | The code was entered more than 5 minutes after the link was issued. Start again. |
| exit 5 with `etrade_code` | E*Trade rejected the call; the message names the cause (bad account key, market closed for a market order, unsupported security). |
| Ledger rows counted twice after connecting E*Trade directly | An account synced through SnapTrade and now served directly has a different account id. Run `ledger.py --verify` (look for `duplicate_across_accounts`) and re-import from a clean ledger or a CSV rather than syncing both ids. |
