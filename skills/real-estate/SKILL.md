---
name: real-estate
description: Real-estate calculators for mortgage and amortization, refinance breakeven, rent vs buy, rental underwriting (NOI, cap rate, DSCR, IRR), affordability and REIT metrics (FFO, AFFO, NAV). Use when the user asks about a home, mortgage, rental property or REIT.
---
Runs real-estate calculations with explicit assumptions and shows what moves the answer. It describes what the numbers show and what is not modelled, and stops there.

## Background

- **No property data feed.** Prices, rents, rates and taxes come from the user. Only REIT figures are fetched, from Yahoo statements.
- **`realestate.py` is the shared math.** Its docstring is the contract for every action: `mortgage`, `refinance`, `rent_vs_buy`, `rental`, `affordability`, `reit`. Rates are decimals.
- **`reit.py`** assembles FFO and AFFO inputs from Yahoo statements and runs the `reit` action.
- **Mortgage model.** Fixed-rate only. ARM and interest-only loans are not modelled. Payments are rounded to cents before amortizing, as lenders do.
- **PMI.** Charged monthly until the balance crosses 80% LTV, and it never returns. 80% is the borrower-requestable cancellation point; lenders auto-cancel at 78% by law.
- **Rent vs buy.** The renter is assumed to invest the buyer's upfront cash and every year's cost difference at `investment_return`. The buyer's position is valued net of selling costs each year. Small changes in appreciation and investment return swing the answer.
- **Rental projection.** Property tax grows at `tax_growth`, which defaults to the assumed appreciation rate since assessed value tends to track it. The rest of operating expenses grows at `expense_growth`. `capex_reserve_rate` and `leasing_rate` (both of EGI) underwrite a reserve for capital repairs and turnover or leasing costs explicitly instead of ignoring them.
- **Rental rules of thumb.** The 1% rule (monthly rent at or above 1% of price) is a screen, not a valuation. Lenders typically want DSCR of 1.20 to 1.25 or more. Cap rate is unlevered and comparable across properties; cash-on-cash depends on leverage.
- **Affordability.** Uses the 28% front-end and 36% back-end debt-to-income ratios. Lenders and loan programs vary (FHA allows more), and the result ignores closing costs and reserves.
- **REIT valuation.** Uses FFO and AFFO rather than earnings because depreciation is non-cash for appreciating property. A discount to NAV can reflect leverage, sector or interest-rate expectations rather than mispricing.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/real-estate/scripts/realestate.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/real-estate/scripts/reit.py" <symbol> [--nav NAV_PER_SHARE] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/real-estate/scripts/render.py" --in result.json --out page.html
```

| Command | What it does |
|---|---|
| `realestate.py` | Reads one JSON object whose `action` picks the calculator and prints the result. For `rental`, `"scenarios": true` adds a small appreciation and rent-growth grid in the same call. |
| `reit.py` | Fetches the REIT's statements and prints its multiples, with `notes` and `inputs`. `--nav` adds the premium or discount to NAV. |
| `render.py` | Turns a saved `realestate.py` or `reit.py` result into one self-contained HTML page for the Artifact tool. Prints `{"out", "title", "calculators", "flags"}`. |

`render.py` detects the calculator by its keys and renders only the matching sections, with light and dark themes and no external scripts.

| Calculator | What the page shows |
|---|---|
| Mortgage | Payment, PITI and interest tiles; a balance, interest and principal line chart; the sortable amortization schedule; the extra-payment and PMI lines |
| Refinance | Breakeven and savings tiles; the cumulative-savings line from `savings_path` |
| Rent vs buy | The buy and rent net-worth crossover chart and the year table |
| Rental | NOI, cap rate, DSCR, cash-on-cash and IRR tiles; the underwriting table; the cash-flow table; the appreciation by rent-growth scenario heatmap |
| Affordability | Tiles |
| REIT | Tiles, multiples, notes |

Flags come last on every page.

All three scripts print JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input. From `render.py`: no calculator matches the input. | `error` |
| 5 | Yahoo error, or no statements | the error |
| 6 | Python dependencies missing | the error |

## Steps

1. Pick the calculator that matches the question.

   | The user asks about | Run |
   |---|---|
   | A mortgage payment, amortization, extra payments, PMI | `realestate.py` with `mortgage` |
   | Whether a refinance pays back | `realestate.py` with `refinance` |
   | Renting against buying | `realestate.py` with `rent_vs_buy` |
   | A rental property | `realestate.py` with `rental` |
   | How much house an income supports | `realestate.py` with `affordability` |
   | A REIT | `reit.py <symbol>` once, with `--nav` if the user supplies a NAV estimate |

2. Collect the inputs the action needs (see the docstring). Ask only for what the user has not given and cannot be defaulted.
3. If the user does not know a current mortgage rate or local property-tax rate, look it up with a web search and cite the source.
4. Note every default you apply: rate, term, tax rate, maintenance, closing rates, appreciation, rent growth, investment return. They go in the Assumptions line.
5. Run the script once per scenario and write the output to `DIR/real-estate.json` (DIR is the session scratchpad).
6. For `rent_vs_buy` and for a `rental` projection, also run a pessimistic scenario (lower appreciation and rent growth, higher rate) unless the user fixed those inputs. Keep its JSON. For `rental`, passing `"scenarios": true` returns the grid in one call instead.
7. Run `render.py --in DIR/real-estate.json --out DIR/real-estate.html`.
8. Publish the HTML with the Artifact tool: icon calculator, description naming the calculator and its key input, for example "Mortgage on a $375,000 home at 6.5%". Republish the same file path on later runs so the link stays stable.
9. Reply with the published-page format below.
10. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 7 and 8 and reply with the markdown fallback instead. Never send both.

## Reply format

**Page published (the default).** In this order, then stop.

1. The artifact link on its own line.
2. One line with the calculator's key figures:

   | Calculator | Key figures |
   |---|---|
   | Mortgage | payment `payment` · PITI `piti` · total interest `total_interest`, and the `with_extra` savings when present |
   | Refinance | monthly savings `monthly_savings` · breakeven `breakeven_months` months · lifetime delta `lifetime_delta` |
   | Rent vs buy | breakeven year `breakeven_year` (or "buying does not catch up within the horizon") · year-1 monthly buy `monthly_cost_year1.buy` vs rent `monthly_cost_year1.rent`, and the pessimistic run's breakeven when one ran |
   | Rental | NOI `noi` · cap rate `cap_rate` · DSCR `dscr` · cash-on-cash `cash_on_cash` · IRR `projection.irr` when present |
   | Affordability | max price `max_price` · max loan `max_loan` · max payment `max_housing_payment` (`binding_ratio`) |
   | REIT | P/FFO `p_ffo` · P/AFFO `p_affo` · dividend yield `dividend_yield` · NAV premium `nav_premium` |

3. The Assumptions line: every default applied. For `mortgage`, that the model is fixed-rate only. For `rental`, the `tax_growth` assumption.
4. **Flags** — one bullet per `flags[].message`, or "None".
5. One sentence that it is general information at the stated assumptions, not financial, tax, or legal advice.

The page carries the schedule, charts, year tables, scenario grid and notes. Do not repeat them in the reply. If the user asks for a number the page shows, read it from the script's JSON. When a pessimistic scenario ran, quote its headline figure in the reply.

**Markdown fallback (only when the Artifact tool is unavailable).** Render the calculator output that matches the question.

- **Mortgage** — one line: loan `principal` at `rate` for `months` months → payment `payment`, PITI `piti` (tax `tax_monthly`, insurance `insurance_monthly`, HOA `hoa_monthly`, PMI `pmi_monthly`), total interest `total_interest`.
  - Then a 5-row slice of `schedule` (years 1, 5, 10, 20, last), including that year's `pmi`.
  - When `with_extra` is present, one line: "+`extra_payment`/month pays off in `months` months (`months_saved` sooner) and saves `interest_saved` interest."
  - When `pmi_monthly` > 0, one line: PMI drops off in year `pmi_off_year` (borrower-requestable at 80% LTV; lenders auto-cancel at 78%), total PMI paid `pmi_total`.
- **Refinance** — a table: Current payment · New payment · Monthly savings · Closing costs · Breakeven months · Remaining interest now · New total interest · Lifetime delta · Term extension. Then one line for `new_loan_at_current_payment`.
- **Rent vs buy** — a table from `by_year`: Year · Buy net worth · Rent net worth · Advantage buy.
  - One line: breakeven year `breakeven_year` (or "buying does not catch up within the horizon"), year-1 monthly cost buy `monthly_cost_year1.buy` vs rent `monthly_cost_year1.rent`.
  - List the `assumptions` verbatim.
  - Show both the base and the pessimistic run when both ran.
- **Rental** — a table: Gross rent · Effective gross income · Operating expenses · NOI · Cap rate · Debt service · DSCR · Cash flow · Cash invested · Cash-on-cash · GRM · Rent/price · Break-even occupancy · Expense ratio.
  - When `projection` is present add: hold `hold_years` years, sale `sale_price`, total profit `total_profit`, equity multiple `equity_multiple`, IRR `irr`, and the property-tax growth assumption used (`tax_growth`, defaulting to the appreciation rate).
  - When `scenarios` is present add a small table: appreciation × rent growth → IRR, total profit, cash-on-cash.
- **Affordability** — one line: max housing payment `max_housing_payment` (`binding_ratio`) → max loan `max_loan`, max price `max_price` with the given down payment.
- **REIT** — a table: FFO/share · P/FFO · FFO yield · AFFO/share · P/AFFO · Dividend yield · FFO payout · AFFO payout · NAV premium. Then the `notes` lines verbatim.

Then, after the calculator output:

1. The Assumptions line, as in the published-page format.
2. **Reading:** two or three sentences, one favourable and one unfavourable, using only the numbers above.
3. **Not modelled:** income-tax effects (mortgage-interest deduction, depreciation, capital-gains exclusion), transaction friction beyond the closing rates given, local rent control or tax reassessment rules unless the user supplied them, and adjustable-rate or interest-only mortgages (the mortgage model is fixed-rate only).

Money to 2 decimal places with thousands separators. Ratios as percentages to 2 decimal places.

## Rules

- Every number comes from the script.
- State every default you applied in the Assumptions line.
- For any `mortgage` answer, state that the model is fixed-rate only. For an ARM or interest-only loan, give the equivalent fixed-rate reading and say so; do not approximate one.
- For any `rental` projection, state the property-tax growth assumption (`tax_growth`, which defaults to the appreciation rate) alongside the other growth assumptions.
- Show both a base and a pessimistic run for rent-vs-buy and rental projections when the user has not fixed appreciation, rent growth and rate.
- Never turn a breakeven year or IRR into advice. Describe what the numbers show and what is not modelled.
- Cite the source of any mortgage rate or property-tax rate you looked up.
- When the answer turns on the user's own tax or legal situation (a deduction, a 1031 exchange, depreciation recapture, a lease or title question), give the general rules, then say that a tax professional (CPA or enrolled agent) or an attorney can confirm how they apply to them.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
