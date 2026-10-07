# Deep picker mode — design

## Intent

**What the user said.** The stock screener leans on financial formulas. The user wants a deep picker mode that finds the best stock opportunities with more than financials:

- Financials are used for quick filtering, mainly to drop badly managed firms.
- AI judgement scans the news and takes the temperature of each industry and sector: likely growth, the top players, and sentiment.
- The mode is aggressive and detailed, like deep valuation.
- The final stage runs deep valuation on a handful of stocks. Only stocks without significant downside price risk are surfaced.

**Agreed decisions.**

- **Search:** top-down and bottom-up, then merged (option C). An industry scan and the existing financial screen run side by side. Their candidates are merged, and every candidate passes a lenient financial health check.
- **Final gate:** rule B.
  - Every deep-valuation scenario earns at least 0% a year over the 5-year horizon, dividends included.
  - The central (first) scenario earns at least 10% a year. Both bars are adjustable.
  - A finalist whose scenarios all sit above the price passes as `pass_flagged`. This signals a likely missing downside case, and the page says so.
- **Orchestration:** `SKILL.md` instructions dispatch Agent-tool subagents, as deep valuation does. Scripts cover only the deterministic parts.
- **Pipeline:** setup → industry scan ∥ financial screen → merge + health check → quick reads → deep valuation of 3–5 finalists → gate + page.

**Success criteria.**

- A run on real data ends with:
  - a page with the picks that passed gate B, or a plain "none passed"
  - the near-misses, each with the test it failed
  - an industry map with dated evidence
  - candidate cards with scores and reasons
- Each finalist links to its deep-valuation page.
- The existing screen, look-back and funnel keep working unchanged. All tests pass.

## Out of scope

- Automatic reruns and tracking picks over time
- Options or short ideas
- Changes to deep valuation itself
- A probability on any pick

## Components

### 1. `screen.py --symbols` and the `health` preset

**`--symbols SYM,SYM`** (repeatable, case-insensitive):

- It restricts the universe to those tickers after `build_companies`.
- With `--symbols`, the output adds `checked` and `not_found`:
  - `checked` is one row per requested ticker found in EDGAR: `{"ticker", "name", "passed": bool, "failed": [criterion, ...], "financial": bool}`.
  - `not_found` lists the requested tickers with no EDGAR filer.
- Banks, insurers and lenders keep `financial: true` and fail with `financial_filer`. Their health is judged in the quick read instead.
- `--symbols` with `--exclude-held` is allowed. Pricing works as usual, but `health` has no price tests.

**Preset `health`** in `screen_math.PRESETS` is a floor, not a ranking:

```python
"health": {
    "min_revenue": 250e6,
    "min_revenue_cagr": -0.05,
    "min_f_score": 4,
    "max_share_growth": 0.05,
    "max_net_debt_to_ebit": 4.0,
    "min_fcf_margin": 0.0,
    "rank_by": "f_score",
}
```

`rank_by: "f_score"` must be a supported ranking. If it is not, add it: highest first.

### 2. `skills/stock-screener/scripts/gate.py`

A pure stdin → stdout script. It exits 2 with `{"error"}` on invalid input.

**Input:**

```json
{"hurdle": 0.10, "floor": 0.0,
 "finalists": [{"symbol": "ACME", "price": 50.0, "page": "https://…",
                "model": <model.py output>, "returns": <returns.py output>}]}
```

**Per finalist:**

- `central` is the first scenario in `model.scenarios`. Its `irr` comes from `returns`, matched by name.
- `worst` is the scenario with the lowest `irr`.
- A scenario with a null `irr` counts as a failure: "return could not be computed".
- `checks`:
  - `worst_ok`: worst irr ≥ floor
  - `central_ok`: central irr ≥ hurdle
  - `all_above_price`: every scenario's `value_per_share` > price
- `verdict`:
  - `fail` if either check is false
  - otherwise `pass_flagged` if `all_above_price`
  - otherwise `pass`
- `reasons` lists plain sentences:
  - "Worst scenario 'X' loses 2.5% a year."
  - "Central scenario earns 7.9% a year, below the 10.0% hurdle."
  - "Every scenario is worth more than the price; a downside case may be missing."
- `implied` is echoed from `model.implied` when present.

**Output:**

```json
{"hurdle", "floor",
 "results": [{"symbol", "price", "verdict", "central": {"name", "irr", "value_per_share"},
              "worst": {"name", "irr", "value_per_share"}, "checks", "reasons", "page", "implied"}],
 "counts": {"pass", "pass_flagged", "fail"}}
```

- `results` are sorted pass first, then `pass_flagged`, then `fail`. Within a group they are sorted by central irr, highest first.
- **Validation:** `hurdle` and `floor` are finite numbers above −1. `finalists` is a non-empty list. Each finalist needs `symbol`, a positive `price`, `model.scenarios` and `returns.scenarios`.

### 3. `skills/stock-screener/scripts/render_pick.py`

It builds the page with `page.render`, in the same style as `render_deep.py`.

**Input** (`pick.json` in the run folder):

```json
{"as_of": "2026-10-05", "profile": "value · years · moderate",
 "gate": <gate.py output>,
 "funnel": [{"stage": "Industries scanned", "count": 40}, ...],
 "industries": [{"sector", "industry", "verdict": "favored|neutral|unfavored", "contrarian": bool,
                 "temperature": "one sentence", "growth": "dated outlook", "sentiment": "one sentence",
                 "leaders": [{"ticker", "name", "trend": "gaining|steady|losing"}],
                 "evidence": [{"claim", "source", "date"}]}],
 "candidates": [{"ticker", "name", "industry", "origin": "industry|screen|both", "held": bool,
                 "scores": {"quality", "direction", "tailwind", "value"},   # 1-5
                 "reasons": {"quality", "direction", "tailwind", "value"},
                 "missing": "what the market may be missing", "bad_pick": "what would make this a bad pick",
                 "health": "passed|failed: criterion|financial (judged in quick read)", "finalist": bool}],
 "picks": {"<SYMBOL>": {"thesis": "one sentence", "bad_pick": "one sentence"}},
 "missing_roles": [...], "notes": [...]}
```

**Page, in order:**

1. **Picks.**
   - One card per `pass` / `pass_flagged` result: ticker, central and worst annual return, value range, thesis, "what would make this a bad pick", and a link to the deep-valuation page.
   - A `pass_flagged` card shows its warning line.
   - If there are no passes, the card says "No finalist passed the downside gate" and points to the near-misses.
2. **Near-misses.** One row per `fail`, with its reasons and a link.
3. **Funnel.** The stage counts as a bar list.
4. **Industry map.**
   - Rows are grouped favored / contrarian / neutral / unfavored.
   - Each row shows industry, temperature and leaders, and opens to growth, sentiment and dated evidence.
5. **Candidates.** A sortable table: ticker, industry, origin, the four scores, total, health and finalist mark. Each row opens to the reasons, "missing" and "bad pick".
6. **Flags.** From `missing_roles` and `notes`.

**Validation (exit 2):**

- `gate` is missing.
- An industry verdict is not in the three values.
- A score is outside 1–5.
- An evidence claim has no source or date.
- A `picks` key does not match a passing gate result.

**It prints** `{"out", "title", "picks", "near_misses", "industries", "candidates", "flags"}`.

### 4. Role briefs: `skills/stock-screener/references/picker-roles.md`

The `## Shared rules` section is the same as deep valuation's:

- dated sources
- skepticism of popular coverage
- a source arguing the other side
- "gone" threats treated as beliefs
- a five-to-ten-year look-back
- files kept inside the run folder (`DIR/pick-DATE/`) under names starting with the role
- the search-budget note
- no buy, sell or hold language

**Roles:**

| Role | Output | Holds |
|---|---|---|
| Industry scanner (×3, about 4 sectors each) | `industries/<group>.json` and `.md` | For each industry with meaningful size: temperature (dated growth outlook, cycle position, pricing power, policy, structural threats), sentiment and valuation against its own 5–10-year range, the top 3–5 leaders with share trend, the verdict with 2–3 deciding reasons, and the contrarian mark when the industry is out of favour but its fundamentals are improving. |
| Quick reader (about 5 companies each) | `cards/<TICKER>.json` | Competitive position and moat evidence, the fundamental trend over the last 4 quarters, the guidance track record, filing red flags (`filing.py --search` for going concern, material weakness, restat), insider activity, sentiment (background only), 12-month catalysts, and quick-mode value and 5-year return (`inputs.py`, `dcf.py`, `returns.py` convergence). Then the four 1–5 scores with one-line reasons, "missing", "bad pick", and the health judgement for a financial filer (book value growth, ROE, capital ratios). |

The sector groups for the three scanners:

- Technology, Communication Services, Consumer Discretionary, Consumer Staples
- Health Care, Financials, Real Estate, Utilities
- Industrials, Energy, Materials

### 5. `SKILL.md` changes

- The description gains "deep picks" and "best opportunities", staying within 260 characters.
- Background gains:
  - a modes table: the funnel stays as is, and "deep picker" is triggered by "deep pick", "best opportunities", "find me the best stocks", "deep screen"
  - the run folder layout
  - `gate.py` and `render_pick.py`
- **Steps: a new `Deep picker` case.**
  1. Check EDGAR. If it is not set up, stop and offer the funnel.
  2. Make the run folder. Get held symbols and sector weights (portfolio-snapshot) when a brokerage is connected. Note the profile, and any theme or sector limits the person gives.
  3. Tell the person the run has started, with its rough size: about 50–70 subagents for 5 finalists, about half that for 3.
  4. Start the industry scan and the financial screen in parallel.
     - The industry scan is 3 Industry scanner agents.
     - The screen is `screen.py` with the preset matching the profile (value → `value` then `quality`; growth → `garp`), run once each.
  5. Merge:
     - the leaders of favored and contrarian industries
     - screen survivors whose industry is not unfavored
     - drop duplicates, about 20–40 names
     - mark held names
  6. Run `screen.py --symbols … --preset health --no-price`. Drop failures and note why. Keep financial filers for the quick read's judgement.
  7. Dispatch Quick reader agents with about 5 companies each, two to three at a time.
  8. Rank by the four scores with judgement, and pick 3–5 finalists (default 4):
     - at least one contrarian when one survives
     - at most 2 from one industry
     - the person's held names allowed, but marked
  9. Run deep valuation (the valuation skill's Deep steps) on the finalists, two or three at a time. Each gets its own `deep-SYMBOL` folder and page.
  10. Run `gate.py` on the finalists' outputs, setting `hurdle` and `floor` in its input when the person changed them.
  11. Write `pick.json`, run `render_pick.py`, publish (icon search, description "Deep picks as of DATE"), and reply.
- **Reply format, deep picker:**
  1. the link
  2. a picks table: ticker, central and worst return a year, one-line thesis, and a link to the deep page
  3. near-misses with reasons
  4. one line on the industry picture
  5. flags
  6. the general-information sentence
- **Rules:**
  - Industry verdicts and candidate scores are judgement backed by dated evidence. They are not forecasts.
  - Surface only gate passes as picks. Never call a pick a recommendation.
  - Name a `pass_flagged` warning beside the pick every time.

## Error handling

| Situation | Behaviour |
|---|---|
| EDGAR not configured | Stop before dispatch and offer the existing funnel |
| A scanner or quick reader fails | Name it in `missing_roles`; the run continues |
| A candidate has no EDGAR filer (`not_found`) | It skips the health check, is judged in the quick read, and is noted |
| A deep valuation fails | That finalist goes into `notes` as not valued; the next-ranked candidate is valued when time allows |
| No finalist passes | The page and reply say so plainly and show the near-misses |

## Testing

**`tests/test_scripts_stock_screener.py`:**

- `--symbols` restricts the universe and reports `checked` and `not_found`.
- A financial filer reports `financial: true`.
- The `health` preset passes GROW and SLOW and fails a company with heavy dilution.
- `rank_by` `f_score` works.

**`tests/test_scripts_stock_picker.py` (new):**

- `gate.py`:
  - pass, `pass_flagged`, fail on the worst scenario, fail on the central scenario
  - a null irr fails
  - sorting
  - custom hurdle and floor
  - each validation error
- `render_pick.py`:
  - every section renders
  - the no-passes page
  - each validation error
  - the sample fixture (`docs/samples/stock-picker.json`) is current
  - the Chrome page audit (`assert_page_help`)

**`tests/test_skills_structure.py`:** register `stock-screener/references/picker-roles.md`.

**Manual:** one full deep-picker run on real data before the branch is called done.

## Docs

- `CHANGELOG.md`: an Unreleased entry
- `docs/scripts.md`: `gate.py`, `render_pick.py`, `--symbols`, `health`
- `docs/examples.md`: one deep-picker prompt
