---
name: valuation
description: Estimates the fair value of a security with DCF, comparable multiples, dividend discount and Graham/Buffett intrinsic value (Graham number, owner earnings, margin of safety). Use when asked what something is worth, for a fair or target price, or a value check.
---
Estimates what a security is worth from its fundamentals: a discounted-cash-flow range, cross-checked against comparable multiples, dividend discounting and Graham/Buffett arithmetic, with every assumption stated. It works from public financial data and market prices and has no access to brokerage accounts.

## Background

### Where the numbers come from

- `fundamentals.py`, `inputs.py` and `peers.py` read Yahoo. `intrinsic-inputs.py` reads SEC EDGAR, and FRED's keyless CSV endpoint for two yields.
- `dcf.py`, `ddm.py`, `comps.py` and `intrinsic.py` are pure math on a JSON input. Each script's docstring is its input and output contract.
- `intrinsic-inputs.py` needs the fundamental-research skill installed and `EDGAR_USER_AGENT` set. Exit 4 `SKILL_MISSING` says so when it is not.
- Web search is only for what the scripts do not return: analyst estimates and qualitative context.

### What `inputs.py` builds

`inputs.py <symbol>` emits a filled `dcf.py` input, three scenario inputs and a filled `ddm.py` input, with nulls where the data cannot fill a field. Every derived value is echoed with its source in `assumptions`.

| Field | How it is built |
|---|---|
| `fcf0` | Free cash flow **to the firm**: the annual statement's free cash flow plus after-tax interest, so it matches the WACC and the net-debt subtraction. When the latest year is above the average margin over the statements, the average is used and the source says so. |
| `wacc` | A weighted cost of capital: CAPM cost of equity on the 10-year Treasury (^TNX) with beta pulled a third of the way toward 1, cost of debt from interest expense over total debt, market-value weights, debt after tax, and never below the Treasury plus 2.5 points. |
| `growth_rate` | The lower of the revenue and free-cash-flow CAGRs, kept within 0–15%. |
| `dcf_scenarios` | `bear`, `base` and `bull` inputs that differ in the business assumption, not the discount rate. Each fades growth in a straight line to terminal growth, from below, at, and above the hint. |
| `business_type` | From Yahoo's sector. |
| `flags` | For a bank or insurer, a REIT, or a regulated utility, a `DCF_NOT_MEANINGFUL_FOR_…` flag says the cash-flow DCF says little and names what to use. `NEGATIVE_FCF` says the same for any company burning cash. |
| `ddm_input` | Discounts at the cost of equity. `dividend_cagr` runs over complete calendar years. |

- The three `dcf_scenarios` results are the range to present. The sensitivity grid inside each result is the discount-rate range.

### What `dcf.py` and `ddm.py` add

- **Reverse DCF.** With `current_share_price` in the `dcf.py` input, the output's `implied` block gives the stage-1 growth and the terminal growth that each reproduce the price. A value is null when no admissible rate does.
- **Per-year growth.** `stage1_growth` takes per-year rates for an explicit high-growth phase tapering to stable growth.
- **`ddm.py`** runs Gordon, two-stage, and H-model dividend discounting from one JSON input.

### What `peers.py` and `comps.py` do

- `peers.py` emits only the multiples that fit the target's kind of business, and echoes `business_type` and `metrics_used`:

  | Kind of business | Multiples |
  |---|---|
  | Bank or insurer | P/E and P/B |
  | REIT | Price to funds from operations and EV/EBITDA |
  | Utility | P/E, P/B and EV/EBITDA |
  | Everything else | All six |

- `comps.py` leaves implied values that are not positive out of its summary and names them in `excluded_from_summary`.

### What `intrinsic-inputs.py` builds

- Ten fiscal years of the fundamentals annual table from SEC EDGAR, the current price, and the Moody's Aaa and 10-year Treasury yields from FRED (AAA and DGS10).
- A `business_type` set from the SEC SIC code in the EDGAR submissions index:

  | SIC | `business_type` |
  |---|---|
  | Banks, brokers and insurers | `financial` |
  | 6798 | `reit` |
  | 6798 with no revenue line, or interest more than half its revenue (a mortgage REIT) | `financial` |
  | 4910-4941 | `utility` |
  | Anything else | `industrial` |

- `--business-type` overrides the SIC reading. The `sic` and the reason are echoed in `assumptions`.
- The output's `intrinsic_input` is what goes into `intrinsic.py`.

### What `intrinsic.py` computes

- The Graham number, Graham's growth formula, net current asset value and the net-net test, and the seven-point defensive-investor checklist.
- Owner earnings with an explicit maintenance-capex estimate, and seven quantifiable Buffett tenets.
- A `normalized` block: ten-year average owner earnings and EPS, a Graham number on the ten-year EPS, and a mid-cycle `dcf_input_mid_cycle`.
- A margin-of-safety row per estimate.
- `intrinsic.py` does not discount. `dcf.py` on `buffett.dcf_input` gives the ten-year owner-earnings present value, and `dcf.py` on `normalized.dcf_input_mid_cycle` gives the mid-cycle case.
- **Averaging.** Owner earnings are averaged per share, each year on its own share count, so a company that issued shares to grow is not marked down for having been smaller.
- **`CYCLE_PEAK`** fires when the latest owner earnings run 1.5x the average.
- **`OWNER_EARNINGS_MOSTLY_NEGATIVE`** fires when owner earnings were not positive in half or more of the years. The mid-cycle input is then withheld.
- **Default growth rate.** The smaller of the EPS CAGR and revenue growth over the table, clipped to 0-8%. Revenue growth is the lower of the total and the per-share rate, so neither share issuance nor buybacks are credited.
- `inputs.growth_rate.source` spells out the arithmetic. `inputs.growth_alternatives` gives both CAGRs and the growth-formula value at 5%, 10% and 15%, so the sensitivity is visible without a rerun.
- **Overrides.** Pass `growth_rate`, `maintenance_capex`, `business_type`, or `discount_rate_floor` in the input to rerun with other values.

### How `intrinsic.py` treats each business type

| `business_type` | What changes | The yardstick it gives |
|---|---|---|
| `financial` | The current ratio, NCAV and net-net are null (`NOT_APPLICABLE`). The financial-condition test is equity / total assets >= 8%. The little-debt tenet is skipped. The DCF handoff is flagged `DCF_NOT_MEANINGFUL_FOR_FINANCIALS` with net debt zeroed. | `buffett.book_value_tests`: P/B against latest and ten-year ROE. |
| `reit` | Maintenance capex defaults to 1% of revenue. Gains on property sales are taken out of owner earnings. Growth runs on the AFFO proxy per share. The Graham number and growth formula carry `GAAP_EPS_UNDERSTATES_REIT` and are left out of the margin of safety. | `buffett.reit_tests`: the AFFO proxy per share with its growth, price / AFFO proxy, dividend yield and growth, payout, net debt / EBITDA and a `ddm_input`. |
| `utility` | Maintenance capex is depreciation (spending above it grows the rate base). The DCF handoff is flagged `DCF_NOT_MEANINGFUL_FOR_UTILITIES`. | `buffett.utility_tests`: P/E, P/B, ROE latest and ten-year, dividend yield, payout, dividend growth and a `ddm_input` to run through `ddm.py`. |

- The REIT AFFO proxy is net income plus all depreciation less a 1% reserve. A company's own reported AFFO will differ.
- Other one-off gains (a stake sold, a revaluation) stay in the proxy, so read `CYCLE_PEAK` on a REIT as "check for a gain".

### What `render.py` takes and shows

- It turns the collected results into one self-contained HTML page for the Artifact tool (light and dark themes; no external scripts).
- There is no single combined script, so its input is an object you assemble:

  | Key | Value |
  |---|---|
  | `symbol` | The ticker |
  | `price` | The current share price |
  | `dcf` | The `dcf.py` result |
  | `dcf_owner_earnings` | The `dcf.py` result on `buffett.dcf_input` |
  | `dcf_mid_cycle` | The `dcf.py` result on `normalized.dcf_input_mid_cycle` |
  | `intrinsic` | The `intrinsic.py` result |
  | `comps` | The `comps.py` result |
  | `ddm` | The `ddm.py` result |

- Every key is optional, with at least one of `dcf`, `intrinsic`, `comps`, `ddm` present. A bare `dcf.py` or `intrinsic.py` result is wrapped.
- The page shows stat tiles: price, DCF fair value, Graham number, growth-formula value, mid-cycle and owner-earnings DCF, comps median, DDM value.
- It shows each method's margin of safety as bars, and the WACC × terminal-growth grid as a heatmap coloured around the current price with the base case outlined.
- It shows the Graham checklist and Buffett tenets as pass/fail lists, owner earnings by year, the normalized block, the comps and DDM tables and the flags.
- It prints `{"out", "title", "symbol", "methods", "flags"}`.
- The only figure it derives is the discount to price for the DCF, comps and DDM values (1 − price / value), stated in its note.

### Reference files

Read these with the Read tool and ground the answer in what they say. Do not answer these topics from memory, even if you recognise the underlying papers.

- Read `references/dcf-methods.md` before answering a question that involves any of these:
  - cash-flow measures (FCFF, FCFE, NOPAT), or which discount rate matches which cash flow
  - terminal-value mechanics, or why small WACC/g changes swing value
  - EVA / economic profit / MVA, or reconciling EVA with FCF
  - dividend discount models (Gordon, multi-stage, stochastic, Markov)
  - startup / pre-profit valuation and the systematic DCF biases against high-growth firms
  - deriving WACC inputs (beta, equity risk premium, after-tax cost of debt) from first principles
  - comparable-multiples methodology (which multiples, peer selection, transaction comps) or Adjusted Present Value (APV)
- Read `references/value-investing.md` before answering anything about Benjamin Graham, Warren Buffett, value investing, the margin of safety, the Graham number, net-nets or net current asset value, owner earnings, or a "value screen".
- `references/value-investing.md` maps every figure `intrinsic.py` emits to its source (Graham's chapters 11, 14, 15 and 20; the 1977, 1983, 1986 and 1992 Berkshire letters; Greenwald).

## Scripts

Run with the Bash tool. All print JSON on stdout.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/fundamentals.py" <symbol> [--quarterly]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/inputs.py" <symbol>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/peers.py" <symbol> --peers A,B,C
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/dcf.py"   <<< '<input json>'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/ddm.py"   <<< '<input json>'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/comps.py" <<< '<input json>'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/intrinsic-inputs.py" <symbol> [--years 10] [--business-type industrial|financial|reit|utility]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/intrinsic.py" <<< '<input json>'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/render.py" --in valuation.json --out page.html
```

| Script | What it does |
|---|---|
| `fundamentals.py` | Company profile plus financial statements from Yahoo. `--quarterly` adds quarterly statements. |
| `inputs.py` | Filled `dcf.py` and `ddm.py` inputs, with `dcf_scenarios`, `assumptions`, `business_type` and `flags`. |
| `peers.py` | The `comps.py` input: target and peer multiples from Yahoo. |
| `dcf.py` | Two-stage DCF with a WACC × terminal-growth sensitivity grid and, given `current_share_price`, the `implied` block. |
| `ddm.py` | Gordon, two-stage and H-model dividend discounting. |
| `comps.py` | Peer-median multiples and the value each implies for the target. |
| `intrinsic-inputs.py` | Filled `intrinsic.py` input: EDGAR annual table, price, FRED AAA and DGS10 yields, business type from the SIC code. |
| `intrinsic.py` | Graham and Buffett figures, checklists, the `normalized` block and margin-of-safety rows. |
| `render.py` | The interactive page from the collected results. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input. For `render.py`, no script result is present. | `error` |
| 4 | `intrinsic-inputs.py` only. `SKILL_MISSING`: the fundamental-research skill is not installed. `CONFIG_MISSING`: EDGAR is not configured. | `error` |
| 5 | A data source (Yahoo, EDGAR) returned an error | `error` |
| 6 | Python dependencies missing | `error`, and say the setup skill repairs it |

## Steps

1. Identify the security. Run `fundamentals.py <symbol>` for current market data (price, market cap, shares outstanding) and the statements: at minimum 3-5 years of income statements, balance sheets and cash flow statements.
2. Run `inputs.py <symbol>`. Read `business_type` and `flags`.
3. Pick the methods from this table. More than one row can apply.

   | Kind of company | What to do |
   |---|---|
   | Banks, insurers, brokers and mortgage REITs | No cash-flow DCF. Lead with `intrinsic.py`'s `book_value_tests` (price to book against return on equity), then P/E and P/B against peers. |
   | Property REITs | No cash-flow DCF and no Graham number against the price. Lead with `reit_tests` (price to the AFFO proxy, its per-share growth, dividend yield, payout, net debt / EBITDA), run `ddm.py` on its `ddm_input`, and cross-check with `peers.py` (price to funds from operations). |
   | Regulated utilities | No cash-flow DCF. Lead with `utility_tests`, run `ddm.py` on its `ddm_input`, and cross-check P/E and P/B against other utilities. |
   | Mature, dividend-paying companies | Supplement the DCF with `ddm.py`. |
   | High-growth companies | Use a multi-stage DCF with an explicit high-growth phase tapering to stable growth (`stage1_growth` per-year rates, or the `ddm.py` H-model for dividends). |
   | Established, profitable companies, or any question framed in Graham or Buffett terms | Run `intrinsic.py` alongside the DCF for the Graham number, the growth formula, net current asset value, owner earnings, and both checklists. Hand its `buffett.dcf_input` to `dcf.py` for the owner-earnings present value. |
   | Companies with changing capital structure | Consider Adjusted Present Value (APV) instead of the standard WACC-based DCF. |
   | Early-stage / pre-profit companies | Flag the systematic DCF biases against high-growth, long-payback firms identified in the literature. Widen the valuation range accordingly. |

4. If a `DCF_NOT_MEANINGFUL_FOR_…` flag or `NEGATIVE_FCF` fired, do not present the DCF as an estimate of value. Skip to step 9.
5. Review the historical record in the statements: revenue growth, operating margins, NOPAT, capex, D&A, changes in working capital, and free cash flow (FCFF).
6. Challenge each entry in `assumptions` against that record instead of accepting it, and state the ones you keep.
   - `wacc`: CAPM for the cost of equity and the company's effective borrowing cost for the cost of debt.
   - Growth: a 5-10 year scenario period based on historical trends, adjusted for known catalysts or headwinds.
   - Terminal growth: a conservative perpetual rate, typically 2-3%, never exceeding long-term nominal GDP growth.
7. Run `dcf.py` on all three `dcf_scenarios` inputs (`bear`, `base`, `bull`). Keep `current_share_price` in each input to get the `implied` block.
   - `dcf.py` discounts the projected cash flows and the terminal value to enterprise value, subtracts net debt for equity value, and divides by shares for per-share fair value.
   - The three results are the range. The sensitivity grid inside each result shows how WACC and perpetual growth move it.
8. Note the terminal-value share of total value in each result.
9. Cross-check against trading comparables (EV/EBITDA, P/E, EV/Sales). Choose peers in the same line of business, run `peers.py <symbol> --peers A,B,C`, and pipe its output into `comps.py`. Say which peers you chose.
10. If step 3 calls for `intrinsic.py`:
    1. Run `intrinsic-inputs.py <symbol>`.
    2. Challenge the growth rate, the maintenance-capex method, the business type, and the discount-rate floor before presenting.
    3. Pipe `intrinsic_input` into `intrinsic.py`, with your own `growth_rate`, `maintenance_capex`, `business_type` or `discount_rate_floor` when you changed one.
    4. Run `dcf.py` on its `buffett.dcf_input`, and on `normalized.dcf_input_mid_cycle` for the mid-cycle case.
11. If step 3 calls for `ddm.py`, run it on the `ddm_input` from `inputs.py`, `reit_tests` or `utility_tests`.
12. Compare with other analysts' estimates and ratings from a web search. Do this only after your own work is complete; do not reference other analysts before then.
13. Deliver the page.
    1. Write the results you ran to one file, `DIR/valuation.json`: the `render.py` input object from Background. DIR is the session scratchpad.
    2. Run `render.py --in DIR/valuation.json --out DIR/valuation.html`.
    3. Publish the HTML with the Artifact tool: icon chart, description "Valuation: SYMBOL at PRICE". Republish the same file path on later runs so the link stays stable.
    4. Reply with the published-page format below.
14. If the Artifact tool is not available in the session (a headless or non-interactive host), reply with the markdown fallback instead. Never both.

## Reply format

**When the page was published (the default):** these parts, in this order, then stop.

1. The artifact link on its own line.
2. One line naming only the methods that ran: **Valuation: SYMBOL** price `price` · DCF `dcf.fair_value_per_share` (range from the sensitivity grid, bear / base / bull) · Graham number `intrinsic.graham.graham_number` · growth formula `intrinsic.graham.growth_formula.value` · mid-cycle DCF `dcf_mid_cycle.fair_value_per_share`.
3. The bull and bear cases in two or three sentences using only the scripts' numbers: the terminal-value share when it exceeds 70%, the checklist pattern, the business-type caveats.
4. **Flags** — one bullet per `intrinsic.flags[].message`, or "None".
5. One sentence, once: the figures are general information at the stated assumptions, not financial, tax, or legal advice.

The page carries the sensitivity grids, checklists, owner earnings, normalized block, comps and DDM tables, so do not repeat them in the reply. If the user asks for a number the page shows, read it from the scripts' JSON.

**Markdown fallback (only when the Artifact tool is unavailable):** these parts, then stop.

1. The fair-value range with the WACC × terminal-growth sensitivity table.
2. Every key assumption.
3. The terminal-value share.
4. The Graham and Buffett figures with their checklists, when `intrinsic.py` ran.
5. The comps and DDM cross-checks.
6. The comparison to the current price with both bull and bear cases.
7. The flags.

**What any presentation of results holds to:**

- Present fair value as a range (bear / base / bull from `dcf_scenarios`), never a single point estimate.
- If the methods disagree widely (a latest-year DCF at twice the mid-cycle one, say), report the spread and what drives it. Do not average them into one figure.
- Show a sensitivity table varying WACC and perpetual growth rate, so the user can see how assumptions drive the output.
- State every key assumption: revenue growth rates, margin trajectory, capex intensity, WACC components (risk-free rate, beta, equity risk premium, cost of debt, tax rate), and terminal growth rate.
- Quantify how much of total value comes from the terminal value. If it exceeds ~70%, flag this and explain the implication.
- Compare the DCF-derived range to the current market price and note whether the stock appears undervalued, fairly valued, or overvalued relative to your assumptions.
- If comparable multiples diverge significantly from the DCF result, discuss possible reasons (market sentiment, sector premium/discount, differences in growth profile).
- Lead with the conclusion and key drivers, then the supporting detail. Thorough but digestible.

**When `intrinsic.py` ran, also:**

- Report the Graham number and growth-formula value as ceilings under their stated assumptions, and the owner-earnings DCF as a range.
- Report each margin of safety as price / value and the discount against that specific estimate.
- Give the checklist results as the pattern of passes and failures with `years_covered`.
- Name the maintenance-capex estimate and the growth rate used, with the `growth_alternatives` sensitivity.
- If `CYCLE_PEAK` fires, present the `normalized` figures beside the latest-year ones.
- For a `financial`, lead with `book_value_tests` and say the DCF is flagged.
- For a `reit`, lead with `reit_tests` and say GAAP EPS understates it.
- For a `utility`, lead with `utility_tests` and the dividend model.

## Rules

- Every number comes from the scripts. Present the scripts' numbers; do not recompute them by hand or add figures.
- Ground every estimate in historical data. Do not fabricate financials or guess at numbers you have not retrieved.
- When a `DCF_NOT_MEANINGFUL_FOR_…` flag or `NEGATIVE_FCF` fires, do not present the DCF as an estimate of value.
- Margin-of-safety bands are description, not a signal.
- Explain your reasoning at each step so the user can follow and challenge your assumptions.
- Distinguish clearly between historical facts, your projections, and your interpretation.
- When drawing on background knowledge, present insights in plain language (e.g., "valuation theory shows…"). Never cite internal reference codes, XML tags, or source identifiers to the user.
- Remind users that a DCF valuation reflects a set of assumptions about the future and is not a guarantee of market price convergence.
- Always attempt to fully answer the question yourself.
- Anything taken from a web search follows the dating protocol below.

<research_dating>
Every news item, analyst action, data release, or calendar entry you present carries the publication date printed on the source page, the source, and what it says. Search-result snippets blend years; the dateline on the article is the date.
1. Fix the window first: today's date, then the period the question covers ("this week" is the five trading days ending today; a price move is the sessions in which it happened).
2. Read the dateline of each candidate before using it. A hit that matches the month and day but not the year is a different year's event: leave it out, or label it "background (DATE)".
3. A cause offered for a price move is dated inside the move window. When no dated item falls inside the window, write "no dated catalyst found for WINDOW" and describe the move from price and volume alone.
4. Calendar dates (CPI, FOMC, central-bank decisions, earnings, ex-dividend) are for the current year, confirmed against a script's `as_of` field or a dated source before being presented as upcoming.
5. Items appear newest first with the date inline, e.g. "(Sep 8, 2026, Reuters)".
</research_dating>

- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
