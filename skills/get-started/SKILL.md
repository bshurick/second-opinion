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

Account roles (the first run's Accounts question): every connected account with `proposed_role`, `saved_role`, `role` and `margin`. `--accept` saves the proposal for each account with no saved role and never overwrites one.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/roles.py" [--accept] [--partial]
```

A report page for a session with no Artifact tool. Every skill that renders a page uses it: it wraps the rendered file into a whole HTML document, saves it under `pages/` in the data directory and opens it in the browser. It prints `{"path", "url", "opened", "title"}`; `opened` is false when no browser could start, and the file is saved either way.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/local_page.py" --in PAGE.html [--name NAME] [--no-open]
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

Three checks, then every question in one form, then a short guide. Each part is checked first and skipped when it is already done, so the flow can stop anywhere and pick up there next time. Say at the start which parts are already done.

| Part | Done when | What the person does | Skippable |
|---|---|---|---|
| 1. Check | `profile.py show` exits 0 or 4 | Nothing | no |
| 2. Keys | connect's `status.py` exits 0 | Runs `configure.py keys` in their own terminal | yes, for research-only use |
| 3. Connect | `status.py` lists accounts | Signs in through the connect skill | yes |
| 4. The form | every question in "The questions" has a saved answer | Answers all of them in one go | yes, question by question |
| 5. The guide | shown once the form is saved | Nothing | no |

1. **Check.** Run `profile.py show`. Exit 6 or a path error means the install is broken: go to "Reinstall dependencies" and stop.
2. **Keys.** If `status.py` exits 4 for missing credentials, follow "A key is needed". Keys never enter the chat. Wait for the person to say the keys are saved, then check again.
3. **Connect.** Hand off to the connect skill to link a brokerage, then come back here.
4. **Read what is already saved,** before asking anything. Run `settings.py show`, and when accounts are connected, `roles.py` and the portfolio-plan skill's `plan.py status`. A question whose answer is saved is not asked again.
5. **Ask every open question in one form,** following "Asking the form" and "The questions" below. Never ask them one message at a time.
6. **Save the answers** with the commands in "The questions". Run `profile.py complete` when at least one About-you answer was saved, and `profile.py skip` when the person skipped both.
7. **Confirm in one table** what was saved: Setting · Value · What it does. Name each skipped question and the default in force for it.
8. **Show the guide.** Run `next-steps` and reply with "The guide" in Reply format.
9. If the person came in with another request (the session context said no profile exists), complete it now.

**Asking the form**

1. If the session has a question tool that takes several questions at once (AskUserQuestion in Claude Code), use it. Each question is one tab, with its choices and one line under each choice saying what the plugin does with it.
   - The tool takes at most four questions a call. Send the first four, then the rest in a second call straight after, with no chat message between the two.
   - When a question has more choices than the tool takes, offer the commonest and name the others in the question text, for the person to type.
2. If there is no such tool, send every question in one message as a numbered list with lettered choices. Ask for all the answers in one reply, such as "1b 2a 3c".
3. State each question as a choice among what the plugin offers. Never ask about the person's strategy in the abstract and infer the setting from the answer.
4. Never mark a choice as the better one. Say which choice is the default.
5. An unanswered question stays unset. Do not ask it again in this conversation.

**The questions**

Ask in this order. Leave out the plan questions (5 to 8) when no account is connected.

| # | Tab | Question | Choices, and what the plugin does with each | Saved with |
|---|---|---|---|---|
| 1 | Accounts | "Here is each account and the role proposed for it. Keep these roles?" Put the Account · Type · Proposed role lines from `roles.py` in the question. | **Keep as proposed.** / **Change one**: the person names the account and the role. A role decides where picks may sit: trading is taxable and holds picks, and its funds can be sold to pay for picks; retirement is tax-advantaged and holds no picks; savings is taxable and holds no picks. | `roles.py --accept`, after `settings.py set accounts.<id>.role ROLE` for each change |
| 2 | Depth | "How thorough should valuations, stock picks and reviews be?" | **Standard** (the default): an answer in seconds from the scripts and little usage; a deep run happens only when you ask for one. / **Deep**: every valuation, pick and review sends 5 to 40 research subagents through filings and news; a run takes minutes and a portfolio review up to an hour, with far more of your Claude usage; it asks first before starting more than 3 deep valuations. | `settings.py set depth standard` or `deep` |
| 3 | Approach | "Which of these describe how you invest? Pick any." | **Value**: what a business is worth. / **Growth**. / **Dividends**. / **Index funds**. / **Charts and momentum**. / **Not sure yet**. The plugin offers the matching analysis first. It never scores a holding against the answer. | `profile.py set approach value,growth,dividend,index,technical,unsure` (the ones chosen) |
| 4 | Horizon | "How long do you usually hold an investment?" | **Years** / **Months** / **Weeks or less** / **It varies**. It sets which time frame the answers lead with. | `profile.py set horizon years`, `months`, `weeks` or `mixed` |
| 5 | Employer stock | "Does your employer pay you in its stock (stock awards, a purchase plan), or do you hold its shares? If so, which ticker, and what happens to new shares?" When `plan.py status` gives `employer_candidate`, name it: "Your account history shows TICKER shares arriving." | **Yes, sold when they arrive**: the plan keeps that stock as its own line outside your picks, and lists each new batch as a sale whose proceeds go to your targets. / **Yes, kept**: the plan keeps that stock as its own line, never lists it for sale on arrival, and flags it above 10% of the portfolio. / **No**: no holding is treated as employer stock, and every single stock counts as one of your picks. | `settings.py set plan.sleeves.EMPLOYER.members TICKER` and `plan.sleeves.EMPLOYER.policy sell_on_arrival` or `hold`; for No, `members none` |
| 6 | Stock picks | "What share of the portfolio do you want in stocks you pick yourself, with the rest in funds?" | **5%** / **10%** / **20%** / another figure: the plan measures your picks against that share and sends new money toward it; it sells nothing to get there unless you ask for a rebalance. / **Not managed**: the plan reports the share and sets no target. | `settings.py set plan.sleeves.PICKS.target 0.1`, or `none` |
| 7 | Cash reserve | "How much cash should plans leave untouched?" | **$0** / **$5,000** / **$10,000** / another amount. A plan never spends this cash when it puts money to work. | `settings.py set plan.cash_reserve AMOUNT` |
| 8 | Short-term gains | "May a plan sell a holding bought less than a year ago at a gain?" | **No, hold them** (the default): a plan leaves those holdings unsold in taxable accounts, so no gain is taxed at the short-term rate, and it can end further from target. / **Yes, allow**: a plan sells whatever reaches the target and shows the estimated tax. | `settings.py set taxes.short_term_gain_policy hold` or `allow` |

- If the person answers question 5 with a yes and no ticker, and there is no `employer_candidate`, ask for the ticker in one line. That is the only follow-up question the form allows.
- Accept anything close in meaning to a choice, map it to the saved value and show that value in the confirming table.
- A skipped plan question stays unset, and plans use the stated default for it (`STANDING_DEFAULT`).
- The other profile fields (`risk_appetite`, `experience`, `goals`, `pre_trade_check`, `trades_actively`, `uses_options`) are never asked. The person can set them in their own words later ("update my profile").

**When a profile already exists** and the person says "get started", offer to revisit the steps, with the current answers shown.

For the install and settings cases below, find the route first (Background table). If neither `install.js` exists, ask the user where their checkout is. Then pick the case that matches the request.

**Install or reconfigure**

1. Say in two sentences what will happen.
   - Plugin install: "The installer saves your keys and optional extras in the plugin's data directory and builds a virtualenv with the three Python dependencies; Claude Code keeps managing the plugin files."
   - Guided install: "The installer copies the chosen skills plus the shared library into `~/.claude/plugins/second-opinion/`, builds a virtualenv with the three Python dependencies, saves your keys and extras in the data directory, links the plugin into `~/.claude/skills/`, and runs a smoke test."
2. Guided install only, if the user has not said which skills they want, ask once, in one question: "The core skills and the trade plan and pre-buy check are installed by default, and two optional extras are off (suggested follow-up questions, and lessons and quizzes); anything to leave out or turn on?" For a plugin install ask only about the extras. Do not ask again.
3. If they ask what exists, show the family list and the extras (with their `label` and `blurb`) from `skills.json`.
4. If a key is needed and none is set, follow "A key is needed" below instead of running the installer yourself.
5. If the user wants to preview the plan before anything is written, run the command with `--dry-run` first.
6. Run the command for the route. For a plugin install, a missing brokerage key is a warning, not an error.
7. Read the JSON object on stdout.
8. Report in plain language: what was installed, removed or configured, whether dependencies were installed, the smoke results, every note and every warning verbatim.
9. If `smoke.status` is `rejected`, point to the connect skill.
10. If `smoke.etrade` is `no_login`, tell the user to say "Connect E*Trade" and paste the code it shows.
11. For a plugin install, say the change applies from the next session or after `/reload-plugins`.
12. After a successful first install, end with: "Now say 'get started with Second Opinion' to connect your accounts, answer the setup questions in one form and see what to try first."

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

1. Before setting it, state what each choice costs. Standard: seconds and little usage per answer, with a deep run on request. Deep: minutes and 5 to 40 research subagents per run (a portfolio review can take up to an hour), a deep valuation or deep pick only, and a question first when a request would start more than `deep.ask_above` (default 3) deep valuations.
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

**The guide** (the end of the first run, and "what can I ask"). These parts in this order, then stop.

1. "Set up": the `setup` items from `next-steps`, one per line. Leave the heading out when the list is empty.
2. "Try asking": the `try_asking` items, one per line, so the person can say each word for word.
3. "Common requests": this table, with only the rows whose skill is in `installed_skills`.

   | To | Say | Or type |
   |---|---|---|
   | See every account today | "How is my portfolio?" | `/second-opinion:portfolio-analysis` |
   | Catch up since last time | "Check in" | |
   | Read the market | "How is the market today?" | `/second-opinion:market-analysis` |
   | Value a stock | "What is COST worth?" | `/second-opinion:valuation` |
   | Find stocks | "Find me stocks" | `/second-opinion:stock-screener` |
   | Compare against your targets | "Am I off target?" | `/second-opinion:portfolio-plan` |
   | Stress-test the holdings | "What if 2008 repeats?" | `/second-opinion:risk-analysis` |
   | Check retirement | "Am I on track to retire?" | `/second-opinion:retirement` |
   | Change anything set here | "Show my settings" | `/second-opinion:get-started` |

4. Three closing lines:
   - "Ask in plain words. A skill name is never needed, and typing `/second-opinion` lists every command."
   - "Say 'deep' with a request for the researched version, such as 'do a deep dive on COST'. It takes minutes and more usage."
   - "Orders are previewed first, and nothing is sent until you say yes."

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

**Writing** (every reply, page and saved file):

- Spell out every acronym and shorthand at its first use, as in "comparable-store sales (comps)". A label is a first use: a scenario name, headline or column header uses the plain words or defines its shorthand. Tickers, $ and % are exempt. Spelling out a term is not explaining a concept.
- Cut adjectives and adverbs that carry no fact. A word like "sharp" or "severe" stays only beside the number that shows it.
- Use the active voice: name who did what. "Management cut prices", not "prices were cut".
- Keep sentences short, one idea each, under about 25 words.
- Give every bulleted or numbered list a heading or lead-in that says what it lists. Otherwise write the items as prose, or as a table with column or row headers when they share fields.
- Lead with the answer. The first sentence gives the result or answers the question asked; the reasons and the detail follow. Each paragraph opens with its point.
- Put a figure, a date or a source where a vague word would go. "Often", "soon", "many" and "significant" say nothing until a number stands beside them, as in "in 7 of the last 10 years".
- State a doubt once, where it applies, and say what causes it. Write the rest plainly. Give each side the weight its evidence has, and never pad the weaker side to make the two look even.
- Cut every sentence the reader would not miss: an opening that announces what the reply will do, a closing that repeats it, a restatement of the sentence before, and a claim that something matters with no reason given.
- Say what is, in plain words: "the data is inconclusive", not "the data does not conclusively show"; "use", not "utilize". Drop build-ups such as "not just X but Y", and keep a series of items in one sentence.
