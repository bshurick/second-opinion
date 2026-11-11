---
name: get-started
description: Runs the first-run flow and keeps the plugin set up, with keys, accounts, depth, the plan, the profile, settings and extras. Use when the user says "get started", "set up", "show my settings", "change a setting", "reinstall" or a script exits 4 or 6.
---
The plugin's front door and its maintenance. "Get started with Second Opinion" runs the first-run flow; the same skill installs, reconfigures and repairs the plugin, shows and changes settings, and keeps the profile. Keys are never taken in chat; the person enters them in a terminal.

## Background

**Install and settings**

- **Two install routes.** The plugin arrives one of two ways. Find out which before running anything.

  | | Plugin install | Guided install |
  |---|---|---|
  | How it was installed | `/plugin marketplace add bshurick/second-opinion`, then `/plugin install second-opinion@second-opinion` | `node install.js` from a git checkout |
  | Where the files are | Under `~/.claude/plugins/cache/`; Claude Code replaces them on every update | The installer copied the chosen skills to `~/.claude/plugins/second-opinion/` and linked it into `~/.claude/skills/` |
  | How to recognise it | `${CLAUDE_PLUGIN_ROOT}/install.js` exists and the path contains `/.claude/plugins/cache/` or `/.claude/plugins/marketplaces/` | The installed copy has no `install.js` |
  | Which skills are present | Every skill, always. Adding or removing skills does not apply; extras do. | The chosen skills |
  | What the installer does | Detects this route and only configures: writes `.env`, the extras record in `settings.json` and the Python virtualenv to the data directory. It never copies or links files. | Copies skills and the shared library, builds the virtualenv, saves keys and extras, links the plugin, runs a smoke test |
  | `<installer>` | `"${CLAUDE_PLUGIN_ROOT}/install.js"` | `"<source_path>/install.js"` |

- **Finding `source_path` (guided install).** It is the checkout's path, recorded as `source_path` in `installed.json`. Read `~/.claude/plugins/data/second-opinion/installed.json`, else `${CLAUDE_PLUGIN_ROOT}/installed.json`. Run the installer from that checkout.
- **Data directory.** Both routes keep settings in `~/.claude/plugins/data/second-opinion/` (or `$SECOND_OPINION_DATA`), so keys and extras survive plugin updates.
- **Requirements.** The installer needs Node.js 20+, which Claude Code already requires.
- **Brokerage choice.** If a brokerage is needed, the installer asks how it connects: SnapTrade (hosted portal, one free key), E*Trade direct (your developer key, real-time quotes, daily re-auth), or both.
- **Optional extras.** With no record, `trade-journal` is on and the others are off. A choice in the record always stands.

  | Key | What it is | Note |
  |---|---|---|
  | `follow_ups` | Suggested follow-up questions | Setting `replies.follow_ups`. Suggestions change from the next session. |
  | `trade-journal` | The trade plan and pre-buy check | Setting `guardrails.pre_buy_check`. In a guided install, turning it on also installs trade-review. |
  | `financial-education` | Lessons and quizzes | Setting `lessons`. In a plugin install the skill is always present and this only records the choice. |

  The journal and learning progress files stay in the data directory whether an extra is on or off.
- **What the installer writes.** It never modifies the checkout or a plugin-cache copy. It writes only the target directory and link (guided install) and the data directory.
- **Virtualenv rebuilds.** The installer rebuilds the venv when `requirements.txt` changed or the venv is absent. The session-start hook also builds it on first use (log: `install.log` in the data directory).
- **Upgrading from the earlier name (finance-analyst).** The installer and the session-start hook move `~/.claude/plugins/data/finance-analyst` to the new data directory once. The installer (with `--yes`) removes the old `~/.claude/plugins/finance-analyst` copy and its `~/.claude/skills/finance-analyst` link so skills do not load twice. Data is never deleted.

**The profile**

- **Storage.** The profile lives in `profile.json` under the plugin data directory. Every field records whether it was declared or confirmed and when.
- **What the profile steers.** Order and framing only. It shapes the session context and the next-steps list, and nothing else. The trading and valuation skills do not read it. Portfolio and risk reports are the same for everyone.
- **Session context line.** The line at the start of every session comes from `context`. It is derived from the file and never stored.
- **Proposals.** Observations about the user become proposals. A proposal becomes a field only on a yes. `show` lists pending proposals.
- **`set` creates the file.** When no profile exists, `set` creates it with onboarding status "skipped", so an interview that stops halfway keeps its answers.
- **Fields and values.**

  | Field | Values |
  |---|---|
  | `approach` | value, growth, dividend, index, technical, unsure; several allowed |
  | `horizon` | years, months, weeks, mixed |
  | `risk_appetite` | low, moderate, high |
  | `experience` | beginner, intermediate, experienced |
  | `goals` | free text; several allowed |
  | `pre_trade_check` | valuation, fundamentals, chart, none |
  | `account_roles` | `id=trading,id=retirement,id=savings`, ids from the connect skill's status; saved to settings.json, not `profile.json` |
  | `trades_actively` | yes/no |
  | `uses_options` | yes/no |

## Scripts

Run with the Bash tool. `<installer>` is the path from the Background table.

```bash
# Plugin install: configure. No selection flags; the installer refuses them here.
node <installer> --json --yes [--extras KEY=on|off,...] [--dry-run]
# Guided install: install or change the skill selection.
node <installer> --json --yes [--all | --without a,b | --skills a,b] [--extras KEY=on|off,...] [--dry-run]
# Either route: reinstall dependencies (no selection flags).
node <installer> --json --yes [--extras KEY=on|off]
# Guided install only: uninstall.
node <installer> --uninstall --json --yes [--purge-data]
# Key entry: the user runs this themselves in a terminal.
node <installer>
```

Key entry without Node, for the person to run in their own terminal (exits 2 when stdin is not a terminal):

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/configure.py" keys [--broker snaptrade|etrade]
```

Settings, the version and the update command (no installer):

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/settings.py" show
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/settings.py" set KEY VALUE
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/settings.py" version
```

Account roles (the first run's accounts step): every connected account with `proposed_role`, `saved_role`, `role` and `margin`. `--accept` saves the proposal for each account with no saved role and never overwrites one.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/roles.py" [--accept] [--partial]
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
| 4 from any skill script | Missing or invalid key | Follow "A key is needed": the person runs `configure.py keys` in their own terminal. |
| 6 from any skill script | Virtualenv missing or broken | Re-run the installer. |

The profile:

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" set <field> <value...>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" unset <field>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" show
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" skip
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" complete
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" learning on|off
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" next-steps [--offline]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" context
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/profile.py" delete --confirm
```

| Command | What it does |
|---|---|
| `set` | Saves a declared answer. Lists are comma-separated. |
| `unset` | Removes a field. `unset account_roles` clears every account role in settings, so the account type decides again. |
| `show` | Prints the profile, pending proposals and whether learning is on. |
| `skip` | "Skip for now": opens the gate and asks nothing again. |
| `complete` | Marks the interview finished. |
| `learning on\|off` | Turns learning about the user on or off. Declared answers stay. |
| `next-steps` | Prints setup actions and starter questions in two groups. `--offline` skips the connected-accounts lookup. |
| `context` | Prints ONE plain-text line for the session-start hook. |
| `delete --confirm` | Deletes the profile. |

Every command prints one JSON object except `context`.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad field or value | `error`; it names the allowed values |
| 3 | `delete` without `--confirm` | ask the user to confirm first |
| 4 `NO_PROFILE` | Nothing saved yet | start the interview |
| 5 `PROFILE_CORRUPT` | Damaged file | `hint` |
| 6 | Python dependencies missing | "Reinstall dependencies" above |

## Steps

**"Get started with Second Opinion": the first run**

Seven steps, one at a time. Each step is checked first and skipped when it is already done, so the flow can stop at any step and pick up there next time. Say at the start which steps are already done.

| Step | Done when | What the person does | Skippable |
|---|---|---|---|
| 1. Check | `profile.py show` exits 0 or 4 | Nothing | no |
| 2. Keys | connect's `status.py` exits 0 | Runs `configure.py keys` in their own terminal | yes, for research-only use |
| 3. Connect | `status.py` lists accounts | Signs in through the connect skill | yes |
| 4. Accounts | every account in `roles.py` has a `saved_role` | Confirms the roles table | with step 3 |
| 5. Depth | `settings.py show` gives `depth` a `changed_on` date | Picks Standard or Deep | defaults to Standard |
| 6. Portfolio plan | the four standing answers below are saved | Answers each, or skips | yes |
| 7. About you | `profile.json` exists | Answers three questions | yes ("skip for now") |

1. **Check.** Run `profile.py show`. Exit 6 or a path error means the install is broken: go to "Reinstall dependencies" and stop.
2. **Keys.** If `status.py` exits 4 for missing credentials, follow "A key is needed". Keys never enter the chat. Wait for the person to say the keys are saved, then check again.
3. **Connect.** Hand off to the connect skill to link a brokerage, then come back to step 4.
4. **Accounts.** Run `roles.py` and show a table: Account · Type · Proposed role · Margin.
   - Say what a role decides: trading is taxable and holds picks, and its core funds can be sold to fund picks; retirement is tax-advantaged and holds no picks; savings is taxable and holds no picks.
   - On a yes, run `roles.py --accept`. For a different role, run `settings.py set accounts.<id>.role ROLE` for that account first.
5. **Depth.** State what each choice costs, as in "Change depth", and save the answer. No answer leaves Standard.
6. **Portfolio plan.** Run the portfolio-plan skill's `plan.py status` and ask each unset standing answer once, one per message. Each one is saved with `settings.py set` and never asked again.

   | Question | Saved as |
   |---|---|
   | "Do you hold your employer's stock?" (offer `employer_candidate` from the run when present) | `plan.sleeves.EMPLOYER.members TICKER` or `none` |
   | "What share of the portfolio should your own stock picks be?" | `plan.sleeves.PICKS.target 0.1`, or `none` to leave it unmanaged |
   | "How much cash should stay out of the plan?" | `plan.cash_reserve AMOUNT` |
   | "Can a plan sell into short-term gains?" | `taxes.short_term_gain_policy hold` or `allow` |

   A skipped question stays unset, and plans use the stated default for it (`STANDING_DEFAULT`).
7. **About you.** Frame it in one sentence: "Three short questions about how you invest, so the plugin knows which analysis to lead with. Say 'skip for now' to answer later." If they skip, run `skip` and never raise it again unless asked. Otherwise run "The three questions" below.
8. Run `next-steps` and render its two groups verbatim as "Set up" and "Try asking", each item on its own line so the person can say it word for word.
9. If the person came in with another request (the session context said no profile exists), complete it now.

**The three questions**

Ask one question per message. Wait for the answer. Run `profile.py set` for that field before asking the next. Every question is skippable: "skip" moves on without writing. Offer the choices below and accept anything close in meaning; map it to the vocabulary and say the value you saved.

1. "How do you decide what to buy?" (what the business is worth / growth prospects / dividends / index funds / charts and momentum / not sure yet; several allowed) → `approach` value, growth, dividend, index, technical, unsure
2. "How long do you usually hold an investment?" (years / months / weeks or less / it varies) → `horizon` years, months, weeks, mixed
3. "Before you buy something, what do you want to have looked at first?" (a valuation / the fundamentals / the chart / nothing extra) → `pre_trade_check`. Say that it is recorded in the profile and shown in the session context line, so the check they named can be run before a buy when they ask for one; nothing blocks an order on it.
4. Run `complete`.

The other profile fields (`risk_appetite`, `experience`, `goals`, `trades_actively`, `uses_options`) are never asked. The person can set them in their own words later ("update my profile").

**When a profile already exists** and the person says "get started", offer to revisit the steps, with the current answers shown.

For the install and settings cases below, find the route first (Background table). If neither `install.js` exists, ask the user where their checkout is. Then pick the case that matches the request.

**Install or reconfigure**

1. Say in two sentences what will happen.
   - Plugin install: "The installer saves your keys and optional extras in the plugin's data directory and builds a virtualenv with the three Python dependencies; Claude Code keeps managing the plugin files."
   - Guided install: "The installer copies the chosen skills plus the shared library into `~/.claude/plugins/second-opinion/`, builds a virtualenv with the three Python dependencies, saves your keys and extras in the data directory, links the plugin into `~/.claude/skills/`, and runs a smoke test."
2. Guided install only, if the user has not said which skills they want, ask once: "The core skills and the trade plan and pre-buy check are installed by default, and two optional extras are off (suggested follow-up questions, and lessons and quizzes); anything to leave out or turn on?" For a plugin install ask only about the extras. Do not ask again.
3. If they ask what exists, show the family list and the extras (with their `label` and `blurb`) from `skills.json`.
4. If a key is needed and none is set, follow "A key is needed" below instead of running the installer yourself.
5. If the user wants to preview the plan before anything is written, run the command with `--dry-run` first.
6. Run the command for the route. For a plugin install, a missing brokerage key is a warning, not an error.
7. Read the JSON object on stdout.
8. Report in plain language: what was installed, removed or configured, whether dependencies were installed, the smoke results, every note and every warning verbatim.
9. If `smoke.status` is `rejected`, point to the connect skill.
10. If `smoke.etrade` is `no_login`, tell the user to say "Connect E*Trade" and paste the code it shows.
11. For a plugin install, say the change applies from the next session or after `/reload-plugins`.
12. After a successful first install, end with: "Now say 'get started with Second Opinion' to connect your accounts, set up your plan and see what to try first."

**A key is needed**

1. Tell the user to run the key entry themselves in their own terminal, with the `${CLAUDE_PLUGIN_ROOT}` path expanded: `python3 "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/configure.py" keys`.
   - Add `--broker etrade` for an E*Trade developer key.
   - It needs no Node, hides what they type, and saves the keys in the data directory's `.env` at mode 0600. A guided install can use `node <installer>` instead.
2. Or they can export `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY`, or `ETRADE_CONSUMER_KEY` and `ETRADE_CONSUMER_SECRET`, in their shell before starting Claude Code.

**Turn an optional extra on or off**

This case covers "turn off suggested questions", "turn off the trade plan check", "turn off lessons" (or on). It changes a setting, not the installed skills, so it does not run the installer.

1. Pick the key: `replies.follow_ups` (suggested questions), `guardrails.pre_buy_check` (trade plan check) or `lessons` (lessons and quizzes).
2. Run `"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/settings.py" set KEY on|off`.
3. For `replies.follow_ups`, say the change applies from the next session. The other two apply on the next command.

**Turn report pages on or off**

1. Run `settings.py set replies.pages on|off`. Off means answers come in chat with no report page.
2. Say the change applies from the next session.

**Show my settings**

1. Run `settings.py show`.
2. Reply with one table per group, with the columns label, value and meaning. Mark a row whose `is_default` is true as default.
3. Under the Depth table, list `deep_paths`: the skills with a deep path and what each one is. Say that deep does nothing more in other skills.
4. If `warnings` is not empty, list each one verbatim.

**Change depth**

Change it only when the person asks in their own words, as for any setting.

1. Before setting it, state what each choice costs. Standard: seconds and little usage per answer, with a deep run on request. Deep: minutes and 5 to 40 research subagents per run, a deep valuation or deep pick only, and a question first when a request would start more than `deep.ask_above` (default 3) deep valuations.
2. Run `settings.py set depth deep` or `settings.py set depth standard`.
3. Say the scripts follow it on the next command, and the session's depth rule from the next session.

**Change a setting**

Change a setting only when the person asks for that change in their own words, never on Claude's initiative: not to make an answer work, not because a value looks wrong, not as a follow-up suggestion carried out unasked.

1. Find the key in `settings.py show` that matches the person's own words. If none matches, say so and show the group.
2. Run `settings.py set KEY VALUE` with the value they gave.
3. Report the new value. Say it applies on the next command, or from the next session for `replies.follow_ups` and `replies.pages`.

**Check my setup or is there an update**

1. Run `settings.py version`.
2. Report `installed`, `latest` (say it is unknown when null) and `update_command`. Nothing updates itself; the person runs the command and restarts Claude Code.

**Reinstall dependencies**

1. Run the same command with no selection flags. The installer keeps the current selection from `installed.json` and the extras from `settings.json`.

**Uninstall**

- Plugin install: tell the user it is removed with `/plugin uninstall second-opinion@second-opinion`. The installer refuses `--uninstall` there.
- Guided install: ask with the confirmation block in Reply format, then run `node <installer> --uninstall --json --yes` only after the user confirms in chat. Add `--purge-data` only if they explicitly ask to delete their ledger, journal, and snapshots.

**Edits and questions later**

| The user says | Do |
|---|---|
| "Show my profile" | Run `show` and reply with the format below. |
| "Update my profile ..." | Run `set`. |
| "Forget ..." | Run `unset`. |
| "What should I try next" | Run `next-steps`. |
| "Stop learning about me" | Run `learning off`. Declared answers stay. |
| "Delete my profile" | Ask once with the confirmation block in Reply format, then run `delete --confirm` on a yes. |

**`show` lists pending proposals**

1. Finish the user's current request first.
2. Raise at most one proposal per session.
3. Give the evidence in plain terms, what the change would do, and the answers yes / no / not now.

## Reply format

**Confirmation block.** A reply that waits on the user's yes ends with this block. It is the last thing in the reply: no follow-up questions, notes or disclaimers after it, so the question is never buried.

```markdown
---
### ⚠️ ACTION NEEDED: reply to confirm
**Nothing has been uninstalled yet.** Reply `yes` to uninstall Second Opinion, or `no` to keep it. Say whether the ledger, journal and snapshots are kept or deleted (`--purge-data`).
```

**For "show my profile":** a table of field, value, source, date. Then pending proposals and whether learning is on.

**For next steps:** the two groups from `next-steps`, verbatim, under "Set up" and "Try asking", one item per line.

The profile deletion uses the same block:

```markdown
---
### ⚠️ ACTION NEEDED: reply to confirm
**Nothing has been deleted yet.** Reply `yes` to delete your Second Opinion profile, or `no` to keep it.
```

## Rules

- Never accept secrets in chat. This covers `ETRADE_CONSUMER_KEY` / `ETRADE_CONSUMER_SECRET` as well as the SnapTrade keys.
- Do not ask the user to paste a key, and do not read `.env` back to them.
- Never run `--uninstall` before the user confirms in chat.
- Never add `--purge-data` unless the user explicitly asks to delete their data.
- Never write a field the user did not state. Observations become proposals; proposals become fields only on a yes.
- Do not raise a proposal before the user's request is finished.
- Never run `delete --confirm` before the user has confirmed.
- This skill asks about the person, never about a security. It does not score holdings against the profile, does not call the user's approach wrong, and answers "what should my approach be" only by explaining what each approach means and letting the user choose.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
