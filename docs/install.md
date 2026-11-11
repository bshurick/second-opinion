# Installing Second Opinion

Requirements: [Claude Code](https://claude.com/claude-code) and Python 3.10+ on your PATH (`python3 --version`). Node.js 20+ is needed only for the guided installer in a checkout. A brokerage key is optional; see [Connecting brokerages](connecting-brokerages.md).

## Contents

- [Plugin marketplace](#plugin-marketplace)
- [From a checkout](#from-a-checkout)
- [Optional extras](#optional-extras)
- [Scripted and CI installs](#scripted-and-ci-installs)
- [Manual install](#manual-install)
- [Uninstalling](#uninstalling)

## Plugin marketplace

```
/plugin marketplace add bshurick/second-opinion
/plugin install second-opinion@second-opinion
```

Claude Code keeps the plugin files under `~/.claude/plugins/` and replaces them on every update. Every skill is present, including the extra skills, and the extras' behavior (the pre-buy check, suggested follow-up questions) stays off until you turn it on. The session-start hook builds the Python virtualenv in the data directory on first use (log: `install.log` there). Changes apply after `/reload-plugins` or in a new session.

To update, run `claude plugin marketplace update second-opinion`, then `claude plugin update second-opinion@second-opinion`, then restart Claude Code. The next session prints "Second Opinion updated to X".

Say "get started with Second Opinion" in Claude for the first run. Keys are never typed into the chat; run the key entry in your own terminal (hidden input, `.env` at mode 0600, no Node needed):

```bash
python3 ~/.claude/plugins/marketplaces/second-opinion/skills/get-started/scripts/configure.py keys                  # SnapTrade
python3 ~/.claude/plugins/marketplaces/second-opinion/skills/get-started/scripts/configure.py keys --broker etrade   # E*Trade
```

The installer in configure mode, which it picks automatically when run from the marketplace copy, also works (it needs Node):

```bash
node ~/.claude/plugins/marketplaces/second-opinion/install.js
```

It writes only `.env`, `installed.json`, `settings.json`, and the virtualenv in the data directory, and never copies or links files. A missing brokerage key is a warning there, not an error.

## From a checkout

```bash
git clone https://github.com/bshurick/second-opinion
cd second-opinion
node install.js
```

The steps: check Node and Python, choose optional extras (the trade plan on, the others off), choose how brokerages connect (SnapTrade, E*Trade direct, or both) and enter only the keys your selection needs, review the plan, then install. The installer writes to exactly three places:

| | Path |
|---|---|
| plugin | `~/.claude/plugins/second-opinion` |
| data | `~/.claude/plugins/data/second-opinion` |
| link | `~/.claude/skills/second-opinion` |

It builds the target in a sibling directory and swaps it in, so a failed install leaves the previous one intact. Then it builds the virtualenv with the dependencies in `requirements.txt` and runs a smoke test (imports, a DCF calculation, connection status).

Every skill is installed; to leave some out, use `--without` or `--skills` (below). To update, run `cd <checkout> && git pull && node install.js`. Re-run `node install.js` to change extras or uninstall. In Claude, "set up Second Opinion" does the same through the `get-started` skill, which finds your checkout from `source_path` in `installed.json`.

## Optional extras

`trade-journal` is on by default on a fresh install; the others are off unless you turn them on. Reinstalling keeps your earlier choices.

| Key | Label | What it does |
|---|---|---|
| `follow_ups` | Suggested follow-up questions | After each answer, two or three questions you could ask next. The rule lives in `hooks/follow-ups.md` and is loaded at session start. |
| `trade-journal` | Trade plan and pre-buy check | Write down why you are buying, your target and your exit; before each order Claude checks it against that plan. Adds a confirmation step to every buy. Needs trade-review. |
| `financial-education` | Lessons and quizzes | Explains investing concepts one at a time with worked numbers and sources, and quizzes you. |

Toggle them with `settings.py set` (`replies.follow_ups`, `guardrails.pre_buy_check`, `lessons`), by asking Claude ("turn off suggested questions"), by re-running the installer, or with `--extras`. A change applies from the next session.

## Scripted and CI installs

```bash
node install.js --all --yes --json
```

| Flag | Effect |
|---|---|
| `--all`, `--skills a,b`, `--without x,y` | Choose skills; dependencies follow automatically. Default: every core skill, or the previous selection. |
| `--extras follow_ups=on,trade-journal=off,financial-education=off` | Switch optional extras. |
| `--snaptrade-client-id ID --snaptrade-consumer-key KEY` | SnapTrade key. The `SNAPTRADE_*` environment variables also work. |
| `--etrade-consumer-key KEY --etrade-consumer-secret SECRET [--etrade-sandbox]` | E*Trade direct key. |
| `--brokers snaptrade,etrade` | Which connections to configure (default: whichever keys are present). |
| `--edgar-user-agent "app me@example.com"` | SEC contact for EDGAR skills. |
| `--env-file PATH` | Copy credentials from this `.env`. |
| `--target DIR`, `--no-link` | Install elsewhere; do not link into `~/.claude/skills`. |
| `--configure` | Only write settings, extras, and the venv to the data directory (automatic for marketplace installs). |
| `--dry-run` | Show the plan and write nothing. |
| `--no-smoke` | Skip the smoke test. |
| `--yes` | Accept every confirmation and the default for optional prompts. |
| `--json` | One summary object on stdout; never prompts. |
| `--plain` | Line output instead of the guided interface. |
| `--uninstall [--purge-data]` | Remove the install; `--purge-data` also deletes the data directory. |

Exit codes: 0 ok, 1 a named failure (message on stderr), 2 bad arguments. `node install.js --help` prints the current list.

## Manual install

Without the installer, from a checkout:

```bash
claude --plugin-dir "$PWD"                         # per session
ln -s "$PWD" ~/.claude/skills/second-opinion       # or load in every session
```

Put keys in `~/.claude/plugins/data/second-opinion/.env` (start from `.env.example`). The first session's hook creates the virtualenv. To use your own interpreter instead, `export SECOND_OPINION_PYTHON=/path/to/python`. If scripts fail with exit 6 or a path error from the symlinked copy, use `--plugin-dir` or set `SECOND_OPINION_PYTHON`.

## Uninstalling

- Marketplace: `/plugin uninstall second-opinion@second-opinion`.
- Guided: `node install.js --uninstall` from your checkout. Your data directory is kept unless you add `--purge-data`.
