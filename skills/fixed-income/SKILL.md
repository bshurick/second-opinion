---
name: fixed-income
description: Shows what a bond or bond fund earns held to a horizon, what a rate move does, the rate path prices assume against the Fed's projections, and where yields sit in history. Use when the user asks about BND, Treasuries, bond ladders, or if bonds are a good deal.
---
Answers what a person holding a bond or a bond fund wants to know: what it earns a year if held, whether that beats cash, what a rate move does along the way, and whether yields are high or low against history. Everything is arithmetic on market prices, so the skill never gives a fair value, a target price, or a cheap/expensive verdict.

## Background

**The questions, in the order to answer them**

1. What it earns a year if held.
2. Whether that beats cash.
3. What a rate move would do along the way.
4. Whether yields are high or low against history.
5. For a fund, which of its three published yields is which.

Two analyst questions sit behind those. Answer them only when asked: what short-rate path today's prices already assume against the Fed's own projection, and where a fund's yield comes from.

**Where the figures come from**

- The Treasury par curve: FRED daily series, bootstrapped to a zero curve.
- The FOMC's own published projections.
- FRED history, for the percentile ranks.
- For a fund, the four volatile characteristics, read live from its index proxy's iShares page.
- Everything else is arithmetic on those inputs. The derivations are in `references/bond-math.md`; read it when the user asks how a figure is calculated.

**Why there is no fair value**

- Every input is a market price: a quoted yield, a par curve, a published spread. Anything modelled from them reproduces the market price by construction.
- `fund.py`'s calculated yield exists to check the arithmetic, not to disagree with the market. It carries a `circularity_note` saying so.
- A gap between the calculated and published yield is model error first. `assumptions.gap_expectation` states the measured band, and a gap inside it is nothing.
- The percentile table is the one place a "dear or cheap" word is defensible, and only as ranking against history, never as a call. A high percentile on a yield means a holder is paid more than usual. A low percentile on a spread means a holder is paid less than usual for taking credit risk. Both describe where today sits; neither is a forecast.

**What the scripts model**

- The scripts price one fixed-coupon bond, and curves built from fixed-coupon par yields.
- `fund.py` maps seven symbols: BND, BIV, BNDX, BSV, BLV, VCIT, VCSH. Any other symbol exits 2.
- A fund is modelled as a single bond with the average coupon, the weighted average life as the maturity, and the current yield. That is an approximation of a portfolio that actually rolls.
- `horizon.py` and `bond.py` need no network.

**The three durations `horizon.py` reports.** They are three different quantities.

| Field | What it is |
|---|---|
| `duration_years` | The Macaulay duration, in years. The horizon at which a rate move's price loss and reinvestment gain cancel, so it is the figure `matched` is measured against. |
| `modified_duration_years` | Price sensitivity per unit of yield, a fraction of price. Never format it with a percent sign: 7.08 means 7.08% per 100 bp, and `7.08%` on the page would be wrong by a factor of 100. |
| `published_effective_duration_years` | The fund's own published effective duration. Present only when the input carried one. Absent, not null, for a bond-like payload. |

- `duration_years` means something different going in and coming out. In a fund payload, `characteristics.duration_years` is the published effective duration. In `horizon.py`'s output, `duration_years` is the Macaulay duration of the single-bond model. Label them whenever both appear.
- The published effective duration and the immunising horizon are not supposed to agree. BND's page publishes 5.75 for its own portfolio; the single-bond model of the same fund gives 7.27. They answer different questions.

**`locked_in_return_pct` and the two yield conventions**

- `locked_in_return_pct` is an effective annual rate. It equals the `delta_yield_bp: 0` scenario exactly.
- A quoted yield to maturity is bond-equivalent: it compounds twice a year. So a published 5.31% comes back as `(1 + 0.0531/2)² − 1 = 5.3805%`.
- That is a compounding convention and nothing else. At a fixed frequency the figure is identical at every horizon, including at maturity.

**`matched` is a tolerance, not immunity**

- `matched` means the horizon is within 20% of the Macaulay duration.
- The `±200 bp` spread is smallest at the Macaulay horizon and grows as the horizon moves away from it. It also grows with maturity and with the size of the move.
- Inside the same matched band it has been measured from 0.0136 percentage points at the centre to 1.0262 at the lower edge on one bond.

**The three yields a bond fund publishes.** They are the main thing users get wrong. They can differ by more than a percentage point without anything being wrong.

| Yield | Field under `characteristics` | Meaning |
|---|---|---|
| Distribution yield | `distribution_yield_pct` | What the fund has actually paid out, annualised from its recent distributions. It follows the coupons on bonds already held, so it lags a change in rates. |
| SEC yield | `sec_yield_pct` | A standardised 30-day figure, net of the expense ratio, defined so any two funds can be compared on the same basis. |
| Yield to maturity | `ytm_pct` | What the portfolio would return if every bond were held to maturity and every coupon reinvested at that same yield, gross of the expense ratio. The horizon answer is built from this one. |

- `distribution_yield_pct` can come back `null` with no warning beside it, because it is not one of the fields the script insists on.

**Instruments the scripts do not model.** `references/treasuries.md` is the taxonomy: what the Treasury issues, how each is quoted, and which the scripts can and cannot price. Read it before answering anything about bills, TIPS, FRNs or STRIPS. Three traps it covers:

- **A bill's quoted rate is a discount rate, not a yield.** It divides the gain by face rather than by what was invested, on a 360-day year, so it understates the return twice over: a 4.00% 13-week bill yields 4.10%. Comparing a quoted bill rate with a note's YTM, a CD's APY or a fund's SEC yield compares two different quantities.
- **No script here prices a bill.** `bond.py` and `horizon.py` model whole semi-annual periods. A 4-, 8- or 13-week bill exits 2 (`years x freq must round to at least one period`), and a 17-week bill is quietly priced as a 26-week one.
- **A STRIP is in scope.** It is zero-coupon too, but a 10-year STRIP spans 20 periods. The boundary is the period count, not the missing coupon.
- **TIPS principal moves with CPI.** The deflation floor protects the principal repaid at maturity only, not the coupons, which are paid on principal that has accreted downward. `bond.py` and `horizon.py` given a TIPS real yield produce real-terms arithmetic with the accretion absent. The supported TIPS view is `rates.py`'s real-yield and breakeven percentiles.
- **Treasury interest is exempt from state and local income tax.** That is worth nothing in a state without one, and nothing inside an IRA or 401(k). The reference gives the taxable-equivalent arithmetic.

**Bonds against stocks (`gravity.py`)**

- A bond yielding y with no growth costs `1/y` per unit of coupon: 5% is 20x, 4% is 25x. `gravity.py` prints that implied P/E for a Treasury beside an equity proxy's trailing P/E, and the gap between the two earnings yields.
- The equity side is not ranked. Today's P/E comes from the proxy's holdings while the long history is as-reported index earnings, so a percentile across that boundary would be false precision. `equity.not_ranked_because` carries the sentence.
- The comparison is the contested Fed Model: a nominal bond yield against earnings that grow with inflation. The arithmetic holds. Reading the gap as a signal about what to own is the contested part. `assumptions.fed_model_caveat` carries the caveat.
- `gravity.py` has no section on the page. Its figures go in the reply, not into the object `render.py` reads.

**Out of scope.** Individual corporate credit analysis, default probabilities, callable and mortgage prepayment modelling, and any bond's fair value.

## Scripts

Run with the Bash tool. Every script prints JSON. Each script's docstring is its contract.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fixed-income/scripts/rates.py"
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fixed-income/scripts/fund.py" SYMBOL
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fixed-income/scripts/bond.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fixed-income/scripts/horizon.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fixed-income/scripts/render.py" --in analysis.json --out page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/fixed-income/scripts/gravity.py" [--tenor 10] [--proxy SPY]
```

| Script | Input | What it does |
|---|---|---|
| `rates.py` | No arguments, nothing on stdin. | The rate environment: par curve, zero and forward curves, `implied_short_rate_path`, `implied_average_short_rate_pct`, `fomc_projection`, `percentiles`, `benchmarks`. |
| `fund.py` | The symbol as its one positional argument, nothing on stdin. | A fund's `characteristics`, its `yield_decomposition`, `price_map`, `warnings` and `circularity_note`. |
| `bond.py` | One JSON object on stdin: `coupon_rate`, `years`, and `ytm` or `price`, as decimals. | The shared pure math: price, the price map and the risk measures for one bond. |
| `horizon.py` | One JSON object on stdin, in one of the two shapes below. | The annual return held to `horizon_years`, re-priced across ±200 bp, with `scenarios`, `spread_pct`, `value_paths`, `matched` and the three durations. |
| `render.py` | `--in` a file holding the combined object, `--out` the page. | One self-contained HTML page. Prints `{"out", "title", "sections"}`. |
| `gravity.py` | `--tenor` (default 10 years) and `--proxy` (default SPY), both optional. | The Treasury's implied P/E beside the equity proxy's trailing P/E, and the gap between the two earnings yields. |

**The two shapes `horizon.py` accepts**

- Bond-like, all decimals: `{"coupon_rate": 0.0379, "years": 8.2, "ytm": 0.0531, "horizon_years": 6.91}`.
- Fund-like: `fund.py`'s own output with `horizon_years` added.

**What pipes into what**

- `fund.py`'s output goes into `horizon.py` on stdin, once `horizon_years` is added to it. That is the only direction that works.
- `bond.py`'s output does not go into `horizon.py`. It echoes `coupon_rate` and `years` under `assumptions`, not at the top level `horizon.py` reads, so `bond.py | horizon.py` exits 2 asking for them.
- The period count `bond.py` reports cannot stand in for `years`: 8.2 years at two coupons a year rounds to 16 periods, which is 8.0.

**What `render.py` reads**

- The combined object is `{"symbol": ..., "horizon": ..., "rates": ..., "fund": ...}`. Each value is that script's whole output.
- At least one of `horizon`, `rates` and `fund` must be present, or `render.py` exits 2.
- Outside a result's `assumptions` block, only named fields are rendered. A key added there does not reach the page.
- Each result's own `assumptions` block is walked generically, and every string in it is printed verbatim. That block is a trust boundary, not a filter.

**`--proxy` validation.** `--proxy` must have a ticker shape: letters, digits, `.`, `^` or `-`, 1-12 characters. Anything else exits 2 before any network call. The error never repeats back what was typed; it names the field, the shape it wants, and the length of what was given.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad input | Show `error`. For `fund.py`, follow the "`fund.py` exits 2" case in Steps. |
| 4 | Credentials missing | Show `error`. |
| 5 | Data-source error | Follow the "exit 5" case in Steps. |
| 6 | Python dependencies missing | Show `error`. |

## Steps

A usual question about one bond or fund runs the matching "earns if held" case, then the market and history case, then the page case. Add the other cases when the request calls for them.

**What a fund earns if held**

1. Run `fund.py SYMBOL`.
2. Add `horizon_years` to that JSON.
3. Pipe it into `horizon.py`.
4. If the user gave no horizon, ask for one in the same message as the first result. Do not pick one silently.
5. If the user has no view on the horizon, run it at the Macaulay duration and say that is what you did.

**What a single bond earns if held**

1. Run `horizon.py` with `coupon_rate`, `years`, `ytm` and `horizon_years`, all decimals.
2. If the user wants the price, the price map or the risk measures, also run `bond.py` on the same three figures: `coupon_rate`, `years`, `ytm`.
3. If you already hold a `bond.py` result, lift `coupon_rate` and `years` out of its `assumptions` block for `horizon.py`. Do not ask the user for them again.
4. Handle a missing horizon as in the fund case: ask in the same message as the first result, or use the Macaulay duration and say so.

**What the market assumes, and how today compares with history**

1. Run `rates.py`.
2. Set `implied_short_rate_path` beside `fomc_projection.path` and `longer_run_pct`, year by year, and name the gap. A curve above the dots means the market is paid to disagree with the committee. A curve below means the opposite.
3. Give `implied_average_short_rate_pct` as the one-number summary.
4. If the first row of the path carries the argument, say what `assumptions.note` says: the row is labelled 0–1y but is priced from the first grid point, because a forward from exactly t=0 is the curve's own constant-rate extension, not an observed forward.
5. From the same result, read `percentiles`. Each entry carries today's `value`, its `percentile`, the `median`, the FRED `series` and `history_from`.
6. Give each percentile with its history window, never the percentile alone. A 99th percentile since 2003 and a 99th percentile since 1986 are different claims.

**Whether bonds are a good deal against stocks**

Use this case for "is 4% on a Treasury better than owning the index", "what is that yield worth as a P/E", or "is the market's earnings yield higher".

1. Run `gravity.py`. Add `--tenor` or `--proxy` only when the user names one.
2. Report, in this order: the Treasury yield with its percentile against its own history; the implied P/E; the equity proxy's trailing P/E and earnings yield; the gap.
3. State the gap's sign in words: "the Treasury yields more" or "the market's earnings yield is higher".
4. Quote `equity.not_ranked_because` when you quote the equity side.
5. Carry `assumptions.fed_model_caveat` whenever you report the gap.
6. If `equity.trailing_pe` is null, quote `equity.unavailable_because` and report the Treasury side alone. Do not drop the answer.
7. Stop at the arithmetic. The gap is a measurement, never a conclusion about what to own.
8. If the script exits 2 on `--proxy`, relay the message as printed. Do not add the rejected value yourself.

**The page**

1. Collect whichever results ran into one object: `{"symbol": ..., "horizon": ..., "rates": ..., "fund": ...}`. Leave `gravity.py`'s result out.
2. Write it with the Write tool to `DIR/fixed-income.json`. DIR is the session scratchpad.
3. Run `render.py --in DIR/fixed-income.json --out DIR/fixed-income.html`.
4. Publish the HTML with the Artifact tool: icon chart, description "Fixed income — SYMBOL as of DATE". On later runs republish the same file path so the link stays stable.
5. Reply with the page format below.
6. If the Artifact tool is unavailable in the session, skip steps 1–4 and use the markdown fallback. Never both.

**`fund.py` exits 2**

The symbol is outside the seven it maps. There is no flag, stdin path or JSON input by which its `INPUT_NEEDED` figures can be handed back to it.

1. Do not retry `fund.py`.
2. Ask the user for the four figures from the fund's own fact sheet: yield to maturity, average coupon, effective duration and SEC yield.
3. Run `horizon.py` directly with a bond-like payload: `coupon_rate`, `years` from the fund's average maturity, `ytm`, `horizon_years`, all decimals.
4. If a price or risk measures are wanted, run `bond.py` on the same three figures.
5. Say which figures came from the user, because none of them was fetched.

**`rates.py`, `fund.py` or `gravity.py` exits 5**

1. Treat it as an upstream data source failing, not a bad question.
2. Say which source failed.
3. Answer what can be answered without it. `horizon.py` and `bond.py` need no network at all.

**The question is about a bill, TIPS, an FRN or a STRIP**

1. Read `references/treasuries.md`.
2. For a bill, convert the quoted discount rate to a yield and stop there.
3. Say which part you can answer and which you cannot. Do not return a number that quietly assumes the instrument is something else.

**The question is out of scope**

Say so in one line and stop.

## Reply format

The reader is a person deciding what to do with their own money, not a bond analyst.

- **Plain words first.** Say "about 7 years" for a duration, "1 point" for 100 bp, "higher than 48% of days since 1962" for a percentile. Macaulay, modified duration, basis points, forwards and the decomposition appear only when the user uses those words or asks to go deeper.
- **One decimal.** 5.6%, not 5.4934%. The JSON keeps the precision; the reply does not need it.
- **Same basis.** Treasury and fund yields are quoted compounding twice a year, and `locked_in_return_pct` is an effective annual rate. Before comparing any two, convert the quoted one: (1 + y/2)² − 1. The page does this for every bar.
- **Cash is the benchmark people have.** The 3-month bill (`benchmarks.bill_3m_pct`, converted) stands in for cash; money funds track it.

**When the page was published (the default):** the artifact link on its own line, then these, in this order, and nothing else.

1. **The short answer.** One sentence: held `horizon_years` years, SYMBOL works out to about `locked_in_return_pct`% a year at today's prices, N points more (or less) a year than cash in a 3-month bill (converted rate).
2. **If rates rise 1 point today.** One sentence from the `delta_yield_bp: 100` scenario: the price drops `immediate_price_change_pct`% at once; held to the horizon it earns `annualised_pct`% a year instead. Add whether the lines in `value_paths` meet before the horizon (the drop is earned back after about the duration) or not (a holder selling at the horizon is still behind).
3. **Against history.** One line: the 10-year Treasury yield's rank in words with its window, then whichever other entry in `percentiles` sits furthest from the middle, in words.
4. **Bonds against stocks.** Only on a run where `gravity.py` ran: its three figures and two disclosures, immediately before Flags.
5. **Flags.** In plain words, or "None".
   - A non-empty `warnings` array from `fund.py` is a flag: name each missing input and the figures that are unavailable because of it.
   - A `gap_bp` outside the band `assumptions.gap_expectation` states is a flag.
6. One closing sentence that these are general information at the stated assumptions, not financial, tax, or legal advice.

The page carries the rate-move chart, the three yields, the market-implied path against the Fed's, the decomposition, the durations and every assumption. Do not repeat them in the reply. If the user asks for one, read it from the JSON and answer in the same plain register.

**Markdown fallback (only when the Artifact tool is unavailable):** the same sections in the same order, plus:

- The three yields with their one-line meanings.
- Only if the user asked to go deeper: the implied path against `fomc_projection`; the three durations labelled separately; and the yield decomposition as treasury-equivalent + blended spread − expense ratio = calculated, beside the published figure, with the `circularity_note` in full directly underneath it.

## Rules

- **Never present a fair value, a target price, or a cheap/expensive verdict for a bond or a bond fund.**
- Whenever a calculated yield appears beside a published one, the `circularity_note` goes with it, in full, in the same place.
- A percentile describes where today sits against history. Never present it as a call or a forecast.
- Never present either side of the `gravity.py` comparison as cheap, expensive, or a fair value, and never read the gap as a signal about what to own.
- Every number comes from the scripts.
- When a fund's yields come up, surface all three together with one line each, in the order distribution yield, SEC yield, yield to maturity.
- Report a null as unavailable, never as zero and never as a blank.
- Present `locked_in_return_pct` and the quoted yield to maturity as one yield in two conventions, never as two yields. Never explain the difference as the price converging on face value: the figure does not move with the horizon.
- Quote `spread_pct` for the input in front of you. Never give a general "at most X" bound.
- When the published effective duration and the horizon figure both appear, say plainly that they answer different questions and that the horizon figure is a single-bond approximation. Never present it as more precise than that.
- Put nothing in a result's `assumptions` block that you would not publish.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- Only explain financial concepts when the user asks for an explanation.
