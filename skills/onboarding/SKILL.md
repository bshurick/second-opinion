---
name: onboarding
description: Runs the Second Opinion first-run interview about goals and approach, then lists next steps (connect a brokerage, first questions to ask). Use when the user says "get started with Second Opinion" or "get started", or on a first finance request with no profile.
---
Runs the plugin's front door: a six-question interview about how the user invests, stored as a profile with provenance, followed by concrete next steps. The profile chooses which analysis runs first and which of the user's own standards a trade is checked against. It never judges a security against the person.

## Background

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
  | `account_roles` | `id=trading,id=retirement,id=savings`, ids from the connect skill's status |
  | `trades_actively` | yes/no |
  | `uses_options` | yes/no |

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" set <field> <value...>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" unset <field>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" show
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" skip
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" complete
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" learning on|off
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" next-steps [--offline]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" context
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/profile.py" delete --confirm
```

| Command | What it does |
|---|---|
| `set` | Saves a declared answer. Lists are comma-separated. |
| `unset` | Removes a field. |
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
| 6 | Python dependencies missing | hand off to the setup skill |

## Steps

Start with the health check, then follow the case it points to.

**Health check**

1. Run `show`.
2. If it exits 6 or reports a path error, the plugin is not installed properly. Hand off to the setup skill ("set up the finance plugin") and stop.
3. If it exits 4, no profile exists yet. Go to "First run".
4. If it exits 0 and the user asked to get started or set up, offer to revisit the answers: run the interview with the current values shown.
5. If it exits 0 and the user asked something else, go to "Edits and questions later".

**First run**

1. Frame it in one sentence: "Six short questions about how you invest, so the plugin knows which analysis to lead with. Say 'skip for now' to answer later."
2. If the user was in the middle of another request (the session context said no profile exists), say the request will be completed right after.
3. If they say skip, run `skip`, complete their original request, and never raise the interview again unless asked.
4. Otherwise run the interview.

**Interview**

Ask one question per message. Wait for the answer. Run `set` for that field before asking the next. Every question is skippable: "skip" moves on without writing. Offer the choices below and accept anything close in meaning; map it to the vocabulary and say the value you saved.

1. "What is the money for?" (retirement, a house, income, growing wealth, learning; several allowed) → `goals`
2. "How long do you usually hold an investment?" (years / months / weeks or less / it varies) → `horizon` years, months, weeks, mixed
3. "How do you decide what to buy?" (what the business is worth / growth prospects / dividends / index funds / charts and momentum / not sure yet; several allowed) → `approach` value, growth, dividend, index, technical, unsure
4. "If a holding dropped 30%, what would you most likely do?" (sell / hold / buy more / it depends) → `risk_appetite` low for sell, moderate for hold or depends, high for buy more. Say the mapping.
5. "How would you describe your investing experience?" (beginner / intermediate / experienced) → `experience`. See the level lookup below.
6. "Before you buy something, what do you want to have looked at first?" (a valuation / the fundamentals / the chart / nothing extra) → `pre_trade_check`. Say that it is recorded in the profile and shown in the session context line, so the check they named can be run before a buy when they ask for one; nothing blocks an order on it.
7. Only when a brokerage is connected (the connect skill's status lists accounts): show each account by name and ask its role (trading / retirement / savings / leave unset) → `account_roles`.
8. Run `complete`.
9. Run `next-steps` and render its two groups verbatim as "Set up" and "Try asking", each item on its own line so the user can say it word for word.
10. If the user came in with a request, complete that request now.

Level lookup for question 5: if a profile file already exists and the financial-education skill is installed, run the command below. If its `level` is set, propose the matching answer and let the user confirm. Skip the lookup when no answer has been saved yet; the gate blocks it until a profile exists.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/financial-education/scripts/progress.py" list
```

**Edits and questions later**

| The user says | Do |
|---|---|
| "Show my profile" | Run `show` and reply with the format below. |
| "Update my profile ..." | Run `set`. |
| "Forget ..." | Run `unset`. |
| "What should I try next" | Run `next-steps`. |
| "Stop learning about me" | Run `learning off`. Declared answers stay. |
| "Delete my profile" | Ask once in plain words, then run `delete --confirm`. |

**`show` lists pending proposals**

1. Finish the user's current request first.
2. Raise at most one proposal per session.
3. Give the evidence in plain terms, what the change would do, and the answers yes / no / not now.

## Reply format

**For "show my profile":** a table of field, value, source, date. Then pending proposals and whether learning is on.

**For next steps:** the two groups from `next-steps`, verbatim, under "Set up" and "Try asking", one item per line.

## Rules

- Never write a field the user did not state. Observations become proposals; proposals become fields only on a yes.
- Do not raise a proposal before the user's request is finished.
- Never run `delete --confirm` before the user has confirmed.
- This skill asks about the person, never about a security. It does not score holdings against the profile, does not call the user's approach wrong, and answers "what should my approach be" only by explaining what each approach means and letting the user choose.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
