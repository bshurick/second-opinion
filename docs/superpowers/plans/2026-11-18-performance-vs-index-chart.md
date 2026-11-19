# Performance vs. Index Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Performance vs. the market" line chart (time-weighted total return of the combined portfolio or one account vs. SPY, QQQ, DIA) to the portfolio summary page.

**Architecture:** A pure math script `history.py` rebuilds end-of-day holdings backward from today's positions through the ledger, values them, and chains daily time-weighted returns. A fetching script `history_report.py` tops up the ledger, reads live accounts through the router, downloads prices and splits in one batch, and calls `history.run_history`. `render_brief.py --history` embeds the result and draws it with the existing `F.lines` helper.

**Tech Stack:** Python 3 stdlib, `second_opinion` lib (router, ledger, market, proxies, output, page), yfinance via `market`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-performance-vs-index-chart-design.md`

## Global Constraints

- Benchmarks are exactly `SPY` ("S&P 500"), `QQQ` ("Nasdaq"), `DIA` ("Dow"), from `adj_close`.
- Portfolio valued from `close` (split-adjusted, not dividend-adjusted); units kept in today's split terms.
- Daily return: `r(d) = (V(d) − F(d)) / V(d−1) − 1`, flows at end of day, deposits positive. Combined = sum V and F across included accounts, then chain.
- Never draw a guess: reconciliation failures start that account's series the day after the break, with a `HISTORY_BREAK` flag.
- Accounts with under 30 days of history are left out of the combined line (`SHORT_HISTORY`).
- Unpriced non-proxy holding: carried at last trade/broker price with `UNPRICED_HOLDING` if under 1% of the account that day, else a break.
- Negative-units tolerance: break when units < 0 and |units| > 1e-6 and > 0.1% of that symbol's max held.
- Cash break: cash < −5% of account value on a non-margin account (`account_type != "margin"`).
- Cash-like (`proxies.is_cash_like(symbol, name)`) valued at $1.00/unit and not rolled through trades.
- Unlisted funds: proxy from `proxies.lookthrough_proxy_for(name)`; series containing one gets `estimated: true` and a `PROXY_PRICED` flag.
- Exit codes 0/2/4/5/6 via `output.run`; ETRADE_REAUTH / `--partial` exactly as `performance_report.py`.
- `render_brief.py` output without `--history` must be byte-identical to today's.
- `brief.py` and the check-in path are not changed.
- Ranges on the page: 1M, 3M, YTD, 1Y, All; every line rebased to 0% at the range start.

## Review Focus

1. **Ledger with only CSV rows under a free-form account label:** expect that account excluded with `NO_HISTORY` and an `UNASSIGNED_ROWS` count, not a crash. Test: Task 3 `test_unassigned_rows_flagged_and_ignored`.
2. **A day with a large deposit and a market drop together:** the return must reflect only the drop. Test: Task 1 `test_deposit_same_day_as_drop`.
3. **First trading day of the range is a holiday for one symbol (missing close):** carry the last close forward, no break. Test: Task 1 `test_missing_close_carries_forward`.
4. **E*Trade login expired:** `history_report.py` exits 4 with ETRADE_REAUTH; with `--partial`, E*Trade accounts excluded with `BROKER_UNAVAILABLE`. Test: Task 4 `test_partial_excludes_etrade_accounts`.
5. **Yahoo benchmark download fails while portfolio prices succeed:** chart still renders portfolio lines; `BENCHMARK_UNAVAILABLE` flag. Test: Task 4 `test_benchmark_fetch_failure_degrades`.

---

### Task 1: `history.py` core rebuild and time-weighted return

**Files:**
- Create: `skills/portfolio-analysis/scripts/history.py`
- Test: `tests/test_scripts_history.py`

**Interfaces:**
- Produces: `run_history(params: dict) -> dict` (input/output contracts exactly as the spec's "Scripts" section, plus input keys `aliases: {ledger_id: live_id}` and per-account `account_type`, per-position `name`, `price`; output series carry `estimated: bool`). `main() -> None` reads stdin, writes stdout, exit 2 with `{"error"}` on bad input, mirroring `performance.py`.
- Internal helpers later tasks extend: `_rollback(account, txns, splits) -> dict[str, DayHolding]` where `DayHolding = {"units": dict[str, float], "cash": float, "flow": float}` keyed by ISO date; `_value(day_holding, prices_on_day) -> float`; `_chain(values: list[tuple[str, float, float]]) -> list[list]` taking (date, value, flow) and returning `[[date, index, value]]`.

- [ ] **Step 1: Write failing tests** in `tests/test_scripts_history.py` (load with `load_script("portfolio-analysis/scripts/history.py")`; build a tiny helper `_params(accounts, txns, prices)` with `as_of="2026-01-09"`, trading days 2026-01-05..09):
  - `test_buys_and_sells_only`: today 10 AAPL, cash 0; ledger BUY 10 @100 on 01-06 (amount −1000), DEPOSIT 1000 on 01-05. Closes 100,100,110,110,121. Assert combined points' index on 01-09 == pytest.approx(1.21) and value == 1210.
  - `test_dividend_raises_return`: same holdings, flat close 100, DIVIDEND +10 on 01-08, today cash 10. Assert final index == approx(1.01).
  - `test_deposit_does_not_move_return`: flat price, DEPOSIT 500 on 01-07 (today cash 500). Assert every index == approx(1.0).
  - `test_withdrawal_does_not_move_return`: WITHDRAWAL −200 on 01-07. Index all 1.0.
  - `test_deposit_same_day_as_drop`: deposit 1000 on 01-07 while price drops 10% that day → r(01-07) == approx(−0.10 × share of stock in V(d−1)) computed in the test from the fixture.
  - `test_transfer_in_shares_is_external_flow`: TRANSFER_IN 5 AAPL on 01-07, flat price 100 → index 1.0 throughout, value jumps by 500.
  - `test_missing_close_carries_forward`: AAPL missing 01-06 close → no flag, 01-06 valued at 01-05 close.
  - `test_combined_sums_values_and_flows`: two accounts, one +10%, other flat, equal size → combined final index approx(1.05); combined `start` = later of the two account starts.
  - `test_benchmark_from_adj_close`: SPY adj_close 400→440 → benchmark points start 1.0, end approx(1.10); labels "S&P 500", "Nasdaq", "Dow".
  - `test_bad_input_exits_2` via `main()` with stdin `{}`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_history.py -q`; expect failures (module missing).
- [ ] **Step 3: Implement** `run_history` with `_rollback`, `_value`, `_chain`, benchmarks. Trading-day calendar = union of dates across all supplied price rows from the earliest ledger date to `as_of`. Undo table exactly as spec "Method". OTHER rows: undo `amount` if present, count in `OTHER_TYPES`. Module docstring states the contracts (repo convention).
- [ ] **Step 4: Run** the test file; expect all PASS.
- [ ] **Step 5: Commit** `git commit -m "history.py: rebuild daily holdings from the ledger and chain time-weighted returns"`

### Task 2: Splits and reconciliation breaks

**Files:**
- Modify: `skills/portfolio-analysis/scripts/history.py`
- Test: `tests/test_scripts_history.py`

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces: `_split_factor(symbol, txn_date, splits) -> float`; `_detect_split_convention(symbol, txns, splits, today_units) -> Literal["as_traded", "adjusted", "ambiguous"]`; output flags `HISTORY_BREAK` (message names account, date, symbol, reason), `SHORT_HISTORY`, `UNPRICED_HOLDING`.

- [ ] **Step 1: Write failing tests:**
  - `test_forward_split_as_traded`: BUY 10 pre-split, 2:1 SPLIT row (ratio 2.0), today 20 units, closes already split-adjusted → no break, flat index.
  - `test_forward_split_already_adjusted`: BUY recorded as 20 pre-split, same split → convention "adjusted", no break.
  - `test_reverse_split_detected_each_way`: 1:10 (ratio 0.1), both recordings → correct convention chosen, no break, values continuous across the split date.
  - `test_split_ratio_from_yahoo_when_row_missing`: no SPLIT row, `splits` input has it → handled.
  - `test_ambiguous_split_breaks`: inconsistent units → series `start` is day after split date, `HISTORY_BREAK` flag with reason "split".
  - `test_missing_sell_breaks`: today 0 AAPL, ledger BUY 10 on 01-07 and no later SELL (the sell is missing) → rolling back gives −10 units before 01-07 → series `start` is 01-08, `HISTORY_BREAK` reason "negative units".
  - `test_unpriced_small_holding_carried`: unpriced symbol worth 0.5% → `UNPRICED_HOLDING`, no break.
  - `test_unpriced_large_holding_breaks`: worth 5% → break, reason "no price".
  - `test_negative_cash_breaks_non_margin` and `test_negative_cash_ok_on_margin`.
  - `test_short_history_excluded_from_combined`: account with 20 days → absent from combined, listed in `excluded` with `SHORT_HISTORY`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement.** Convention detection per split: simulate rollback of that symbol under each reading; a reading fits when units never break the negative-units tolerance and, if the SPLIT row has `units`, the unit change across the split date equals it within 1e-6 relative. Exactly one fit → use it; else ambiguous → break.
- [ ] **Step 4: Run**; expect PASS (Task 1 tests still pass).
- [ ] **Step 5: Commit** `git commit -m "history.py: detect split recording per split and stop a series at any unreconciled day"`

### Task 3: Cash-like, proxy-priced funds, account aliases

**Files:**
- Modify: `skills/portfolio-analysis/scripts/history.py`
- Test: `tests/test_scripts_history.py`

**Interfaces:**
- Consumes: `proxies.is_cash_like(symbol, name)`, `proxies.lookthrough_proxy_for(name)` from `lib/second_opinion/proxies.py`.
- Produces: input key `proxies: {symbol: proxy_symbol}` (resolved by Task 4) and `aliases`; `_synthetic_prices(today_price, proxy_rows) -> list[{"date","close"}]` (today's broker price scaled back by proxy `adj_close` daily ratios); flags `PROXY_PRICED`, `UNASSIGNED_ROWS`, `NO_HISTORY`.

- [ ] **Step 1: Write failing tests:**
  - `test_money_market_valued_as_cash`: SPAXX 1000 units, no ledger rows for it, no price → valued 1000 every day, no break.
  - `test_proxy_fund_synthetic_history`: ONN5 (name "VANG INST 500 IDX TR", price 113.48), proxies `{"ONN5": "VOO"}`, VOO adj_close +10% over window → ONN5 synthetic close on day 1 == approx(113.48/1.10); series `estimated` true; `PROXY_PRICED` flag names ONN5 and VOO.
  - `test_aliases_fold_and_dedupe`: same BUY under twin id and live id, aliases map twin→live → counted once.
  - `test_unassigned_rows_flagged_and_ignored`: rows with account_id "my-csv" matching nothing → ignored, `UNASSIGNED_ROWS` message has count.
  - `test_account_without_ledger_rows_no_history`: excluded with `NO_HISTORY`, message contains `statement-import`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full `tests/test_scripts_history.py`; PASS.
- [ ] **Step 5: Commit** `git commit -m "history.py: value money markets as cash, price unlisted funds from their proxy ETF, fold twin account ids"`

### Task 4: `history_report.py` fetcher

**Files:**
- Create: `skills/portfolio-analysis/scripts/history_report.py`
- Modify: `lib/second_opinion/market.py` (add `split_histories`)
- Test: `tests/test_scripts_history_report.py`

**Interfaces:**
- Consumes: `history.run_history`; `router.load()`, `hub.partial`, `hub.list_accounts()`, `hub.get_portfolio(aid)["positions"]`, `hub.get_balance(aid)["balances"]`, `hub.list_transactions(aid, start, end, count)`, `hub.shadowed` (entries `{snaptrade_account_id, direct_account_id}`), `hub.unavailable_flags()`; `ledger.load/merge/save`; `normalize.run_normalize` (import as sync-broker does); `summary._symbol_and_name(pos)`; `market.close_histories(symbols, start)`; `proxies.lookthrough_proxy_for`.
- Produces: CLI `history_report.py [--since YYYY-MM-DD] [--partial]`; `build(argv_ns) -> dict` returning `run_history`'s output plus `sources`; `market.split_histories(symbols: list[str], start: str) -> dict[str, list[{"date": str, "ratio": float}]]` (one batched `actions=True` download, mirroring `dividend_histories`).

- [ ] **Step 1: Write failing tests** (monkeypatch `router.load` with `tests/fakes.fake_hub`/a stub hub, `market.close_histories`, `market.split_histories`, `SECOND_OPINION_DATA` to `tmp_path`):
  - `test_top_up_merges_new_activity_before_rebuild`: ledger newest row 01-05; hub returns a BUY dated 01-08 → saved ledger contains it, and `list_transactions` was called with `start="2026-01-06"`.
  - `test_empty_ledger_flags`: no ledger and hub returns nothing → exit 0, `LEDGER_EMPTY` flag naming `statement-import`.
  - `test_aliases_built_from_shadowed`: `hub.shadowed=[{"snaptrade_account_id":"s1","direct_account_id":"d1"}]` → payload `aliases == {"s1":"d1"}`.
  - `test_proxy_map_resolved_from_names`: position named "VG IS TOT BD MKT IDX" → `proxies` payload maps it to "BND" and BND is in the price download.
  - `test_partial_excludes_etrade_accounts`: hub raising ETRADE_REAUTH → exit 4 without `--partial`; with it, `BROKER_UNAVAILABLE` flag and that account in `excluded`.
  - `test_benchmark_fetch_failure_degrades`: `close_histories` returns no SPY/QQQ/DIA rows → exit 0, `BENCHMARK_UNAVAILABLE`, portfolio series present.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_history_report.py -q`; FAIL.
- [ ] **Step 3: Implement.** Order: parse args → `router.load()` (partial) → `list_accounts()` → top-up per account from day after its newest ledger row (skip accounts with no rows) → `ledger.save` → positions/balances (cash via the same balance parsing `snapshot.py`/`summary.py` use) → symbol set (held today ∪ ledger symbols in window ∪ proxies ∪ benchmarks) → one `close_histories` from the oldest ledger date (or `--since`) → `split_histories` → `run_history`. Module docstring in the `performance_report.py` style.
- [ ] **Step 4: Run** both history test files; PASS.
- [ ] **Step 5: Live smoke check** (read-only except the ledger top-up): `CLAUDE_PLUGIN_ROOT=$PWD python3 skills/portfolio-analysis/scripts/history_report.py --partial | python3 -c "import json,sys;d=json.load(sys.stdin);print([s['key'] for s in d['series']], d['flags'])"`. Expected on this machine today: `LEDGER_EMPTY` (no ledger yet), exit 0. Report the output.
- [ ] **Step 6: Commit** `git commit -m "history_report.py: top up the ledger, fetch prices once, and build the performance history"`

### Task 5: Chart card on the summary page

**Files:**
- Modify: `skills/portfolio-analysis/scripts/render_brief.py` (`build`, `main`, BODY, SCRIPT, help text)
- Test: `tests/test_scripts_portfolio.py` (or a new `tests/test_render_brief_history.py`)

**Interfaces:**
- Consumes: `history_report.py` output shape.
- Produces: `build(snapshot: dict, summary: dict | None = None, history: dict | None = None) -> str`; CLI flag `--history PATH`. When `history` is given, data passed to `page.render` is `{**snapshot, "history": history}`; otherwise `snapshot` unchanged.

- [ ] **Step 1: Write failing tests:**
  - `test_render_without_history_byte_identical`: `build(SNAP)` equals output of the pre-change function captured in a fixture string from `git show HEAD:...` (or compare `build(SNAP) == build(SNAP, None, None)` plus assert `"perf-card"` not in output).
  - `test_render_with_history_has_card_picker_ranges`: output contains `id="perf-card"`, `id="perf-account"`, and buttons `1M`, `3M`, `YTD`, `1Y`, `All`.
  - `test_estimated_series_labelled`: series with `estimated: true` → page script renders "estimated via"; check via `page_dom.render_and_audit` card text when Chrome is available (skip otherwise, as existing page tests do).
  - `test_history_flags_join_flags_section`.
- [ ] **Step 2: Run**; FAIL.
- [ ] **Step 3: Implement.** Card placed right after the headline tiles, titled "Performance vs. the market". Picker: "All accounts" + one option per series; excluded accounts as disabled options with the reason in `title`. Range buttons disabled beyond the data span. Draw with `F.lines(el, {series, xIsDate: true, yFmt: v => F.pct(v, 1, true), zeroLine: true})`, values `index/index_at_range_start − 1`; portfolio `F.S[0]`, SPY/QQQ/DIA `F.S[1..3]`. Summary line above: "Your portfolio +8.2% · S&P 500 +11.0% · Nasdaq … · Dow … · −2.8 pts vs. S&P 500". Add an `F.help` entry explaining time-weighted return in plain words. Merge `history.flags` into the flags list.
- [ ] **Step 4: Run** the render tests and the full suite `python3 -m pytest -q tests`; all PASS.
- [ ] **Step 5: Commit** `git commit -m "Portfolio page: performance vs. S&P 500, Nasdaq and Dow chart with account picker"`

### Task 6: Skill docs, changelog, version

**Files:**
- Modify: `skills/portfolio-analysis/SKILL.md` (Background "Script output shapes", Scripts block + table, "How is my portfolio" steps, Reply format)
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json` (1.16.0 → 1.17.0)

- [ ] **Step 1:** Add `history_report.py` / `history.py` usage lines and table rows. In the summary steps: run `history_report.py` after `snapshot.py`, write `DIR/history.json`, pass `--history DIR/history.json` to `render_brief.py`; exit 4 → existing login handoff; any other failure → render without it and note why. State check-in and daily brief do not run it. Reply format: one line with the 1Y (or All if shorter) portfolio-vs-SPY figure.
- [ ] **Step 2:** CHANGELOG `## 1.17.0` entry in the repo's existing style; bump version.
- [ ] **Step 3: Run** `python3 -m pytest -q tests`; all PASS (some tests check SKILL.md/plugin consistency).
- [ ] **Step 4: Commit** `git commit -m "Portfolio summary: document the performance chart (1.17.0)"`
