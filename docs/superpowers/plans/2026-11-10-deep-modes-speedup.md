# Deep Valuation and Deep Picker Speed-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the deep valuation and deep picker's web searches, tool calls and wall-clock time by moving mechanical work into scripts, with research quality held or improved.

**Architecture:** One "research pack" builder gathers everything the scripts can fetch for a company (filings text, releases, analyst consensus, quick value, red-flag passages) into files before any subagent starts, so subagents read instead of fetch. Small coordinator scripts replace hand-written JSON (budget, model runs, page assembly, pool merge, gate and pick assembly). The skill steps and role briefs are rewritten around them, with lower search caps and one thread round by default.

**Tech Stack:** Python 3 scripts under `skills/*/scripts/` printing one JSON object, shared code in `lib/second_opinion/`, pytest. No new dependencies.

**Spec:** This document's "Measurements" and "Design decisions" sections are the spec. There is no separate design file.

## Measurements (five past runs, profiled from session transcripts)

- A deep valuation takes 19–28 minutes; a picker with three finalists 59–117 minutes.
- Script execution is 13–21% of subagent time. Each tool call costs about 12 s of agent time, and a subagent makes 25–58 of them; 13–20 per agent are grep/sed/inline Python slicing script output, plus `--help` and role-file re-reads.
- One company's 10-K is hit by 21–38 `filing.py` calls from 6–9 agents.
- Searches: 17–30 per valuation. 32% look for the company's own results and guidance history (in `earnings.py`), 22% for analyst targets and consensus (in Yahoo; 74 of 94 quick-reader queries), 2% macro (in FRED).
- Thread round 2 ran in 5 of 7 valuations and moved a scenario over 5% once, after a round 1 that moved it 11%. Round 3 ran once and moved 1.6%. The red team moved the central value 5–7% in 5 of 6.
- The coordinator spends 7–8 minutes per valuation on serial work: baseline scripts, `budget.json` updates (50 Bash calls in one picker), hand-writing `model.json`, `page.json`, `gate.json`, `pick.json`. Context compaction hit the picker coordinator at the gate step twice.
- Quick readers were dispatched in waves of three, so the second wave waited on the first.

## Design decisions

1. **Research pack.** `lib/second_opinion/pack.py` builds a folder of files for one company at level `card` (picker quick read) or `deep` (valuation). It ends with `INDEX.md`: what each file holds, the headline figures, and the resolved script commands, so no subagent calls `--help`.
2. **Analyst consensus from Yahoo.** `market.analyst_view()` and an `analysts` block in `sentiment.py` replace the analyst-target searches.
3. **Coordinator scripts.** `deep_prep.py`, `budget.py`, `deep_run.py`, `render_deep.py --case` (valuation); `pick_prep.py`, `prospects.py`, `pool.py`, `cards.py`, `pick_assemble.py` (picker).
4. **Thread rounds.** One round of up to four threads. A second round of up to two threads runs only when `deep_run.py` reports `round2_due` (a scenario moved more than 10% in round 1). No third round. The Red team stays, after the threads.
5. **Search caps.**

   | Role | Old | New |
   |---|---|---|
   | Forensic accountant | 3 | 1 |
   | Management claims | 6 | 3 |
   | Industry and news | 8 (4 in the picker) | 6 (4 in the picker) |
   | Segment economics | 2 | 1 |
   | Thread deep-dive | 2 each | 2 each |
   | Red team | 3 | 2 |
   | Industry scanner | 8 | 6 |
   | Quick reader | 2 per company | 1 per company |

   Budget plans (`budget.py`): `valuation` 25 (21 + 4 reserved for round 2), `valuation-picker` 23, `picker-3` 117 (18 + 30 + 69), `picker-4` 140, `picker-5` 143 (no round-2 reserve: 19 each).
6. **Dispatch.** All quick readers go out in one message. Deep valuations still run two or three at a time, one coordinator per company.
7. **Not changed:** `model.py`, `returns.py`, `gate.py`, `render_pick.py` math and contracts; the gate rule; the ledger rules; the pick store; every compliance rule.

## Global Constraints

- Every script prints one JSON object on stdout, uses the exit codes in `docs/scripts.md` (2 bad input, 4 config/skill missing, 5 data source, 6 deps), has a `main(argv: list[str] | None = None) -> int`, a docstring that is its contract, and is executable (`chmod +x`).
- Scripts insert `lib` on `sys.path` the way `skills/valuation/scripts/intrinsic-inputs.py` does, and use `second_opinion.output` and `second_opinion.errors` like their neighbours.
- A source that fails degrades to a named entry in `missing` or a flag. Only an unknown ticker (2) or EDGAR not configured (4) stops a prep script.
- No network in tests: monkeypatch the gatherers, as existing tests do (`tests/scripts_util.py`: `load_script`, `run_json`).
- No personal identifiers in any request. SEC data only through `lib/second_opinion/edgar.py` and the fundamental-research scripts.
- SKILL.md files obey `docs/skill-style.md` and `tests/test_skills_structure.py` (500 body lines, no prose line over 400 characters, commands in one fenced block, no dates).
- Run tests with `python3 -m pytest tests -q`. One failure predates this work and is not to be fixed here: `tests/test_scripts_picks.py::test_check_deep_records_and_moves_next_earnings`.
- No git commits; the work stays in the working tree for review.

## Review Focus

- A pack source down (Yahoo 429, a filing with no Item 8, a foreign filer with no 10-K): the pack still builds, `missing` names it, `INDEX.md` says so.
- A bank, insurer, REIT or utility: `quick_value` carries the business-type yardstick, never a cash-flow DCF value.
- `deep_run.py` on the first run (no previous run): `max_move` null, `round2_due` false.
- `pick_assemble.py` when a finalist's folder has no `model.out.json`: exit 2 naming the finalist, nothing half-written.
- Dollar amounts in text (`$100M`) survive every assembly script unchanged.

---

### Task 1: Analyst consensus

**Files:** Modify `lib/second_opinion/market.py`, `skills/stock-screener/scripts/sentiment.py`. Test: `tests/test_market.py`, `tests/test_scripts_sentiment.py`.

**Produces:** `market.analyst_view(symbol: str) -> dict`:

```
{"symbol", "as_of", "source": "yahoo",
 "targets": {"current", "low", "mean", "median", "high"} | None,
 "recommendations": {"strong_buy", "buy", "hold", "sell", "strong_sell", "count"} | None,   # current month
 "actions": [{"date", "firm", "action", "from_grade", "to_grade", "target", "prior_target"}],  # last 180 days, newest first, at most 10
 "estimates": {"eps": [{"period", "avg", "low", "high", "year_ago", "analysts", "growth"}], "revenue": [...]} | None}
```

It never raises: each part that fails is `None` or `[]`. `sentiment.py` adds `"analysts": <analyst_view>` per symbol and an `ANALYSTS_UNAVAILABLE` flag when every part is empty.

- [ ] Tests: a fake ticker with all four yfinance attributes maps to the shape above; a ticker whose attributes raise gives all-empty parts and no exception; `sentiment.py` output carries `analysts` and the flag.
- [ ] Implement from yfinance `analyst_price_targets`, `recommendations_summary` (row `0m`), `upgrades_downgrades`, `earnings_estimate`, `revenue_estimate`. Zero targets become `None`.
- [ ] Run both test files.

### Task 2: Research pack, `deep_prep.py`, `budget.py`

**Files:** Create `lib/second_opinion/pack.py`, `skills/valuation/scripts/deep_prep.py`, `skills/valuation/scripts/budget.py`, `tests/test_pack.py`, `tests/test_scripts_deep_prep.py`, `tests/test_scripts_budget.py`.

**Consumes:** Task 1's `analysts` block inside `sentiment.py` output.

**Produces:**

`pack.build(symbol: str, out_dir: Path, level: str = "card", workers: int = 4) -> dict` runs the existing scripts as subprocesses of `sys.executable` (thread pool; each result written to `out_dir`), and returns and writes `pack.json`:

```
{"symbol", "as_of", "level", "dir",
 "files": {"<name>": {"path", "ok", "error"?}},
 "missing": ["<name>", ...],
 "summary": {"company", "price", "market_cap", "business_type", "flags": [codes from inputs.py and intrinsic.py],
             "quick_value": {"basis": "dcf"|"normalized"|"book_value"|"reit"|"utility"|None,
                             "bear", "base", "bull", "irr_5y", "note"},
             "analysts": {"target_mean", "count"}, "red_flag_hits": {"<term>": n},
             "insiders": {"buys", "sells"}}}
```

Files, by level:

| File | Command | Level |
|---|---|---|
| `edgar.json` | `edgar.py SYM --years 10 --quarters 12 --form4 5` | both |
| `fundamentals.json` | valuation `fundamentals.py SYM` | both |
| `inputs.json` | `inputs.py SYM` | both |
| `intrinsic-inputs.json`, `intrinsic.json` | `intrinsic-inputs.py SYM`, piped into `intrinsic.py` | both |
| `quick_value.json` | `dcf.py` on the three `dcf_scenarios`, then `returns.py` convergence (the SKILL's Quick step 7 inputs). `CYCLICAL`: basis `normalized` from `dcf.py` on `normalized.dcf_input_mid_cycle`. A `DCF_NOT_MEANINGFUL_FOR_…` flag or `NEGATIVE_FCF`: no DCF value; `basis` names the yardstick and the block copies `book_value_tests`, `reit_tests` or `utility_tests`. | both |
| `sentiment.json` | `sentiment.py SYM` | both |
| `earnings.json`, `releases/<filing date>.txt` | `earnings.py SYM --last 8` (card) or `--last 12 --max-chars 40000` (deep); one text file per release | both |
| `redflags.json` | `filing.py SYM --search T` for "going concern", "material weakness", "restat", "related part"; deep adds "capitalized", "change in accounting" | both |
| `filings/10k-items.json` | `filing.py SYM` (the Item list) | deep |
| `filings/10k-item1.txt`, `-item1a.txt`, `-item7.txt`, `-item8.txt`, `-item9a.txt` | `filing.py SYM --item N --max-chars 600000`, text only | deep |
| `filings/10k-item1a-diff.txt`, `filings/10k-item8-diff.txt` | `--item N --diff` | deep |
| `filings/10q-item2.txt` | `filing.py SYM --form 10-Q --item 2 --max-chars 200000` | deep |
| `filings/segment-note.txt` | `filing.py SYM --search segment --context 3000` | deep |
| `forensic-checks.json` | computed from `edgar.json`'s annual table: net income against operating cash flow by year, receivables (DSO) and inventory (DIO) trend against revenue growth, stock pay as a share of revenue and of operating cash flow, each with `finding: bool` under the thresholds in `references/deep-roles.md`'s Forensic table | deep |
| `INDEX.md` | each file with one line and its size, the summary figures, `missing`, and a "Script commands" section with `sys.executable` and absolute script paths for `edgar.py`, `filing.py` (all flags), `earnings.py`, `fundamentals.py`, `sentiment.py`, `inputs.py`, `dcf.py`, `returns.py`, `model.py` | both |

`deep_prep.py SYMBOL --case DIR [--plan valuation|valuation-picker] [--industry FILE ...]`: makes `DIR` with `baseline/`, `research/`, `threads/`, `custom/`; builds the deep pack into `baseline/`; copies each `--industry` file to `baseline/picker-industry-<name>`; initialises `budget.json`; writes `model.skeleton.json`; prints `{"symbol", "case", "summary", "missing", "budget", "index": "<path to INDEX.md>", "skeleton": "<path>", "flags"}`. Exit 2 unknown ticker, 4 EDGAR not configured.

`model.skeleton.json`: `symbol`, `price`, `shares_outstanding` (millions), `years` 10, `horizon` 5, `base_discount_rate` (inputs `wacc`), `tax_rate`, `cost_of_debt`, `payout` 1, `annual_dilution` (EDGAR `diluted_shares_cagr`, 0 when null), `hurdle` 0.10, `claims` {}, `segments` [], `scenarios` [], plus `_notes`: a list of strings giving each filled value's source, the `ERP_DEFAULT`/`ERP_STALE` flags when present, and what the analyst still fills (segments, claims from `research/segments.md`, scenarios, sensitivity). Money in millions.

`budget.py DIR init --plan NAME [--force]`, `budget.py DIR add ROLE=N [ROLE=N ...]`, `budget.py DIR` (status). Plans and caps:

| Plan | Caps | Total |
|---|---|---|
| `valuation` | forensic 1, claims 3, industry 6, segments 1, threads 8, threads_round2 4, red_team 2 | 25 |
| `valuation-picker` | as above with industry 4 | 23 |
| `picker-3` | scanners 18, quick_reads 30, valuations 69 | 117 |
| `picker-4` | scanners 18, quick_reads 30, valuations 92 | 140 |
| `picker-5` | scanners 18, quick_reads 30, valuations 95 | 143 |

Every command prints `{"plan", "total", "caps", "used", "remaining", "threads_allowed": min(4, remaining // 2), "flags"}`; flags `ROLE_OVER_CAP`, `OVER_BUDGET`. An unknown role is exit 2. `init` on an existing file is exit 2 without `--force`.

- [ ] Tests (`test_pack.py`, runner monkeypatched to canned JSON): a deep pack writes every table row and an `INDEX.md` naming them; a runner that fails for `earnings.py` leaves `missing == ["earnings.json"]` and still writes the index; `inputs.json` with `DCF_NOT_MEANINGFUL_FOR_FINANCIALS` gives `quick_value.basis == "book_value"` and `base is None`; `CYCLICAL` gives `basis == "normalized"`; a release text containing `$100M` is written unchanged.
- [ ] Tests (`test_scripts_deep_prep.py`, `pack.build` monkeypatched): folders exist; skeleton holds the inputs' `wacc` as `base_discount_rate` and shares in millions; `--plan valuation-picker` sets industry cap 4; `--industry` file is copied.
- [ ] Tests (`test_scripts_budget.py`): init totals match the table; `add claims=2 industry=7` on `valuation` flags `ROLE_OVER_CAP` and `remaining == 16`; `threads_allowed` is 4 then falls with `remaining`; unknown role exit 2; second `init` exit 2.
- [ ] Implement; `chmod +x`; run the three test files.

### Task 3: `deep_run.py` and `render_deep.py --case`

**Files:** Create `skills/valuation/scripts/deep_run.py`, `tests/test_scripts_deep_run.py`. Modify `skills/valuation/scripts/render_deep.py`, `tests/test_scripts_valuation_deep.py`.

**Produces:**

`deep_run.py --case DIR [--label TEXT]`: reads `DIR/model.json`, drops top-level keys starting with `_`, runs `model.py` then `returns.py` on its `returns_input` (import the modules; capture their stdout), writes `model.out.json` and `returns.out.json`, appends to `runs.json`, and prints:

```
{"run": n, "label", "price",
 "scenarios": [{"name", "value_per_share", "value_ex_premiums", "upside", "irr", "change_vs_prev"}],
 "max_move": largest |change_vs_prev| or null, "round2_due": max_move > 0.10,
 "position": "brackets_price" | "all_above_price" | "all_below_price" | null,
 "implied", "flags": [model and returns flags]}
```

`change_vs_prev` matches scenarios by name against the previous run; null on the first run or for a new scenario. `model.py` exit 2 passes through as exit 2 with its `error`, and nothing is written.

`render_deep.py --case DIR`: reads `model.out.json`, `returns.out.json`, `ledger.json` (a list, or an object with `ledger`) and `blocks.json` (`{"blocks", "as_of"?, "notes"?, "missing_roles"?}`), writes `DIR/page.json` in the existing input shape (symbol and price from the model output) and `DIR/page.html`, and prints its usual result. `--in/--out` keeps working. A missing `model.out.json` or `blocks.json` is exit 2 naming the file.

- [ ] Tests: first run has `max_move is None`, `round2_due is False`, files written; a second run after raising a margin 15 points reports `round2_due True` and per-scenario `change_vs_prev`; `_notes` in `model.json` is ignored; invalid model exit 2 and no `model.out.json`; scenarios all above price give `all_above_price`.
- [ ] Tests: `--case` builds `page.json` whose `model` equals `model.out.json`, keeps a ledger takeaway containing `$2.9B` verbatim in `page.json`, and exits 2 without `blocks.json`.
- [ ] Implement; `chmod +x`; run both test files.

### Task 4: `pick_prep.py` and `prospects.py`

**Files:** Create `skills/stock-screener/scripts/pick_prep.py`, `skills/stock-screener/scripts/prospects.py`, `tests/test_scripts_pick_prep.py`, `tests/test_scripts_prospects.py`. Modify `lib/second_opinion/fred.py` (series names only).

**Consumes:** `budget.py` (Task 2) by its command line: `budget.py DIR init --plan picker-N`. Until Task 2 lands, call it through one function that tests monkeypatch.

**Produces:**

`pick_prep.py --run DIR --profile value|growth [--held SYM,SYM] [--finalists 3|4|5]`: makes `DIR` with `context/`, `screen/`, `industries/`, `cards/`; writes `context/macro.json` and `context/macro.md` (its own date on top; one dated line per FRED series: DGS10, DGS2, FEDFUNDS, BAMLC0A4CBBBEY, MORTGAGE30US, UNRATE, DCOILWTICO, DHHNGSP as latest values; CPIAUCSL, RSAFS, IPMAN as year-over-year change from `fred.observations`; a failed series is left out and flagged `MACRO_SERIES_UNAVAILABLE`); runs the screens (`value`: `value`, `quality`; `growth`: `garp`; plus the first preset with `--set min_revenue=1.5e8 --set min_market_cap=3e8` as `smallcap`), first one alone to warm the frames cache, then the rest in parallel, each written to `screen/<name>.json`; initialises the budget; prints `{"run", "macro": {"lines", "missing"}, "screens": {name: {"survivors", "top": [first 15 tickers], "flags"}}, "budget", "flags"}`. Exit 4 when EDGAR is not configured; a screen that fails is flagged `SCREEN_FAILED` and the others kept.

`prospects.py SYM[,SYM...] [--out FILE]` (at most 25, in parallel): per symbol, from `edgar.py SYM --years 5 --quarters 12` and `market.company_info`:

```
{"ticker", "name", "market_cap", "tests_passed": n,
 "tests": {"trajectory": {"pass", "figures": {"quarters_up_of_8", "ttm_revenue_growth", "net_margin_ttm", "net_margin_prior_ttm"}},
           "cash": {"pass", "figures": {"fcf_positive_years_of_4", "dividends_covered"}},
           "price": {"pass", "figures": {"pe", "forward_pe", "fcf_yield", "change_12m", "pct_of_52w_high"}},
           "overlooked": {"pass", "figures": {"analyst_count", "institutional_ownership", "change_12m"}}},
 "size_ok": market_cap >= 3e8, "why": "<one line of the passing tests with figures>", "flags"}
```

Rules: trajectory passes with year-over-year revenue up in at least 5 of the last 8 quarters and TTM net margin not below the prior TTM; cash with free cash flow positive in at least 3 of 4 years and covering dividends in the latest; price with FCF yield ≥ 6% or P/E ≤ 15 (else null: the scanner judges it against history and peers); overlooked with analyst count ≤ 8, institutional ownership < 60%, or a 12-month change below −20%. A figure that cannot be computed is null and its test null. Output `{"as_of", "prospects": [...], "not_found": [...], "flags"}`.

- [ ] Tests (`pick_prep`): fake FRED and a fake screen runner; `macro.md` starts with the date and has a line containing `DGS10` and its observation date; a failing series is flagged and absent; `value` profile writes `value.json`, `quality.json`, `smallcap.json`; one failing screen leaves the other files and a `SCREEN_FAILED` flag.
- [ ] Tests (`prospects`): a fixture with 6 of 8 quarters up, 4 of 4 FCF years, P/E 11, 3 analysts gives `tests_passed == 4` and a `why` naming each; P/E 30 with FCF yield 2% gives `price.pass is None`; an unknown ticker lands in `not_found`; 26 symbols exit 2.
- [ ] Implement; `chmod +x`; run both test files.

### Task 5: `pool.py`, `cards.py`, `pick_assemble.py`

**Files:** Create `skills/stock-screener/scripts/pool.py`, `cards.py`, `pick_assemble.py`, and `tests/test_scripts_pick_pool.py`, `tests/test_scripts_pick_cards.py`, `tests/test_scripts_pick_assemble.py`.

**Consumes:** `pack.build` (Task 2); `model.out.json`, `returns.out.json` (Task 3); `screen/*.json`, `industries/*.json` (Task 4 and the scanners); `gate.py` and `render_pick.py` unchanged.

**Produces:**

`pool.py --run DIR [--held SYM,SYM] [--max 40]`: merges every industry's `prospects` and every `screen/*.json` survivor (not `health.json`); a leader enters only when also a prospect or survivor; dedupes by ticker; sets `origin` (`industry`, `screen`, `both`), `held`, `industry`, `sector`, `industry_verdict`, `contrarian`; trims to `--max` keeping `both` first, then prospects and screen survivors alternately by their order, never on the verdict; runs `screen.py --symbols … --preset health --no-price [--held …]` into `screen/health.json`; sets `health` (`passed`, `failed`, `financial`, `not_found`, `incomplete`, or `judge_in_quick_read` for a failed name whose sector is Financials) and `failed_tests`; writes `pool.json` `{"names", "dropped", "counts", "batches"}` where `dropped` holds health failures with their tests and `batches` groups the kept names five at a time, same industry together. Prints counts and batches.

`cards.py --run DIR [--symbols SYM,SYM] [--workers 4]`: for each kept pool name builds the `card` pack into `cards/<TICKER>/` and writes `cards/<TICKER>.data.json`: the pool row plus `quick_value`, `red_flags` (the inputs flags `SHARE_CLASSES_COMBINED`, `CORPORATE_ACTION_SUSPECTED`, `LARGE_MINORITY_INTEREST`, `CYCLICAL`, `CYCLE_BASE_SPLIT` that fired, and each red-flag term with hits), `direction` (`quarters_up_of_8`, `ttm_revenue_growth`), `analysts`, `insiders`, `value_hint` (5 at `irr_5y` ≥ 15%, 4 at ≥ 10%, 3 at ≥ 6%, 2 at ≥ 0, else 1; null without an IRR) and `index` (the pack's `INDEX.md`). Prints one row per name and `missing` per name. A name whose pack fails entirely is listed in `failed`, never an exit.

`pick_assemble.py --run DIR --finalists SYM=URL[,SYM=URL...] [--cases DIR] [--hurdle R] [--floor R] [--notes FILE] [--as-of DATE]`: `--cases` defaults to the run folder's parent; reads each `deep-SYM/model.out.json` and `returns.out.json`; writes `gate.json`, runs `gate.py`'s logic, writes its output; builds `pick.json` for `render_pick.py`: `funnel` (industries scanned, screen survivors, merged pool, health check passed, quick reads, finalists, picks), `industries` (all `industries/*.json` joined), `candidates` (each `cards/<T>.json` with `held` from the pool and `finalist`), `picks` and `missing_roles`, `notes`, `profile` from the notes file (`{"picks": {SYM: {"thesis", "bad_pick"}}, "missing_roles", "notes", "profile"}`; a `picks` entry for a finalist that failed the gate is dropped and named in `notes`), plus a note with searches used against the budget from `budget.json`; runs `render_pick.py`'s render into `page.html`. Prints `{"out", "gate": counts, "picks", "near_misses", "save_commands": ["picks.py save-deep SYM --case … --thesis … --source URL", ...], "flags"}`. A finalist with no `model.out.json`, or a URL that is not https, is exit 2 before anything is written.

- [ ] Tests (`pool`): two industry files and two screens with one overlap give `origin == "both"` for it; a leader that is not a prospect stays out; 50 names trim to 40 with every `both` kept; a failed Financials name is `judge_in_quick_read`, a failed industrial is in `dropped`; batches hold at most five.
- [ ] Tests (`cards`, `pack.build` monkeypatched): `value_hint` thresholds at 0.15, 0.10, 0.06, 0; a pack with no IRR gives null; a failing pack lands in `failed`.
- [ ] Tests (`assemble`): three finalists from fixture model and returns outputs produce a page and the same verdicts as `gate.py` run directly; a thesis containing `$100M` appears verbatim in `pick.json`; a missing `model.out.json` exits 2 and leaves no `gate.json`; an http link exits 2; a thesis for a gate failure is dropped with a note.
- [ ] Implement; `chmod +x`; run the three test files.

### Task 6: Skills, role briefs, docs, version

**Files:** Modify `skills/valuation/SKILL.md`, `skills/valuation/references/deep-roles.md`, `skills/stock-screener/SKILL.md`, `skills/stock-screener/references/picker-roles.md`, `docs/scripts.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json` (1.7.0), and wherever the version or the run sizes are repeated (`grep -rn "1\.6\.0\|30 to 40 subagents\|about 160"`).

- [ ] Valuation Deep steps become: `deep_prep.py` (replaces steps 1–3's scripts and the budget file; exit 4 keeps its meaning) → dispatch the four round-1 roles (prompt: brief path and two sections, case folder, symbol, date, cap, and "start from `baseline/INDEX.md`") → `budget.py add` once per round → ledger → fill `model.skeleton.json` into `model.json` (the existing modelling rules kept verbatim) → `deep_run.py` → one thread round of up to `threads_allowed` threads (one a blind-spot thread) → `deep_run.py`; a second round of up to two threads only when `round2_due` → Red team → `deep_run.py` → write `blocks.json` → `render_deep.py --case` → publish → save → reply. Background's case-folder table, scripts block, script table and the "ten to fifteen" size line (now eight to eleven subagents, about 25 searches) are updated.
- [ ] `deep-roles.md`: Shared rules open with "Read `baseline/INDEX.md` first", a table of which pack files serve which role, "do not run `--help`; the commands are in the index", and "run `filing.py` only for what the pack lacks (older filings, competitors, another search term)". Each role's cap and starting files follow the table in Design decisions 5; Forensic starts from `forensic-checks.json` and `redflags.json`; Claims from `releases/`; Industry from `sentiment.json` (news and `analysts`); Segments from `filings/segment-note.txt` and `10k-item8.txt`; analyst targets and consensus come from `sentiment.json`, never a search.
- [ ] Picker steps become: EDGAR check and holdings read → `pick_prep.py` → three scanners (told to test names with `prospects.py`, cap 6) → `pool.py` → `cards.py` → every quick reader in one message, a batch from `pool.json` each, cap 1 per company, reading `cards/<T>.data.json` and its index → finalists → deep valuations with `--plan valuation-picker` and `--industry` → `picks-notes.json` → `pick_assemble.py` → publish → its `save_commands` → reply. The budget table, the size line (about 25 to 35 subagents, about 117 planned searches) and the run-folder table are updated.
- [ ] `picker-roles.md`: scanner prospects use `prospects.py` (the four tests' thresholds stay as the brief's, with the script's rules named); quick reader steps 2, 4, 5, 6 and 8 read the data file instead of running scripts, and the card JSON shape is unchanged.
- [ ] `python3 -m pytest tests/test_skills_structure.py tests/test_version.py tests/test_readme_samples.py -q` passes.

### Task 7: Review and live check

- [ ] Whole-change code review by a fresh reviewer against this plan's Review Focus.
- [ ] Full suite: `python3 -m pytest tests -q` (only the known failure).
- [ ] Live: `deep_prep.py` on one industrial and one bank, `prospects.py` on five tickers, `pick_prep.py` into a scratch folder; fix what real data breaks.
