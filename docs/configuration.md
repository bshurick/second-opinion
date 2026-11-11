# Configuration

## Where settings live

The installer writes `.env` (mode 0600) and `installed.json` to the data directory, `~/.claude/plugins/data/second-opinion/`, or `$SECOND_OPINION_DATA` when set. Both survive plugin updates. The same directory holds your records as local JSON files: profile, ledger, watchlist, journal, statement summaries, spending transactions and rules, saved snapshots, caches, and the Python virtualenv.

Each setting is read in this order, first match wins:

1. the process environment;
2. `.env` in the data directory;
3. `.env` in the plugin root (older installs and checkouts).

Nothing is written back to `.env` by the scripts. It is plaintext, the same trust model as most developer tools; see [SECURITY.md](../SECURITY.md).

`installed.json` records the installed skills and (for a guided install) `source_path`, the checkout the installer ran from.

`settings.json` holds every setting, one reader and writer for all scripts. Groups:

| Group | Keys |
|---|---|
| Depth | `depth`, `deep.ask_above` |
| Accounts | `accounts.<id>.role` (trading, retirement or savings; `none` clears it so the account type decides) `margin` (recorded from `BROKER_ACCOUNT_TYPES`; brokerage scripts still read `.env` for now) and `whole_shares` (saved when the broker refuses a fractional order; plans that touch the account size in whole shares) |
| Portfolio plan | `plan.targets` (keys are symbols, classes, `CASH` or the sleeves `PICKS` and `EMPLOYER`), `plan.classes`, `plan.cash_reserve`, `plan.bands`, `plan.sleeves.PICKS` (`target`, `glide` `{to, by}`, `weighting`, `include_light`), `plan.sleeves.EMPLOYER` (`members`, `policy` sell_on_arrival or hold) |
| Taxes | `taxes.short_term_rate`, `taxes.long_term_rate`, `taxes.short_term_gain_policy` |
| Guardrails | `guardrails.pre_buy_check` |
| Replies | `replies.follow_ups`, `replies.pages` |
| Lessons | `lessons` |

Say "show my settings" in Claude, or run `skills/get-started/scripts/settings.py show`, to see each key with its value and default. `settings.py set KEY VALUE` changes one; switches take `on` or `off`. A change applies on the next command, except `replies.follow_ups` and `replies.pages`, which apply from the next session. With no saved choice, the pre-buy check and pages are on, and follow-ups and lessons are off.

On first use after an upgrade (or the installer's first run, whichever comes first), `settings.json` takes in `installed.json`'s extras, `core-satellite.json`, `targets.json`, the profile's account roles and the broker margin flags. `core-satellite.json` and `targets.json` are renamed to `.migrated` (`.migrated.1` if that name is taken), never deleted. A file that cannot be read is left in place and listed under `warnings` in `settings.py show`. This runs once: `meta.migrated_at` records when, and the first session afterwards says the settings moved.

The picks sleeve's size is a target weight: `plan.targets.PICKS` when targets are saved, else `plan.sleeves.PICKS.target`; none leaves its size unmanaged. A glide is a target with a date: new money goes to the sleeve first until it reaches `to`, and the portfolio plan's status shows the monthly pace to get there by `by`.

Settings files are schema 2 since 1.3.0. A schema-1 file upgrades in place on first read and records `"schema 1"` in `meta.migrated_from`: a picks `ceiling` below 1 becomes the sleeve's `target` (a ceiling of 1 or none means no target), a step-up plan becomes a `glide`, and the old `ceiling`, `increases` and `step_up` values are kept under `meta.retired`.

### Depth

`depth` sets how much research an answer gets.

| | Standard (default) | Deep |
|---|---|---|
| Valuation | Quick: scripted DCF, comps, DDM, Graham/Buffett | Researched scenarios by segment, sourced ledger |
| Stock picking | Screen and funnel, light picks | Deep picker, downside gate, deep picks only |
| Reviews (portfolio, property, trades, tax plans) | Scripted answer; deep run on request | Deep run is the default answer |
| Cost | Seconds, little usage | Minutes, 5 to 40 subagents per run |

At deep depth a saved deep result answers until its own re-check says a rerun is due, each deep run is announced with its size, and a request that would start more than `deep.ask_above` (default 3) deep valuations asks first. Light picks already saved are kept and marked as needing a deep valuation. Quotes, ratios, filing sections, option chains and screen candidates are the same at both depths. Six skills have a deep path (valuation, stock-screener, portfolio-analysis, real-estate, tax-aware, trade-review); the others answer as before. The scripts follow a change on the next command, and the session rule from the next session.

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
