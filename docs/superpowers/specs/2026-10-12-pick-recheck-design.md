# Pick re-check: track picks against the valuation they were picked on

Date: 2026-10-12. Status: approved (the person approved all decisions up front).

## Intent

**What the person asked for**
- A way to re-evaluate stocks they picked with the stock picker.
- For deep picks, the preferred way is to track against the earlier deep valuation instead of re-running it end to end. The re-check asks which scenario the actuals are following.
- Light (funnel) picks get a lighter re-check of the same kind.
- A re-check produces a scorecard plus a status. When the actuals fall outside every scenario, the status says a full deep valuation is due. (Option B.)
- A pick becomes due for a re-check when its earnings are out, or when its price has moved 15% or more since the last check. (Option C.) The person starts every check.

**Constraints from the repo**
- Numbers come from scripts. Skills never say buy, sell or hold. The status describes the *valuation*, not the trade: on track, shifting, outside (re-run the deep valuation).
- Deep-valuation and picker run folders live only in the session scratchpad, and macOS cleans them up. The six current picks (LDOS, ADBE, INTU, DECK, PRDO, FHI) have already lost their folders. Each published deep page embeds its full `page.json` as `window.DATA`: model output with every scenario's per-segment, per-year revenue and EBIT, returns, and the ledger. That makes the published page a recovery source.

**Success**
- Saving a pick keeps everything a re-check needs in the plugin data dir, so it outlives the session.
- `check SYM` answers, from EDGAR and a price quote alone, which scenario the latest reported quarters are tracking. It also says whether any scenario still fits, and what return the central case now implies at today's price. No subagents are needed.
- The session-start hook says when a pick is due, without network calls.
- The six current picks can be loaded from their published pages.

## Design

### Store (`<data_dir>/picks.json` + `<data_dir>/picks/`)

`picks.json`:

```
{"picks": [{"symbol", "kind": "deep"|"light", "added", "added_price", "source",
            "baseline": "picks/SYM-YYYY-MM-DD.json", "thesis", "next_earnings",
            "checks": [{"date", "price", "period_end", "status", "nearest", "rerun_deep", "reasons"}]}]}
```

- One entry per symbol. Saving again replaces the baseline and keeps `checks`. A new deep valuation starts a new baseline.
- The baseline file holds the full deep `page.json` (or `window.DATA` pulled from a page's HTML). It also holds `model.json` when it is available, which gives the exact base-year `revenue0`. A light baseline holds `fair_values` (bear/base/bull), `preset`, `thesis`, and `metrics_at_pick`, measured by the script from EDGAR at save time.

### Scripts (stock-screener skill)

**`track_math.py`** holds the pure math, stdin to stdout, in the style of `gate.py`. It handles two modes.

*Deep mode* takes the baseline model output, the actuals and a price.

1. **Time alignment.**
   - Year 0 is the last fiscal year reported on or before the baseline's `as_of`, with its actual revenue R0 and operating income E0.
   - Scenario year *t* is fiscal year *t* after it.
   - The latest TTM window ends *f* years after the base year end, so it covers (f−1, f].
   - The expected TTM figure in each scenario is the overlap-weighted sum of that scenario's yearly figures. Year 0 uses the actuals.
2. **Scale.**
   - Scenario levels are segment sums. When `model.json` is present, they are scaled by R0 / Σrevenue0, so eliminations and unallocated revenue do not register as a miss. A gap over 5% is flagged `BASE_MISMATCH`.
   - Without `model.json`, the scale is 1: the segment sums are assumed to match the reported totals. The result is flagged `APPROX_BASE`.
3. **Metrics.**
   - For operating segments: TTM revenue growth over R0, and TTM operating margin. The scenario's EBIT is the sum of operating EBIT less cost segments grossed up for tax.
   - For a model made only of residual-income segments: TTM ROE against each scenario's ROE path.
   - Optional segment actuals (`segments: {name: {revenue, ebit}}`, read from the 10-Q segment note) get the same treatment per segment.
4. **Distance.** For each scenario, d = |Δgrowth| / 2pt + |Δmargin| / 0.5pt. ROE uses 1pt.
   - `nearest` is the scenario with the smallest d.
   - `envelope`: for each metric, the actual is compared with the min and max across scenarios. A miss beyond the tolerance on either side is `outside`, whether below or above.
5. **Status.**
   - `no_new_data`: f < 0.2. No quarter has been reported since the base year.
   - `outside`: outside the envelope on any metric. Sets `rerun_deep: true`.
   - `shifting`: the nearest scenario is not the central one, and d_central − d_nearest ≥ 1.
   - Otherwise `on_track`.
   - `rerun_deep` is also set when the baseline is more than 15 months old (`STALE_BASELINE`). It is also set when an evidence item contradicts a high-stakes ledger belief (`HIGH_STAKES_CONTRADICTED`).
6. **Price.**
   - Price against the scenario values: which value it sits nearest, and whether it is below every scenario or above every one.
   - The annualized return per scenario at today's price. This reruns `valuation/scripts/returns.py`'s math on the baseline's `returns_input` with the new price.
7. **Watch list for evidence.** The scenarios' `must_be_true` items for the central and nearest scenarios. Also every ledger belief with high or medium stakes whose verdict is not settled, or whose `if_true` cuts against the central case. The skill hands this list to the model so it can look for dated evidence, capped at 4 web searches.

*Light mode* compares two things: `metrics_at_pick` (TTM revenue growth and operating margin) against the same metrics now, and the price against the bear/base/bull fair values.
- `weakening` when growth fell more than 5 points or the margin fell more than 2 points. This sets `deep_review: true`, which means running a deep valuation is the next step.
- Otherwise `on_track`, or `no_new_data` when no quarter has been reported since the pick.

**`picks.py`** handles storage and I/O, following `watchlist.py`'s subcommand pattern.
- `save-deep SYM (--case DIR | --page page.html) [--thesis T] [--added-price P] [--date D]`: copies the baseline in. Taking HTML covers recovery from a published page.
- `save-light SYM --in light.json`: takes `{thesis, preset, fair_values, added_price?}`, then fetches `metrics_at_pick` from EDGAR.
- `list`, `remove SYM`.
- `check SYM [--segments F] [--evidence F] [--record]`: builds the actuals from EDGAR companyfacts, using fundamental-research's `fundamentals.py` helpers for quarterly series and annual facts, and gets the price from `market.quote`. It runs `track_math` and, with `--record`, appends the check and refreshes `next_earnings`.
- `due [--move 0.15]`: does network work for every pick. A pick is due when a 10-Q or 10-K was filed after its last check (from EDGAR submissions), or when its price moved by `--move` or more since the last check (or since it was added).
- `summary`: plain text for the hook, with no network calls. A pick is due when its stored `next_earnings` date has passed since the last check, or when the price in `watchlist-last-check.json` moved 15% or more from the last checked price. With no picks it prints nothing.

### Hook

`hooks/picks-summary.sh` follows `watchlist-summary.sh` and runs `picks.py summary`. It is registered in `hooks/hooks.json`.

### Skill wiring

- **stock-screener SKILL.md**:
  - Background: a "Re-checking picks" part.
  - Scripts: the new commands.
  - Steps: a new case, "**The person asks how their picks are doing, or the session says a pick is due**". Its steps are: run `check`, look for dated evidence on the watch items within 4 searches, rerun with `--evidence --record`, then reply.
  - Deep-picker step 13 saves each passing pick with `save-deep`.
  - Funnel step 5 offers `save-light`.
  - Reply format: the re-check format.
- **valuation SKILL.md** deep step 13: when the person holds or tracks the company, saves the baseline with `picks.py save-deep --case`.
- **Recovery**: for a pick whose run folder is gone, read its published deep page with the Artifact tool and run `save-deep --page`.

### Errors

- Exit 2 for bad input, an unknown pick, or a page with no `window.DATA`.
- Exit 4 `SKILL_MISSING` when fundamental-research is absent.
- Exit 5 for EDGAR or Yahoo errors.
- A missing operating-income tag degrades to a revenue-only comparison, flagged `NO_OPERATING_INCOME`.

### Testing

- `tests/test_scripts_track_math.py` covers the pure math: alignment weights, scaling, nearest, envelope, status precedence, ROE mode, light mode, and returns at a new price.
- `tests/test_scripts_picks.py` covers the store, save-deep from a case folder and from HTML, check with stubbed EDGAR facts and quote, due, and summary.
- The structure tests must keep passing.

## Out of scope

- A published page for re-checks. The reply goes in chat.
- Automatic scheduled runs. The person starts each check.
- Segment actuals parsed from XBRL dimensions. The model reads the segment note when it matters.
