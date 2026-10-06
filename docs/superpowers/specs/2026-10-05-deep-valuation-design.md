# Deep valuation mode — design

## Intent

**What the user said.** The valuation skill is too mechanical. Two modes are wanted:

- a **quick** mode for scanning many stocks
- a **deep** mode for one company

In deep mode, subagents work through the filings and the news. They act as a *bullshit detector*: they find the beliefs that management (or the market) holds, chase each one down against the evidence, and adjust the valuation by what they find. They do this in a loop. The deep mode:

- values the business's parts separately and adds them up
- uses higher discount rates when a plan is rosy or vague
- estimates **future returns**, not just a fair-value point

The method follows the practice of shops that spend the most on valuation (hedge funds, VC). The scripts are the default, but agents may go beyond the formulas when a case needs it. The output is digestible without a long read, and it is not a rigid template: each company's page fits its own case.

**Agreed decisions.**

- Result: a fair value per named scenario, plus the **annualized return at today's price** for each. There is no probability weighting; the person weighs the scenarios.
- Orchestration: the instructions in `SKILL.md` direct subagents dispatched with the Agent tool. No Workflow script.
- Every figure comes from an engine script by default. A custom calculation is allowed when the engine cannot express a case. It is written to a file, labelled "custom" on the page, and checked by the red team.
- The loop stops when a round moves no scenario's value by more than about 5%, or after 3 rounds (about 15 subagents at most).

**Success criteria.**

- A deep run on a real ticker produces:
  - a page that leads with the scenario → value → return table
  - a belief ledger whose every claim cites a dated source
  - at least one belief chased in a deep-dive round
  - scenarios that differ in their story, not just in a growth shift
- Quick mode still works unchanged, plus a 5-year return figure.
- All existing tests pass. The new scripts carry known-answer unit tests.

## Out of scope

- Probability-weighted expected returns
- Deep runs on several tickers at once
- Keeping past runs for tracking over time
- Workflow-script orchestration
- Changes to `dcf.py`, `ddm.py`, `comps.py`, `intrinsic.py` (quick mode keeps them)

## Components

### 1. `skills/valuation/scripts/model.py` — the driver-based engine

A pure-math stdin → stdout JSON script, like `dcf.py`. Its docstring is the contract. It exits 2 on invalid input with `{"error"}`.

**Input**

```json
{
  "symbol": "ACME",
  "price": 50.0,
  "shares_outstanding": 100.0,
  "years": 10,
  "base_discount_rate": 0.09,
  "tax_rate": 0.21,
  "cost_of_debt": 0.06,
  "claims": {"debt": 400, "cash": 150, "leases": 0, "minority_interest": 0,
             "pension_deficit": 0, "preferred": 0, "options": 0},
  "payout": 0.6,
  "annual_dilution": 0.0,
  "horizon": 5,
  "segments": [ <segment>, ... ],
  "scenarios": [ <scenario>, ... ],
  "sensitivity": {"scenario": "Base", "a": {"segment": "Core", "field": "margin_shift", "values": [-0.02, -0.01, 0, 0.01, 0.02]},
                  "b": {"segment": "Core", "field": "discount_premium", "values": [0, 0.01, 0.02, 0.03]}}
}
```

Units are the caller's own, as long as they are used throughout (e.g. millions, with shares in millions).

**Segment kinds**

| `kind` | Fields | Valued as |
|---|---|---|
| `operating` | `revenue0`, `growth` (scalar or per-year list), `margin` (EBIT margin, scalar or list), `sales_to_capital` (scalar or list), `tax_rate` (optional, falls back to the top level), `discount_premium` (default 0), `premium_reason`, `terminal` (`{"method":"gordon","growth":g}` or `{"method":"multiple","metric":"ebit"\|"ebitda"\|"revenue","multiple":m}`), `da_pct_revenue` (required for an EBITDA multiple) | FCFF_t = EBIT_t(1−tax) − reinvestment_t, where reinvestment_t = (Rev_t − Rev_{t−1}) / sales_to_capital_t. Discounted at `base_discount_rate + discount_premium`, or at `discount_rate` when that is given. Terminal value at year N. |
| `cost` | `cost0` (after-tax annual cost, positive number), `growth`, `discount_premium` | A negative perpetuity: the cost path grows to year N, then the Gordon terminal value at the segment's terminal growth (default 0.02). |
| `asset` | `value` | Its stated value (a stake, land, excess cash not counted in `claims`). |
| `venture` | `value_if_success`, `probability`, `cost_pv` | Risk-adjusted NPV = `probability × value_if_success − cost_pv`. This is the standard rNPV for a long-shot project. It is shown on its own line so it is never hidden inside a total. |
| `residual_income` | `book0`, `roe` (scalar or list), `retention` (scalar or list), `cost_of_equity`, `discount_premium`, `terminal_growth` | Equity value = book0 + Σ PV((ROE_t − ke)·book_{t−1}) + terminal residual income. It is added to **equity**, not enterprise value. This is for banks and insurers. |

**Scenario**

```json
{"name": "Turnaround stalls",
 "summary": "One sentence story.",
 "must_be_true": ["Core margin stays under 8%", "..."],
 "overrides": {"Core": {"growth": [...], "margin": 0.07, "fails": null},
               "NewCo": {"fails": {"year": 3, "salvage": 20}}},
 "payout": 0.4, "annual_dilution": 0.01, "claims": {...}}
```

- `overrides` replace the segment's fields named in it. Fields not named keep their base values.
- `fails` cuts the segment's cash flows after year `year − 1`. It adds `salvage` at year `year`, and the segment then has no terminal value.
- Top-level `payout`, `annual_dilution` and `claims` can be overridden per scenario.

**Calculation per scenario**

1. Each segment gives a yearly table (revenue, EBIT, tax, reinvestment, FCFF) and a present value.
2. Enterprise value = Σ(operating, cost, asset, venture).
3. Equity = EV − debt + cash − leases − minority − pension − preferred − options + Σ residual_income.
4. Value per share = equity / shares_outstanding.
5. The share of each segment's value that comes from its terminal value is reported.
6. `value_ex_premiums` is the same scenario rerun with every `discount_premium` set to 0. The difference is the **cost of skepticism**.
7. **Path to the horizon** (for returns), for t = 1..horizon:
   - FCFE_t = Σ FCFF_t − after-tax interest on net debt_{t−1}
   - distributions_t = payout × max(FCFE_t, 0)
   - net debt_t = net debt_{t−1} − (FCFE_t − distributions_t)
   - shares_t = shares_{t−1} × (1 + annual_dilution)
   - Per-share distributions are distributions_t / shares_t.
8. **Exit value at the horizon H:** the value at year H of every flow after H, discounted at each segment's own rate, less net debt_H, divided by shares_H. This is the `dcf_roll` method. An optional scenario `exit_multiple` (`{"metric":"ebit"|"ebitda"|"revenue"|"fcfe","multiple":m}`) gives a second exit value on year-H company totals. Both are reported when given.
9. `returns_input` is a ready `returns.py` input, so the two scripts pipe.

**Validation:** `years` must be at least `horizon + 1` and between 1 and 30. Every rate must be a finite number. A Gordon terminal growth must be below the segment's discount rate. A list field must have length `years`. Scenario names must be unique. An override must name a segment that exists.

**Output**

```json
{
  "symbol", "price", "horizon",
  "scenarios": [{"name", "summary", "must_be_true",
                 "enterprise_value", "equity_value", "value_per_share", "value_ex_premiums",
                 "upside": "value_per_share / price - 1",
                 "segments": [{"name", "kind", "value", "terminal_share", "discount_rate", "premium", "premium_reason", "years": [{t, revenue, ebit, reinvestment, fcff}]}],
                 "bridge": {"enterprise_value", "debt", "cash", "...", "equity_value"},
                 "path": [{t, fcfe, distributions_per_share, net_debt, shares}],
                 "exit": {"dcf_roll": v, "multiple": v|null}}],
  "sensitivity": {"scenario", "a": {...,"values"}, "b": {...,"values"}, "value_per_share": [[...]]},
  "returns_input": {...},
  "flags": [{"code", "message"}]
}
```

**Flags:**

| Flag | Fires when |
|---|---|
| `TERMINAL_HEAVY` | A segment gets more than 75% of its value from the terminal value |
| `NEGATIVE_EQUITY` | A scenario's equity value is not positive |
| `MARGIN_ABOVE_HISTORY` | Optional: the input carries `history.max_margin` and a path exceeds it |
| `REINVESTMENT_NEGATIVE` | Shrinking revenue releases capital. This is allowed but noted. |

### 2. `skills/valuation/scripts/returns.py` — returns at today's price

A pure-math stdin → stdout script. Two input modes:

- **`paths`** (from `model.py`'s `returns_input`): `{"price", "horizon", "hurdle": 0.10, "scenarios": [{"name", "distributions_per_share": [...], "exit_value_per_share": v, "exit_multiple_value": v|null}]}`
- **`convergence`** (quick mode, from a `dcf.py` result): `{"price", "horizon", "hurdle", "scenarios": [{"name", "fair_value", "cost_of_equity", "dividend_yield"}]}`
  - The market closes the gap to fair value by the horizon.
  - Fair value compounds at cost_of_equity − dividend_yield.
  - Dividends are dividend_yield × the prior year's fair value.
  - All of this is stated in the output's `assumptions`.

**Output per scenario:** `irr` (annualized; bisection on [−0.99, 5]), `total_multiple` ((Σ distributions + exit) / price), and `hurdle_exit_value` (the exit value per share that would earn exactly the hurdle). When `exit_multiple_value` is given, `irr_at_multiple` too. When exit + distributions ≤ 0, `irr` is −1 and the flag `TOTAL_LOSS` is raised.

### 3. `skills/valuation/scripts/render_deep.py` — the deep page

It builds the page with `page.render`, as `render.py` does.

**Input:** `{"symbol", "price", "as_of", "model": <model.py output>, "returns": <returns.py output>, "ledger": <ledger.json>, "blocks": [...], "missing_roles": [...], "notes": [...]}`

**Fixed at the top, always:**

1. **Scenario table:** name, story, value per share, upside, annualized return, total multiple, and what has to be true.
2. **Price against scenarios:** a horizontal strip with the price marked against each scenario's value.

**Optional blocks, in the order given in `blocks`.** Each has a type and a schema. An unknown type, or a block missing a required field, is exit 2.

| `type` | Required fields | Shows |
|---|---|---|
| `segments` | `scenario` | Waterfall of segment values to equity, from `model` |
| `drivers` | `segment`, `field` (`revenue`\|`ebit`\|`fcff`) | That segment's line per scenario |
| `ledger` | — | Belief ledger: verdict chip, belief, holder, and the model consequence. Each row expands to its sourced evidence for and against. |
| `track_record` | `rows: [{period, metric, guided, actual, source}]` | Guidance against actual results |
| `forensics` | `items: [{finding, severity, source}]` | Accounting findings |
| `skepticism` | — | `value_per_share` against `value_ex_premiums` per scenario, with each premium and its reason |
| `sensitivity` | — | The model's two-way grid as a heatmap around the price |
| `custom` | `title`, `file`, `result`, `explanation` | A labelled custom calculation |
| `text` | `title`, `markdown` | Free text. The renderer escapes HTML and supports only paragraphs, bullets and bold. |

`missing_roles` and `notes` render in the Flags section, alongside the flags from `model` and `returns`.

**It prints** `{"out", "title", "symbol", "scenarios", "blocks", "flags"}`.

### 4. Case folder and belief ledger

Each deep run uses `DIR/deep-SYMBOL/`, where DIR is the scratchpad:

| Path | Holds |
|---|---|
| `baseline/` | Quick-mode script output: `fundamentals.json`, `inputs.json`, `intrinsic.json`, `edgar.json` |
| `research/<role>.md` | One findings file per round-1 role |
| `ledger.json` | The merged belief ledger |
| `threads/<n>-<slug>.md` | One file per deep-dive |
| `model.json` | The `model.py` input |
| `custom/*.py` | Custom calculations, each printing JSON |
| `page.json` | The `render_deep.py` input |

**Ledger entry**

```json
{"id": "B3", "belief": "Pricing actions will hold margin at 20%", "holder": "management",
 "stakes": "high|medium|low", "verdict": "supported|doubtful|contradicted|unknowable|open",
 "for": [{"claim", "source", "date"}], "against": [{"claim", "source", "date"}],
 "consequence": {"segment": "Core", "field": "margin", "change": "path capped at 17% in Base"},
 "thread": "threads/2-pricing.md"}
```

`render_deep.py` validates the ledger's shape for the `ledger` block. A claim with no `source` or `date` is exit 2. This enforces the citation rule mechanically.

### 5. Role briefs: `skills/valuation/references/deep-roles.md`

There is one reference file with one `##` section per role and a Contents list. Reference files are one level deep, so the briefs live in a single file. `SKILL.md` names the section to hand each subagent. Each brief states:

- what to look for
- which scripts to run (`edgar.py`, `filing.py --item/--search/--diff`, WebSearch/WebFetch for 8-K exhibits and news)
- the citation rule
- the output file and its sections

| Role | Round | Output |
|---|---|---|
| Forensic accountant | 1 | `research/forensic.md` covers these checks: earnings vs. operating cash flow, receivables, inventory and deferred revenue growth against revenue, capitalized costs, the non-GAAP to GAAP gap, stock pay as a share of revenue and operating cash flow, auditor changes, accounting-policy changes (`--diff` on the notes), related parties, and the red-flag search terms. It ends with candidate beliefs. |
| Management claims | 1 | `research/claims.md` lists strategy, guidance and the beliefs behind them. It includes a track-record table of past guidance against reported results, from older 10-Ks and 8-K Item 2.02 exhibits, and ends with candidate beliefs. |
| Industry & news | 1 | `research/industry.md` covers competitors, market size and growth, pricing, regulation, and dated news (following the skill's dating rule). It ends with candidate beliefs. |
| Segment economics | 1 | `research/segments.md` gives per-segment revenue, operating income, assets and capex (from the segment note), says which segment carries the value, and proposes segment boundaries for `model.py`. |
| Thread deep-dive | 2+ | `threads/<n>-<slug>.md` takes one belief to a verdict with evidence for and against, and gives the model consequence as a specific field and value. It can list new beliefs it found. |
| Red team | final | `research/redteam.md` attacks the central scenario: the weakest input, an omitted risk, and any double counting. It reruns every `custom/*.py` and checks the result against the stated method. It lists concrete changes. |

Every subagent returns a one-paragraph summary plus its file path. The full findings stay in the file.

### 6. `SKILL.md` changes

- The description gains "deep dive" in its trigger words while staying at or under 260 characters.
- **Background:**
  - a "Two modes" table (the mode-picking table from the design)
  - short descriptions of `model.py`, `returns.py` and `render_deep.py`
  - the case folder layout
- **Scripts:** the three new commands, table rows, and the exit codes they share.
- **Steps:** Steps gets three case lines:
  - **Quick (one company)**: today's steps, plus `returns.py` in convergence mode on the bear, base and bull results
  - **Quick (several companies)**: the same, with the page skipped
  - **Deep**: the procedure below
- **Deep procedure (in Steps):**
  1. Check EDGAR (`edgar.py SYMBOL`). If it exits 4, stop, say so, and offer quick mode.
  2. Run the baseline scripts into `baseline/`.
  3. Dispatch the four round-1 roles in parallel with the Agent tool (general-purpose). Each prompt gets the matching section of `references/deep-roles.md`, the case folder path, the symbol and today's date.
  4. Merge the candidate beliefs into `ledger.json`. Rank them by stakes × uncertainty.
  5. Write `model.json`: segments from the segment economics findings, with drivers anchored on history and adjusted by the ledger. Use 3–5 named scenarios that differ in story. Each premium has a reason tied to a ledger entry.
  6. Run `model.py`, then `returns.py`.
  7. Run thread rounds:
     - Pick up to 4 open beliefs with high or medium stakes and dispatch one deep-dive each, in parallel.
     - Apply the verdicts to `ledger.json` and `model.json`, then rerun.
     - Stop when no scenario's value moved more than 5%, or after round 3.
  8. Dispatch the red team. Apply the changes it raises that hold up, and say which you rejected and why.
  9. Write `page.json`, choosing the blocks that tell this company's story. Run `render_deep.py` and publish.
  10. Reply in the deep reply format.
- **If the Agent tool is unavailable:** run the roles one after another in the main context and say so.
- **If a subagent fails or returns nothing:** add its role to `missing_roles` and continue.
- **Reply format, deep:**
  1. the link
  2. the scenario table: name, value per share, annualized return
  3. the two or three ledger verdicts that move value most, each with its source
  4. the cost of skepticism in one line
  5. flags, including missing roles
  6. the general-information sentence

  The markdown fallback holds the same content plus the ledger.
- **Rules:**
  - "Every number comes from the scripts" becomes: every number comes from the scripts or from a labelled `custom/*.py` the red team reran.
  - A belief without a dated source does not change the model.
  - Discount-rate premiums are stated with their reason.
  - The existing compliance bullets are unchanged.

`SKILL.md` stays under the 500-line limit. The deep steps are kept compact, and the per-role detail lives in `deep-roles.md`.

### 7. Quick mode

Steps 7 and 13 gain one sub-step each:

- run `returns.py` in convergence mode on the three scenario results, with `cost_of_equity` from `inputs.py`'s WACC assumptions and the dividend yield from `fundamentals.py`
- add `returns` to the `render.py` input

`render.py` gains an optional `returns` key, shown as one row of tiles: bear, base and bull annualized returns. Nothing existing changes. In the funnel's price check (stock-screener step 4), returns come along automatically through the valuation flow.

## Error handling

| Situation | Behaviour |
|---|---|
| EDGAR not configured / fundamental-research missing | Deep mode stops before dispatch, says why, and offers quick |
| A subagent fails or returns nothing | Its role goes in `missing_roles`, shown on the page and in the reply |
| `model.py` rejects input | The main model fixes `model.json` and reruns. A hand-computed substitute is never used. |
| Custom calc fails on rerun by red team | It is left out of the page and noted in `notes` |
| Financial, REIT, utility | Financial: a `residual_income` segment. REIT: `operating` segments on property NOI with an exit-multiple terminal. Utility: `operating` with a low premium and a Gordon terminal. The existing `DCF_NOT_MEANINGFUL_…` flags from `inputs.py` are echoed into `notes`. |

## Testing

- `tests/test_scripts_valuation.py` gains:
  - `model.py`:
    - one operating segment with constant growth, margin and sales-to-capital equals the closed-form two-stage FCFF value, independently computed
    - a `cost` segment lowers EV by its perpetuity value
    - an `asset` and a `venture` add as stated
    - a `residual_income` segment matches hand arithmetic
    - `fails` truncates flows and adds salvage
    - overrides change only the named fields
    - `value_ex_premiums` equals the value with premiums zeroed
    - the sensitivity grid's centre equals the scenario value
    - validation errors exit 2
  - `returns.py`:
    - a known stream reproduces a known IRR (e.g. price 100, distributions 0, exit 161.051 over 5 years gives 10%)
    - convergence mode with fair value = price and no dividends gives an IRR equal to cost of equity
    - `hurdle_exit_value` round-trips
    - `TOTAL_LOSS`
  - `render_deep.py`:
    - each block type renders
    - an unknown block exits 2
    - a ledger claim with no source exits 2
    - a page audit through `render_and_audit` (Chrome-gated, like the existing render tests)
  - `render.py`: the `returns` tiles render when the key is present
- `tests/test_skills_structure.py`: register `valuation/references/deep-roles.md` in `REFERENCE_FILES`. Existing tests enforce the description length, the layout and the Contents list.
- **Manual:** one deep run on a watchlist ticker (PHM) end to end before the branch is called done, with the page published privately.

## Docs

- `CHANGELOG.md`: an Unreleased entry
- `docs/scripts.md`: the three scripts
- `README.md` / `docs/examples.md`: one deep-mode example prompt, if the existing structure lists per-skill prompts
