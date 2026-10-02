---
name: fundamental-research
description: Researches a company from SEC EDGAR — XBRL financials, growth, quality checklist, filing index, 10-K/10-Q reader (risk factors, MD&A, diffs), 13F holdings per manager. Use when the user asks "what does the 10-K say" or "what did Berkshire buy". Not fair value.
---
Researches a company from its SEC filings: the numbers from XBRL, the words from the documents. The scripts produce the tables; the reply quotes the filing sections the user asks about, with dates and links. A second path reports what a 13F manager bought and sold.

## Background

**EDGAR access**

- Set `EDGAR_USER_AGENT` to "app-name contact@email" in the plugin's `.env`. The SEC blocks clients without a proper User-Agent, and the script flags the placeholder default.
- EDGAR's rate limit is 10 requests per second.
- Filing index and company facts are cached under the plugin data directory.

**Form types**

| Form | What it is |
|---|---|
| 10-K | Annual, audited |
| 10-Q | Quarterly |
| 8-K | Material events; Item 2.02 is results, 1.01 agreements, 5.02 officer changes |
| DEF 14A | Proxy: pay, board, votes |
| Form 4 | Insider trades within two business days |
| 13F | Institutional holdings, quarterly, 45-day lag |
| SC 13D/G | 5%+ holders |

**How `edgar.py` builds its tables**

- It resolves the CIK, fetches the filing index and company facts, and runs `fundamentals.py`: the annual table plus the accounting-quality red-flag screens.
- The method is in `fundamentals.py`'s docstring: annual fact selection, concept aliases, ratios, growth, checklist thresholds, red-flag thresholds, quarterly/TTM contract, filing URLs.
- Annual rows are the ~12-month `fp=FY` facts. A 10-K tags its embedded quarterlies `FY` too.
- The quarterly table uses discrete ~90-day quarters only. Q4 is taken from the 10-K. When the 10-K tags no discrete Q4, it is derived as annual minus nine-month year-to-date and marked `derived: true`.
- XBRL concept names vary between companies and years. The script tries several per metric and reports which it used in `concepts_used`. When a metric is null, the company tags it differently: open the 10-K.
- When `concepts_used.revenue` is `InterestAndDividendIncomeOperating`, the `BANK_REVENUE_PROXY` flag says revenue is gross interest income, not a net figure.
- Foreign private issuers (20-F/40-F) tag fewer us-gaap concepts.

**Quality checklist and red-flag screens**

- Quality checks are a screen (revenue growth, cash conversion, dilution, leverage, ROE, margins, coverage, FCF consistency), not a rating. A failed check needs the MD&A explanation before it means anything.
- Red-flag screens are the same kind of thing, one level deeper. Each is a named threshold, not a verdict. Corroborate with the MD&A or footnotes before treating it as more than a screen.

| Flag | Threshold |
|---|---|
| `SBC_HEAVY` | Stock comp >10% of revenue, or above FCF |
| `RECEIVABLES_BUILDING` | Receivables CAGR outpacing revenue CAGR by >10 points/yr |
| `INVENTORY_BUILDING` | Inventory CAGR outpacing revenue CAGR by >10 points/yr |
| `DSO_RISING` | Days-sales-outstanding up >15 days over the table |
| `GOODWILL_HEAVY` | Goodwill >30% of assets |
| `ACCRUALS` | Net income CAGR outpacing operating cash flow CAGR by >15 points/yr |

**Form 4**

- Form 4 counts show activity, not direction.
- `--form4` parses the transaction code, shares, price and date, so the code shows directly whether it is P (open-market purchase), S (sale), or an award/exercise (A, M, F, G), which carry little signal. `acquired` is true only for A/M/P/G.
- It fetches the raw XML behind the index's XSL-rendered path.
- A filing that fails to parse is flagged `"error": "unparseable"` with an 80-character `snippet` of the response rather than failing the run.

**13F**

- 13F-HR is filed by managers with over $100M in US-listed securities within 45 days of quarter end.
- It lists long positions and options only: no shorts, bonds, cash or non-US holdings. Values are whole dollars.
- A CUSIP repeats once per sub-manager, which is why the script sums by CUSIP. Options are kept apart as PUT/CALL rows.
- `holdings.py` diffs the latest 13F-HR by share count against the newest earlier filing with a different report date.
- Curated manager aliases (`--list` prints them): berkshire, bridgewater, renaissance, citadel, millennium, two-sigma, de-shaw, pershing-square, soros, baupost, appaloosa, third-point, elliott, tiger-global, coatue, scion, ark, duquesne, lone-pine, viking.
- Sector or market-level aggregation across every filer needs the SEC's quarterly 13F data sets, which the script does not download.

**Other skills**

- Fair value belongs to the valuation skill. Price action belongs to the trading skill.
- Market-wide "who is buying" belongs to the market-analysis flows script.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fundamental-research/scripts/edgar.py" <symbol> [--years N] [--filings-only] [--quarters N] [--form4 [N]] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fundamental-research/scripts/filing.py" <symbol> [--url URL] [--form 10-K|10-Q] [--item 1A] [--search TERM] [--diff] [--max-chars N] [--context N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fundamental-research/scripts/fundamentals.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fundamental-research/scripts/filing_sections.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fundamental-research/scripts/holdings.py" <manager> [--limit N] | --cik N | --search NAME | --list
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fundamental-research/scripts/render.py" --in holdings.json --out page.html
```

| Script | What it does |
|---|---|
| `edgar.py` | Annual table, growth, quality checklist, red-flag screens, latest quarter, filings summary. |
| `edgar.py --years N` | Fiscal years to keep (default 5). |
| `edgar.py --filings-only` | Skips the large company-facts download. For documents or insider activity only. |
| `edgar.py --quarters N` | Adds a quarterly revenue/net-income table and trailing-twelve-month figures. |
| `edgar.py --form4 [N]` | Fetches and structurally parses that many recent Form 4 filings (default 5, max 10), instead of you opening each one. |
| `filing.py` | Downloads the latest 10-K or 10-Q (or a filing `--url`) and runs `filing_sections.py`. Returns the Item list, one Item's text (`--item`), a passage search (`--search`), or a diff of an Item against the previous filing (`--item` with `--diff`). `--max-chars` (default 20000) caps an Item's text. |
| `fundamentals.py` | Pure math on companyfacts JSON you already have. |
| `filing_sections.py` | Pure reader on a filing document you already have. |
| `holdings.py` | 13F: a manager's latest holdings against the prior quarter. Takes a curated alias, a bare CIK, or `--cik N` for any filer. `--search NAME` only looks up 13F filers. |
| `render.py` | Turns a saved `holdings.py` result into one self-contained HTML page for the Artifact tool. Prints `{"out", "title", "manager", "positions", "changes", "flags"}`. |

`holdings.py` returns `totals`, `new`, `exited`, `increased`, `trimmed` (each capped at `--limit`, default 25, with `truncated` counts), `unchanged`, `top` with weights, `concentration` and `lag_days`.

The `render.py` page holds: stat tiles for reported value and its change, positions with new and exited counts, top-5/top-10 concentration and filing lag; top holdings as weight bars; a concentration donut; sortable New, Exited, Increased and Trimmed tables with share changes and weights; filing links; flags and notes. Light and dark themes; no external scripts.

All scripts print JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Unknown ticker or bad input | `error` |
| 2 from `holdings.py`, unknown manager name | `candidates` from EDGAR's 13F filer search | rerun with `--cik` |
| 2 with code `NO_13F` | The CIK files no 13F-HR | `error` |
| 2 from `render.py` | The input is not a holdings result | `error` |
| 5 | EDGAR HTTP error | `hint` |
| 5 with code `EDGAR_13F_TABLE` | The filing had no parseable information table | `error` |
| 6 | Python dependencies missing | the error, and say the setup skill repairs it |

## Steps

Pick the case that matches the request.

**The user asks about a company**

1. Run `edgar.py <symbol>` once. Use `--filings-only` when the user only wants documents or insider activity; add `--form4` there for a structured parse instead of opening each filing.
2. If the user asks about strategy, risks, guidance, a segment, or an event, read the filing with `filing.py`:

   | The user asks about | Flags |
   |---|---|
   | The business | `--item 1` |
   | Risk factors | `--item 1A` |
   | MD&A, annual | `--item 7` |
   | MD&A, a quarter | `--form 10-Q --item 2` |
   | A topic | `--search TERM` |
   | What changed since last year | `--item 1A --diff` |

3. For 8-Ks, use the WebFetch tool on the URL from `filings`.
4. Run the red-flag sweep: `filing.py --search` against the latest 10-K for "going concern", "material weakness", "restat", and "internal control".
5. Attribute any hit to its Item (1A Risk Factors, 7 MD&A, 9A Controls and Procedures) before quoting it.
6. Reply with the company format below.
7. If the user then wants fair value or price action, finish the research first, then hand off to the valuation or trading skill.

**The user wants a red-team pass on a held or planned position**

1. Follow `references/due-diligence.md`.

**The user asks what a manager bought or sold**

This case covers "what did X buy or sell", "X's biggest positions", "is X still in Y".

1. Run `holdings.py <manager>` once. Write the result to `DIR/holdings.json`. DIR is the session scratchpad.
2. If it exits 2 with `candidates`, pick the CIK and rerun with `--cik`.
3. Run `render.py --in DIR/holdings.json --out DIR/holdings.html`.
4. Publish the HTML with the Artifact tool: icon table, description "MANAGER 13F holdings, quarter ended DATE". Republish the same file path on later runs for the same manager so the link stays stable.
5. Reply with the 13F published-page format below.
6. If the Artifact tool is not available in the session, skip steps 3 to 5 and reply with the 13F markdown format instead.

## Reply format

Every number comes from the script, every quote from a filing you read.

### Company

Render in this order.

**SYMBOL — company** (CIK `cik`, `sic`, fiscal year end `fiscal_year_end`)

1. **Annual table** — from `annual`, oldest to newest: FY · Revenue · Growth · Gross margin · Operating margin · Net income · Net margin · Free cash flow · FCF/NI · EPS (diluted) · Diluted shares · Debt/equity · ROE.
   - Then one line from `growth`: revenue CAGR, net income CAGR, FCF CAGR, EPS CAGR, share-count CAGR over `years` years.
   - Then `latest_quarter` on one line when present.
   - With `--quarters`: the `quarterly` table plus `ttm` revenue/net income and `revenue_ttm_yoy`.
2. **Quality checklist** — `quality.score` of `quality.out_of`. List each check with pass/fail and its value.
3. **Filings** — from `filings`: latest 10-K, 10-Q and proxy with dates and links; recent 8-Ks with items; `insider_filings_90d` Form 4 filings in the last 90 days with links to the most recent. With `--form4`, show the structured `form4.filings` transactions directly instead.
4. **From the filings** — only when the user asked about strategy, risks, or a specific matter. Quote or closely paraphrase the relevant passage from the Item returned by `filing.py` (or the 8-K), with the filing date and link.
   - For a diff, list `added_sentences` and `removed_sentences` verbatim under "New this year" and "Dropped", with `similarity` and `word_delta`.
   - Say when `truncated` is true.
5. **Flags** — one bullet per `flags[].message`, or "None".
   - Label the SBC/receivables/DSO/inventory/goodwill/accruals flags as named-threshold screens, not judgments, and state the threshold that fired.
   - When `BANK_REVENUE_PROXY` is present, say the revenue column is gross interest and dividend income.
6. **Reading** — two or three sentences, one favourable and one unfavourable, using only the numbers and passages above. Then: "XBRL-derived figures can differ from the company's own adjusted metrics; valuation belongs to the valuation skill."

Money in the reported currency with thousands separators (millions when large). Ratios as percentages to 1 decimal place. Share counts in millions.

### 13F, page published (the default)

1. The artifact link on its own line.
2. One line: `manager.name` · quarter ended `current.report_date`, filed `current.filing_date` · `totals.value` in `totals.positions` positions · `totals.value_change_pct` vs the prior quarter · counts of new, exited, increased, trimmed.
3. Two to four sentences naming the largest new, exited, increased and trimmed positions by issuer with their share change.
4. One sentence on concentration.
5. The `notes` caveats in one sentence: long US-listed positions only, classification by shares, confidential positions surface later.

The page carries the tables; do not repeat them.

### 13F, markdown (only when the Artifact tool is unavailable)

In this order:

1. **manager.name** (CIK) — `current.report_date` filed `current.filing_date` (`lag_days` days), versus `previous.report_date`, with both filing URLs.
2. `totals` on one line: reported value, change versus the prior quarter, position count.
3. Four short tables — New, Exited, Increased, Trimmed — each row issuer · shares · change in shares (%) · value · weight, largest first, noting `truncated` counts.
4. Top holdings from `top` with weights, and the `concentration` line.
5. The `notes` in one sentence each:
   - long US-listed positions only, so value is not the fund's assets
   - classification is by shares; value includes price moves
   - confidential positions surface later in amendments this diff ignores

## Rules

- Run `edgar.py` once per answer. Never rerun it within one answer.
- Run at most three `filing.py` calls per answer.
- Numbers come only from the scripts. Passages come only from documents you opened.
- Never summarize a section you did not read.
- The red-flag `flags` are named-threshold screens for the accounting-quality section, not judgments.
- Never infer a rationale for a trade the filing does not state.
- Publish the 13F page or use the 13F markdown format, never both.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
