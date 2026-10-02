# Configuration

## Where settings live

The installer writes `.env` (mode 0600) and `installed.json` to the data directory, `~/.claude/plugins/data/second-opinion/`, or `$SECOND_OPINION_DATA` when set. Both survive plugin updates. The same directory holds your records as local JSON files: profile, ledger, watchlist, journal, statement summaries, spending transactions and rules, saved snapshots, caches, and the Python virtualenv.

Each setting is read in this order, first match wins:

1. the process environment;
2. `.env` in the data directory;
3. `.env` in the plugin root (older installs and checkouts).

Nothing is written back to `.env` by the scripts. It is plaintext, the same trust model as most developer tools; see [SECURITY.md](../SECURITY.md).

`installed.json` records the installed skills, the extras that are on, and (for a guided install) `source_path`, the checkout the installer ran from. Extras are opt-in: only `"<key>": true` turns one on.

## Environment variables

| Variable | Needed for | Meaning |
|---|---|---|
| `SNAPTRADE_CLIENT_ID` / `SNAPTRADE_CONSUMER_KEY` | SnapTrade-backed skills; optional when E*Trade direct is configured | Your SnapTrade Personal API key. |
| `ETRADE_CONSUMER_KEY` / `ETRADE_CONSUMER_SECRET` | optional | Your E*Trade developer key, for connecting E*Trade directly. |
| `ETRADE_SANDBOX` | optional | `1` sends every E*Trade call to E*Trade's sandbox (fake accounts, fake fills). |
| `EDGAR_USER_AGENT` | fundamental-research, stock-screener | The SEC requires a User-Agent with a contact address and returns HTTP 403 without one. Use `"app-name contact@email"`, for example `EDGAR_USER_AGENT="second-opinion me@example.com"`. Quote values with spaces; the unquoted form is read the same way. |
| `BROKER_ACCOUNT_TYPES` | optional | `id=cash,id=margin`, where `id` is the account's `account_id` (a UUID, not your brokerage account number; ask Claude "list my accounts"). Only margin accounts need an entry. `SNAPTRADE_ACCOUNT_TYPES` is still accepted. |
| `SECOND_OPINION_DATA` | optional | Use this directory instead of `~/.claude/plugins/data/second-opinion`. |
| `SECOND_OPINION_PYTHON` | optional | Skip the managed virtualenv and use this interpreter. |

`CLAUDE_PLUGIN_DATA` is deliberately ignored: Claude Code sets it only in hook processes, so scripts would never see it.

A template with comments is in [`.env.example`](../.env.example).
