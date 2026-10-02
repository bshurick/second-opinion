---
name: watchlist
description: Keeps a watchlist with alert rules (price above or below, daily move, drawdown from the 52-week high) and checks them on request or by cron. Use when the user says "watch X", "alert me if X drops below", or asks what on the watchlist moved.
---
Maintains the user's watchlist and checks their alert rules on demand. The rules are the user's own; the check is mechanical; a triggered alert is a fact about a price level, not a signal.

## Background

- **Storage.** The watchlist is `watchlist.json` in the plugin data directory. Each `check` also saves its result to `watchlist-last-check.json` there.
- **When alerts are evaluated.** Only when `check` runs, started by the user or by their own cron entry. Nothing monitors in the background and nothing sends notifications.
- **What `check` fetches.** One batched Yahoo quote, plus one batched year of closes and volumes for 52-week highs, moving averages and volume averages. `--no-history` skips the second fetch.
- **Rates are decimals.** `--day-move 0.05` means 5%.
- **Alert states.** Every triggered rule carries a `state`:

  | State | Meaning |
  |---|---|
  | `new` | Not reported yet. Report it. |
  | `still` | Already reported today. |
  | `acknowledged` | The user acknowledged it. |
  | `snoozed` | Inside a snooze window. |

  `summary.newly_triggered_symbols` counts the `new` ones.
- **Session start.** Once a watchlist exists, the plugin's session-start hook prints the last saved check when a session opens.
- **Other skills.** Analysis of a symbol belongs to trading, valuation or fundamental-research. Orders belong to portfolio-analysis. Holdings belong to portfolio-snapshot.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" add SYMBOL [--note TEXT] [--above P] [--below P] [--day-move R] [--from-added R] [--drawdown R] [--near-52w-high R] [--ma-cross 1|-1] [--volume-spike M] [--added-price P]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" remove SYMBOL
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" list
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" check [--as-of YYYY-MM-DD] [--no-history] [--events]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" summary
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" install-cron [--hour 9] [--minute 37]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" ack SYMBOL [RULE_TYPE]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/watchlist.py" snooze SYMBOL DAYS
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/watchlist/scripts/alerts.py" < input.json
```

| Command | What it does |
|---|---|
| `add` | Adds a symbol with rules. Running it again with a rule replaces that rule. |
| `remove` | Drops the symbol. |
| `list` | Prints the watchlist. |
| `check` | Fetches quotes, evaluates every rule, saves the result. `--events` adds `events`: next earnings and ex-dividend date per symbol, with `earnings_in_5_days`; symbols with neither date are left out. |
| `summary` | Prints the last saved check as a few lines of plain text (not JSON), or one line saying no check has run. |
| `install-cron` | Prints the crontab line for a weekday-morning `check --events`. It installs nothing. |
| `ack` | Marks an alert as seen. All rules for the symbol when no `RULE_TYPE` is given. |
| `snooze` | Silences a symbol's alerts for `DAYS` days. |
| `alerts.py` | Pure evaluation of a watchlist and quotes you already have. Rule semantics are in its docstring. |

All commands print JSON except `summary`.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad flags, unknown symbol, or empty watchlist | `error` |
| 5 | Corrupt watchlist file | `hint` |
| 6 | Python dependencies missing | the error, and say the setup skill repairs it |

## Steps

Pick the case that matches the request.

**The user wants to watch a symbol**

1. Translate each rule the user states into a flag:

   | The user says | Flag |
   |---|---|
   | "drops below 150" | `--below 150` |
   | "rises above 200" | `--above 200` |
   | "falls 10% from here" | `--from-added -0.10` |
   | "moves more than 5% in a day" | `--day-move 0.05` |
   | "is 20% off its high" | `--drawdown 0.2` |
   | "gets within 5% of its high" | `--near-52w-high 0.05` |
   | "golden cross" (50-day average crosses above the 200-day) | `--ma-cross 1` |
   | "death cross" | `--ma-cross -1` |
   | "volume doubles its 20-day average" | `--volume-spike 2.0` |

2. Run `add SYMBOL` with those flags. Add `--note` with the user's reason in their own words.
3. Reply with the add/remove/list format below.

**The user asks what moved, or whether anything triggered**

1. Run `check` once. Add `--events` when they ask about earnings or dividends.
2. Reply with the check format below.
3. If they then want analysis or an order for a triggered symbol, finish this reply first, then hand off to the skill named in Background.

**The user asks what the last check said**

1. Run `summary`.
2. Show its text as is.

**The user wants a check every morning without opening a session**

1. Run `install-cron` with their hour and minute.
2. Show `crontab_line` verbatim, with the `instructions`.
3. Say the user pastes the line into their crontab themselves, and that the next session will open with that check's summary.

**The user has seen an alert, or wants quiet**

- Seen: run `ack SYMBOL [RULE_TYPE]`.
- Quiet: run `snooze SYMBOL DAYS`.

**A triggered rule's note begins with `journal j-...`**

The trade-journal skill created that rule for a planned add. Say so and point to that journal entry. Do not present it as a fresh alert level.

## Reply format

**For `add`, `remove` and `list`:** one line per symbol.

Symbol · Note · Added (price) · Rules (type and value)

**For `check`:** these sections, in this order.

1. **Triggered** — one bullet per `triggered[].message` whose `state` is `new`. Write "No alerts triggered." when there are none. Summarize `still`, `acknowledged` and `snoozed` rules in one line ("seen today: …", "snoozed until …").
2. **Watchlist** — a table from `watchlist`: Symbol · Price · Day · Since added · From 52w high · Rules waiting · Note. Write each `untriggered` rule as "type value (now current)".
3. **Events** — only when `--events` ran. One line per `events[]`: Symbol · Next earnings (mark it when `earnings_in_5_days` is true) · Next ex-dividend. Write "None upcoming." when empty.
4. **Flags** — one bullet per `flags[].message`, or "None".

Percentages to 1 decimal place with a sign. Prices to 2 decimal places.

## Rules

- Every number comes from the script. Do not recompute or add figures.
- A triggered alert is a fact about a price level the user chose earlier. Describe it and stop.
- Never edit the crontab yourself. The user pastes the line in.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
