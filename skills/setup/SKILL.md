---
name: setup
description: Installs, reconfigures, or repairs the Second Opinion plugin — brokerage keys, optional extras, Python dependencies, choosing skills, fixing exit 4/6 errors. Use when the user asks to set up, install, reconfigure, add or remove skills, or reinstall.
---
Installs or reconfigures this plugin by running its installer for the user. Keys are never taken in chat; the user enters them in a terminal.

## Background

- **Two install routes.** The plugin arrives one of two ways. Find out which before running anything.

  | | Plugin install | Guided install |
  |---|---|---|
  | How it was installed | `/plugin marketplace add bshurick/second-opinion`, then `/plugin install second-opinion@second-opinion` | `node install.js` from a git checkout |
  | Where the files are | Under `~/.claude/plugins/cache/`; Claude Code replaces them on every update | The installer copied the chosen skills to `~/.claude/plugins/second-opinion/` and linked it into `~/.claude/skills/` |
  | How to recognise it | `${CLAUDE_PLUGIN_ROOT}/install.js` exists and the path contains `/.claude/plugins/cache/` or `/.claude/plugins/marketplaces/` | The installed copy has no `install.js` |
  | Which skills are present | Every skill, always. Adding or removing skills does not apply; extras do. | The chosen skills |
  | What the installer does | Detects this route and only configures: writes `.env`, the extras record (`installed.json`) and the Python virtualenv to the data directory. It never copies or links files. | Copies skills and the shared library, builds the virtualenv, saves keys and extras, links the plugin, runs a smoke test |
  | `<installer>` | `"${CLAUDE_PLUGIN_ROOT}/install.js"` | `"<source_path>/install.js"` |

- **Finding `source_path` (guided install).** It is the checkout's path, recorded as `source_path` in `installed.json`. Read `~/.claude/plugins/data/second-opinion/installed.json`, else `${CLAUDE_PLUGIN_ROOT}/installed.json`. Run the installer from that checkout.
- **Data directory.** Both routes keep settings in `~/.claude/plugins/data/second-opinion/` (or `$SECOND_OPINION_DATA`), so keys and extras survive plugin updates.
- **Requirements.** The installer needs Node.js 20+, which Claude Code already requires.
- **Brokerage choice.** If a brokerage is needed, the installer asks how it connects: SnapTrade (hosted portal, one free key), E*Trade direct (your developer key, real-time quotes, daily re-auth), or both.
- **Optional extras.** Extras are opt-in: with no record they are off.

  | Key | What it is | Note |
  |---|---|---|
  | `follow_ups` | Suggested follow-up questions | Suggestions change from the next session. |
  | `trade-journal` | The trade plan and pre-buy check | In a guided install, turning it on also installs trade-review. |
  | `financial-education` | Lessons and quizzes | In a plugin install the skill is always present and this only records the choice. |

  The journal and learning progress files stay in the data directory whether an extra is on or off.
- **What the installer writes.** It never modifies the checkout or a plugin-cache copy. It writes only the target directory and link (guided install) and the data directory.
- **Virtualenv rebuilds.** The installer rebuilds the venv when `requirements.txt` changed or the venv is absent. The session-start hook also builds it on first use (log: `install.log` in the data directory).
- **Upgrading from the earlier name (finance-analyst).** The installer and the session-start hook move `~/.claude/plugins/data/finance-analyst` to the new data directory once. The installer (with `--yes`) removes the old `~/.claude/plugins/finance-analyst` copy and its `~/.claude/skills/finance-analyst` link so skills do not load twice. Data is never deleted.

## Scripts

Run with the Bash tool. `<installer>` is the path from the Background table.

```bash
# Plugin install: configure. No selection flags; the installer refuses them here.
node <installer> --json --yes [--extras KEY=on|off,...] [--dry-run]
# Guided install: install or change the skill selection.
node <installer> --json --yes [--all | --without a,b | --skills a,b] [--extras KEY=on|off,...] [--dry-run]
# Either route: turn one extra on or off, or reinstall dependencies (no selection flags).
node <installer> --json --yes [--extras KEY=on|off]
# Guided install only: uninstall.
node <installer> --uninstall --json --yes [--purge-data]
# Key entry: the user runs this themselves in a terminal.
node <installer>
```

With `--json` the installer prints a single JSON object on stdout:

| Field | Meaning |
|---|---|
| `mode` | `configure` (plugin install) or `copy` (guided install) |
| `skills.installed/removed/refreshed` | Copy mode only |
| `extras` | Every optional extra, on or off |
| `dependencies.installed` | Whether Python dependencies were installed |
| `smoke.{imports,dcf,status,etrade}` | Smoke test results |
| `notes`, `warnings` | Show each one verbatim |

| Exit code | Meaning | What to do |
|---|---|---|
| 1 or 2 from the installer | The run failed | Quote the one-line error from stderr and its next step. |
| 4 from any skill script | Missing or invalid key | Have the user run `node <installer>` in a terminal to enter it. |
| 6 from any skill script | Virtualenv missing or broken | Re-run the installer. |

## Steps

Find the route first (Background table). If neither `install.js` exists, ask the user where their checkout is. Then pick the case that matches the request.

**Install or reconfigure**

1. Say in two sentences what will happen.
   - Plugin install: "The installer saves your keys and optional extras in the plugin's data directory and builds a virtualenv with the three Python dependencies; Claude Code keeps managing the plugin files."
   - Guided install: "The installer copies the chosen skills plus the shared library into `~/.claude/plugins/second-opinion/`, builds a virtualenv with the three Python dependencies, saves your keys and extras in the data directory, links the plugin into `~/.claude/skills/`, and runs a smoke test."
2. Guided install only, if the user has not said which skills they want, ask once: "The core skills are installed by default and three optional extras are off (suggested follow-up questions, the trade plan and pre-buy check, and lessons and quizzes); anything to leave out or turn on?" For a plugin install ask only about the extras. Do not ask again.
3. If they ask what exists, show the family list and the extras (with their `label` and `blurb`) from `skills.json`.
4. If a key is needed and none is set, follow "A key is needed" below instead of running the installer yourself.
5. If the user wants to preview the plan before anything is written, run the command with `--dry-run` first.
6. Run the command for the route. For a plugin install, a missing brokerage key is a warning, not an error.
7. Read the JSON object on stdout.
8. Report in plain language: what was installed, removed or configured, whether dependencies were installed, the smoke results, every note and every warning verbatim.
9. If `smoke.status` is `rejected`, point to the connect skill.
10. If `smoke.etrade` is `no_login`, tell the user to say "Connect E*Trade" and paste the code it shows.
11. For a plugin install, say the change applies from the next session or after `/reload-plugins`.
12. After a successful first install, end with: "Now say 'get started with Second Opinion' to answer six short questions about how you invest and see what to try first."

**A key is needed**

1. Tell the user to run the guided installer themselves in a terminal for key entry: `node <installer>`. For a plugin install, give the full `${CLAUDE_PLUGIN_ROOT}` path expanded. It saves the keys in the data directory's `.env`.
2. Or they can export `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY`, or `ETRADE_CONSUMER_KEY` and `ETRADE_CONSUMER_SECRET`, in their shell before starting Claude Code.

**Turn an optional extra on or off**

This case covers "turn off suggested questions", "turn off the trade plan check", "turn off lessons" (or on).

1. Run `node <installer> --json --yes --extras KEY=on|off` with no selection flags, so every other skill and `.env` stay as they are.
2. Report the `extras` block in plain words.

**Reinstall dependencies**

1. Run the same command with no selection flags. The installer keeps the current selection and extras from `installed.json`.

**Uninstall**

- Plugin install: tell the user it is removed with `/plugin uninstall second-opinion@second-opinion`. The installer refuses `--uninstall` there.
- Guided install: run `node <installer> --uninstall --json --yes` only after the user confirms in chat. Add `--purge-data` only if they explicitly ask to delete their ledger, journal, and snapshots.

## Rules

- Never accept secrets in chat. This covers `ETRADE_CONSUMER_KEY` / `ETRADE_CONSUMER_SECRET` as well as the SnapTrade keys.
- Do not ask the user to paste a key, and do not read `.env` back to them.
- Never run `--uninstall` before the user confirms in chat.
- Never add `--purge-data` unless the user explicitly asks to delete their data.
