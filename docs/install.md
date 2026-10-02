# Installing Second Opinion

Requirements: [Claude Code](https://claude.com/claude-code), Python 3.10+ on your PATH (`python3 --version`), and Node.js 20+ to run the installer. A brokerage key is optional; see [Connecting brokerages](connecting-brokerages.md).

## Contents

- [Plugin marketplace](#plugin-marketplace)
- [Guided installer](#guided-installer)
- [Optional extras](#optional-extras)
- [Scripted and CI installs](#scripted-and-ci-installs)
- [Manual install](#manual-install)
- [Uninstalling](#uninstalling)

## Plugin marketplace

```
/plugin marketplace add bshurick/second-opinion
/plugin install second-opinion@second-opinion
```

Claude Code keeps the plugin files under `~/.claude/plugins/` and replaces them on every update. Every skill is present, including the extra skills; the skill picker does not apply to this route, and the extras' behavior (the pre-buy check, suggested follow-up questions) stays off until you turn it on. The session-start hook builds the Python virtualenv in the data directory on first use (log: `install.log` there). Changes apply after `/reload-plugins` or in a new session.

Keys and extras are set with the installer in configure mode, which it picks automatically when run from the marketplace copy:

```bash
node ~/.claude/plugins/marketplaces/second-opinion/install.js
```

It writes only `.env`, `installed.json`, and the virtualenv in the data directory, and never copies or links files. A missing brokerage key is a warning there, not an error. You can also say "set up Second Opinion" in Claude: the `setup` skill runs the installer for extras and dependencies, and for keys it tells you which command to run in your own terminal. Keys are never typed into the chat.

## Guided installer

```bash
git clone https://github.com/bshurick/second-opinion
cd second-opinion
node install.js
```

The steps: check Node and Python, choose the core skills (all preselected), choose optional extras (all off), choose how brokerages connect (SnapTrade, E*Trade direct, or both) and enter only the keys your selection needs, review the plan, then install. The installer writes to exactly three places:

| | Path |
|---|---|
| plugin | `~/.claude/plugins/second-opinion` |
| data | `~/.claude/plugins/data/second-opinion` |
| link | `~/.claude/skills/second-opinion` |

It builds the target in a sibling directory and swaps it in, so a failed install leaves the previous one intact. Then it builds the virtualenv with the dependencies in `requirements.txt` and runs a smoke test (imports, a DCF calculation, connection status).

Re-run `node install.js` from your checkout to add or remove skills, change extras, pick up a newer checkout (`git pull` first), or uninstall. In Claude, "set up Second Opinion" does the same through the `setup` skill, which finds your checkout from `source_path` in `installed.json`.

## Optional extras

All off unless you turn them on:

| Key | Label | What it does |
|---|---|---|
| `follow_ups` | Suggested follow-up questions | After each answer, two or three questions you could ask next. The rule lives in `hooks/follow-ups.md` and is loaded at session start. |
| `trade-journal` | Trade plan and pre-buy check | Write down why you are buying, your target and your exit; before each order Claude checks it against that plan. Adds a confirmation step to every buy. Needs trade-review. |
| `financial-education` | Lessons and quizzes | Explains investing concepts one at a time with worked numbers and sources, and quizzes you. |

Toggle them by re-running the installer, with `--extras`, or by asking Claude ("turn off suggested questions"). In the guided installer, press `c` on the extras step to choose every skill individually.

## Scripted and CI installs

```bash
node install.js --all --yes --json
```

| Flag | Effect |
|---|---|
| `--all`, `--skills a,b`, `--without x,y` | Choose skills; dependencies follow automatically. Default: the core skills, or the previous selection. |
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
