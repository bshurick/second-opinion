# Pick Re-check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save each pick's valuation baseline durably, and re-check it against new filings and today's price. The re-check says which scenario the company is tracking, and when a full deep valuation is due again.

**Architecture:**
- `track_math.py` holds the pure math (stdin to stdout JSON, like `gate.py`).
- `picks.py` holds the store and the I/O: EDGAR companyfacts through fundamental-research's `fundamentals.py` helpers, and `market.quote`.
- A SessionStart hook prints the due picks with no network calls.
- The SKILL.md files wire it into the deep picker, the funnel and deep valuation.

**Tech Stack:** Python 3.10+ stdlib, the existing `second_opinion` lib, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-pick-recheck-design.md`

## Global Constraints

- Scripts print one JSON object. Exit codes are 0, 2 (bad input), 4 (`SKILL_MISSING`), 5 (data source) and 6 (dependencies). `summary` prints plain text and always exits 0.
- No buy, sell or hold language. Statuses are `on_track`, `shifting`, `outside` and `no_new_data` (deep), and `on_track`, `weakening` and `no_new_data` (light).
- Tolerances: growth 0.02, margin 0.005, ROE 0.01. A gap of 1.0 in d separates shifting from on track. f below 0.2 means no new data. The baseline goes stale after 15 months. The price trigger is 0.15. Light weakening is a growth drop over 0.05 or a margin drop over 0.02.
- The data dir is `config.data_dir()`, overridden in tests by `SECOND_OPINION_DATA`.
- New scripts are executable (`chmod +x`). SKILL.md keeps the tested layout (`docs/skill-style.md`).

## Review Focus

1. A pick whose company has not filed a quarter since the base year: `no_new_data`, never a false `outside`.
2. A bank or insurer model with only `residual_income` segments: compared on ROE, with no crash on a missing operating income.
3. A filer with no `OperatingIncomeLoss` tag: revenue-only comparison plus the `NO_OPERATING_INCOME` flag.
4. A page HTML without `window.DATA`, or with `</script>` inside a string: exit 2 with a clear error.
5. `summary` with no `picks.json`, or a pick missing from `watchlist-last-check.json`: silent or partial output, never a traceback.

---

### Task 1: `track_math.py` deep mode

**Files:** Create `skills/stock-screener/scripts/track_math.py`. Test: `tests/test_scripts_track_math.py`.

**Interfaces (Produces):**
- `run_track(params: dict) -> dict`, with `params = {"mode": "deep", "as_of": "YYYY-MM-DD", "baseline": {"as_of", "model": <model.py output>, "model_input"?: <model.json>, "ledger"?: [...]}, "actuals": {"base": {"period_end", "revenue", "operating_income"?, "equity"?}, "ttm": {"period_end", "revenue", "operating_income"?, "net_income"?, "equity_start"?}, "segments"?: {name: {"revenue", "ebit"?}}}, "price", "evidence"?: [{"belief", "finding": "supports"|"contradicts", "claim", "source", "date"}]}`.
- It returns `{"mode", "status", "nearest", "central", "rerun_deep", "reasons", "elapsed_years", "metrics": {name: {"actual", "expected": {scenario: v}, "envelope": [lo, hi], "position": "inside"|"below"|"above"}}, "scenarios": [{"name", "distance", "expected": {...}, "value_per_share", "irr"}], "segments"?, "price": {...}, "watch": [...], "evidence", "flags"}`.
- Helpers: `window_weights(f: float) -> dict[int, float]` and `expected_ttm(yearly: list[float], y0: float, f: float) -> float`.

**Tests:**
- Window weights: f=1.0 gives {1: 1.0}, f=0.5 gives {0: 0.5, 1: 0.5}, f=1.25 gives {1: 0.75, 2: 0.25}.
- `on_track` when the actuals equal the central path.
- `shifting` when the actuals equal the second scenario.
- `outside` (below, and above) with `rerun_deep`.
- `no_new_data` when f < 0.2.
- A cost segment lowers expected EBIT by cost / (1 − tax).
- With `model_input`, the scale applies, and `BASE_MISMATCH` fires above 5%. Without it, `APPROX_BASE` fires.
- ROE mode for a residual-income-only model.
- `NO_OPERATING_INCOME` gives a revenue-only result.
- `STALE_BASELINE` after 15 months, and `HIGH_STAKES_CONTRADICTED` from evidence.
- `irr` at the new price matches `returns.py` run with that price.
- The watch list holds the central and nearest `must_be_true` items, plus the high and medium unsettled beliefs.
- Exit 2 on a missing model.

- [ ] Write the tests, run them and see them fail. Implement. Run again and see them pass. Commit.

### Task 2: `track_math.py` light mode

**Interfaces:** `params = {"mode": "light", "as_of", "baseline": {"fair_values": {"bear", "base", "bull"}, "metrics_at_pick": {"period_end", "revenue_growth", "operating_margin"}}, "actuals": {"period_end", "revenue_growth", "operating_margin"}, "price"}`. It returns `{"mode", "status", "deep_review", "reasons", "metrics": {name: {"at_pick", "now", "change"}}, "price": {"price", "position": "below_bear"|"bear_base"|"base_bull"|"above_bull", "fair_values"}, "flags"}`.

**Tests:**
- `on_track`.
- `weakening` from growth, and from margin.
- `no_new_data` when the period is the same.
- Each price position.
- A missing margin gives a growth-only result plus a flag.

- [ ] Write the tests, see them fail, implement, see them pass. Commit.

### Task 3: `picks.py` store and saves

**Files:** Create `skills/stock-screener/scripts/picks.py`. Test: `tests/test_scripts_picks.py`.

**Interfaces:**
- Commands: `save-deep SYM (--case DIR | --page FILE) [--thesis T] [--added-price P] [--date D]`, `save-light SYM --in FILE`, `list` and `remove SYM`.
- `page_data(html: str) -> dict` pulls out `window.DATA`. It parses the JSON with `json.JSONDecoder.raw_decode` from the `=` onward, so a `</script>` inside a string does not break it.
- `edgar_actuals(symbol: str, as_of: str | None) -> dict` (Task 4) supplies `metrics_at_pick` for a light save.

**Tests:**
- `save-deep --case` copies `page.json` and `model.json`.
- `--page` extracts from HTML, and HTML without the data exits 2.
- Saving again keeps the checks.
- `list` and `remove`.
- `save-light` stores the metrics, with the EDGAR stub patched.

- [ ] Write the tests, see them fail, implement, see them pass. Commit.

### Task 4: `picks.py check`, `due`, `summary` and the hook

**Interfaces:**
- `edgar_actuals(symbol, base_as_of)` returns `{"base": {...}, "ttm": {...}, "latest_filed", "light": {"period_end", "revenue_growth", "operating_margin"}}`. It takes the base year as the latest annual fact filed on or before `base_as_of`, and the TTM as the four latest discrete quarters (`fundamentals._quarterly_series`).
- `check SYM [--segments F] [--evidence F] [--record]`.
- `due [--move R]` returns `{"due": [{"symbol", "reasons"}], "not_due": [...]}`.
- `summary` prints plain text.

**Tests (EDGAR and quote stubbed):**
- `check` deep and light. `--record` appends the check and sets `next_earnings`.
- `due` by a new filing, and by a price move.
- `summary` with no file prints nothing. `summary` marks a pick due by an earnings date and by a price taken from `watchlist-last-check.json`.
- The hook script is listed in `hooks.json`.

- [ ] Write the tests, see them fail, implement, see them pass. Add `hooks/picks-summary.sh` and its `hooks.json` entry. Commit.

### Task 5: Skill wiring and docs

**Files:**
- Modify `skills/stock-screener/SKILL.md` (Background, Scripts, Steps, Reply format) and `skills/valuation/SKILL.md` (deep step 13).
- Modify `docs/scripts.md` if it lists scripts, and `CHANGELOG.md`.

- [ ] Edit, then run `python -m pytest tests -q`. Every test passes. Commit.

### Task 6: Recover the current picks

- [ ] Find the deep pages for LDOS, ADBE, INTU, DECK, PRDO and FHI with the Artifact tool. Save each one's HTML and run `save-deep --page`. Then run `check` on each and report.
