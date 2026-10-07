# Deep Picker Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the tooling bugs and search-budget problems found in the 2026-10-06 live deep-pick run, and make the central case and value obvious on the deep pages.

**Architecture:** Library fixes in `lib/second_opinion/edgar.py` (throttle, 429 retry, archive fetch); two new scripts (`fundamental-research/scripts/earnings.py`, `stock-screener/scripts/sentiment.py`); four correctness fixes in `valuation/scripts/inputs.py` (share count, minority interest, cyclicals, WACC); two new screener flags in `screen_math.py`/`screen.py`; renderer changes in `render_deep.py` and `render_pick.py`; reference and SKILL.md changes so agents fetch instead of search.

**Tech Stack:** Python 3 stdlib + yfinance (lazy), pytest; pages are self-contained HTML with inline JS (`lib/second_opinion/page.py`).

**Spec:** The Claude Doc "Deep picker: fetch instead of search" (https://claude.ai/code/artifact/7b9d4e0d-6d5f-4502-8a4a-9e9130f8bfe5), sections Ideas, Changes to the repo, Risks, Next steps, and every "Bug found during the run" / "Issue found" / "Page design issue" section.

## Global Constraints

- Run tests with `python3 -m pytest tests -q -p no:cacheprovider` from the repo root. Baseline: 2380 passed.
- Scripts print one JSON object and use the exit codes in `docs/scripts.md` (0 ok, 2 bad input, 4 config/skill missing, 5 data source error, 6 deps missing) via `second_opinion.output.run`.
- New scripts are executable (`chmod +x`), start with `#!/usr/bin/env python3` and a usage docstring, and are listed in `docs/scripts.md`.
- New reference files are registered in `REFERENCE_FILES` (and `GUARDED_REFERENCES` when the skill is verb-guarded) in `tests/test_skills_structure.py`, linked from the SKILL.md, and get a `## Contents` list when over 100 lines.
- SKILL.md bodies stay under 500 lines and keep the compliance rules verbatim; never use "recommend", "advise", "should", "suggest" about financial actions.
- No real personal data in fixtures. Never write a user's name or email into code, fixtures, docs or requests other than through `EDGAR_USER_AGENT`.
- Every flag is `{"code", "message"}` in `inputs.py`; screener company flags are bare code strings in `flags`.
- Commit after each task with a conventional message ending in the attribution lines:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. A company with **no** debt or **no** minority interest must produce exactly the same `inputs.py` output as before (no new flags, same WACC except the ERP change) — regression tests in Tasks 4-7.
2. A Yahoo `info` missing `impliedSharesOutstanding` must fall back to `sharesOutstanding` silently (Task 4).
3. EDGAR throttle must not deadlock or crash when the lock file's directory is unwritable (read-only data dir) — fall back to an in-process sleep (Task 1).
4. `render_deep.py` given a model whose first scenario has no `returns` row must still render (central return shows "—") (Task 9).
5. `earnings.py` on a company with no 8-K Item 2.02 in the recent index returns an empty `releases` list with exit 0, not an error (Task 2).

---

### Task 1: EDGAR throttle, 429 retry and archive fetch

**Files:**
- Modify: `lib/second_opinion/edgar.py` (`_fetch`, new `_throttle`, new `archive`)
- Test: `tests/test_edgar.py`

**Interfaces:**
- Produces: `edgar.archive(url: str) -> str` — fetches any `https://www.sec.gov/Archives/...` URL through the cache and throttle; raises `InvalidInput` for any other host/path. `edgar._throttle()` (internal).

- [ ] **Step 1: Write failing tests** in `tests/test_edgar.py`:

```python
def test_fetch_retries_on_429_then_succeeds(monkeypatch, tmp_path):
    from second_opinion import edgar
    calls = []
    def fake_urlopen(req, timeout=30):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        return _Resp(b'{"ok": 1}')
    monkeypatch.setattr(edgar.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(edgar.time, "sleep", lambda s: None)
    assert edgar._fetch("https://data.sec.gov/x.json", "ua") == b'{"ok": 1}'
    assert len(calls) == 3

def test_fetch_gives_up_after_retries(monkeypatch):
    ...  # always 429 -> ApiError with http_status 429 after edgar._MAX_RETRIES + 1 attempts

def test_throttle_spaces_requests(monkeypatch, tmp_path):
    # with a fake clock, two back-to-back _throttle() calls sleep at least edgar._MIN_INTERVAL in total
    ...

def test_throttle_survives_unwritable_lock_dir(monkeypatch, tmp_path):
    # point cache_dir at a path under a file (so mkdir fails); _throttle() must not raise

def test_archive_rejects_other_hosts():
    with pytest.raises(InvalidInput):
        edgar.archive("https://example.com/a.htm")
    with pytest.raises(InvalidInput):
        edgar.archive("https://data.sec.gov/submissions/CIK1.json")

def test_archive_fetches_and_caches(monkeypatch, tmp_path):
    # second call with the network stubbed to raise must return the cached text
```

(Write the elided bodies in the same style as existing tests in `tests/test_edgar.py`; reuse its fake response helper or add `_Resp` with `read()` and `headers.get()`.)

- [ ] **Step 2: Run** `python3 -m pytest tests/test_edgar.py -q -p no:cacheprovider` — new tests FAIL.

- [ ] **Step 3: Implement.**

```python
_MIN_INTERVAL = 0.125          # SEC fair-access limit is 10 requests/second; stay at 8
_MAX_RETRIES = 4               # on HTTP 429 / 503
_BACKOFF = (2, 5, 10, 20)      # seconds

def _throttle() -> None:
    """Space EDGAR requests across every process on this machine (all agents share one IP)."""
    try:
        import fcntl
        lock = cache_dir() / ".throttle"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                last = float(fh.read() or 0)
            except ValueError:
                last = 0.0
            wait = last + _MIN_INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            fh.seek(0); fh.truncate(); fh.write(repr(time.time())); fh.flush()
    except (OSError, ImportError):
        time.sleep(_MIN_INTERVAL)
```

In `_fetch`, call `_throttle()` before each attempt; on `HTTPError` with code 429 or 503 sleep `_BACKOFF[attempt]` and retry up to `_MAX_RETRIES`, then raise the existing `ApiError` (keep its message/hint, add `http_status`). Add:

```python
ARCHIVE_PREFIX = "https://www.sec.gov/Archives/edgar/data/"

def archive(url: str) -> str:
    """Any file under the SEC filing archive (an 8-K exhibit, an index.json), cached for a day."""
    if not isinstance(url, str) or not url.startswith(ARCHIVE_PREFIX):
        raise InvalidInput(f"not an SEC archive URL: {url!r} (must start with {ARCHIVE_PREFIX})")
    return document(url)
```

Update the module docstring: throttle (8/s across processes), retry on 429/503, `archive()`.

- [ ] **Step 4: Run** the edgar tests, then the full suite — PASS.
- [ ] **Step 5: Commit** `fix(edgar): throttle requests across processes and retry on 429`.

---

### Task 2: `earnings.py` — earnings releases from 8-K Item 2.02

**Files:**
- Create: `skills/fundamental-research/scripts/earnings.py` (executable)
- Modify: `skills/fundamental-research/SKILL.md` (Scripts block, script table, Background bullet), `docs/scripts.md`
- Test: `tests/test_scripts_earnings.py`

**Interfaces:**
- Consumes: `edgar.cik_for`, `edgar.submissions`, `edgar.archive` (Task 1), `filing_sections` HTML-to-text helper if present (check `skills/fundamental-research/scripts/filing_sections.py`; otherwise strip tags with `html.parser`).
- Produces: CLI `earnings.py SYMBOL [--last N] [--max-chars N]` printing `{"symbol", "cik", "as_of", "releases": [{"filing_date", "accession", "exhibit", "url", "text", "truncated"}], "flags"}`.

- [ ] **Step 1: Write failing tests** with `monkeypatch` on `edgar.submissions` (rows with `form`, `filingDate`, `accessionNumber`, `primaryDocument`, `items`) and `edgar.archive` (returns an `index.json` listing `ex99-1.htm` / `ex991.htm`, then HTML text):
  - picks only `8-K` rows whose `items` contains `2.02`, newest first, at most `--last` (default 8);
  - finds the exhibit whose name matches `ex-?99[._-]?1` (case-insensitive), falling back to the first `ex99` file; a filing without one gets `exhibit: null`, `text: null` and a flag `NO_EX99`;
  - text is tag-stripped and cut to `--max-chars` (default 15000) with `truncated: true`;
  - no Item 2.02 filings → `releases: []`, exit 0 (Review Focus 5);
  - bad symbol → exit 2; usage error → exit 2.
- [ ] **Step 2: Run** — FAIL (no such script).
- [ ] **Step 3: Implement.** Index URL: `f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/index.json"`; items are `json.loads(edgar.archive(index_url))["directory"]["item"]`. Use `argparse` with the same `_Parser` error pattern as `filing.py` (raise `InvalidInput`). Docstring explains: "Use for guidance-versus-results track records instead of web search."
- [ ] **Step 4: Run** the new tests and `tests/test_skills_structure.py` — PASS.
- [ ] **Step 5: Commit** `feat(fundamental-research): earnings.py reads earnings releases from 8-K exhibits`.

---

### Task 3: `sentiment.py` — short volume and dated news without web search

**Files:**
- Create: `skills/stock-screener/scripts/sentiment.py` (executable)
- Modify: `skills/stock-screener/SKILL.md` (Scripts block and table), `docs/scripts.md`
- Test: `tests/test_scripts_sentiment.py`

**Interfaces:**
- Consumes: `second_opinion.finra.short_volume(symbols, days)`, `second_opinion.flows.short_volume_summary(rows_by_symbol)`, `second_opinion.market.recent_news(symbol, days, limit)`.
- Produces: CLI `sentiment.py SYM[,SYM...] [--days 20] [--news-days 30] [--news 10]` printing `{"as_of", "symbols": {SYM: {"short_volume": <summary entry or null>, "news": [...]}}, "flags"}`. Note in the docstring that FINRA daily short-sale volume is not short interest.

- [ ] **Step 1: Failing tests** monkeypatching the three library functions: two symbols merged correctly; a symbol with no FINRA rows gets `short_volume: null` and flag `NO_SHORT_VOLUME`; news failure for one symbol (raise) gives `news: []` and flag `NEWS_UNAVAILABLE` without failing the run; more than 25 symbols → exit 2.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with `output.run`, `brokerage.validate_symbol` per symbol.
- [ ] **Step 4: Run** — PASS (plus structure tests).
- [ ] **Step 5: Commit** `feat(stock-screener): sentiment.py for short volume and dated news`.

---

### Task 4: `inputs.py` share count and corporate-action check

**Files:**
- Modify: `lib/second_opinion/market.py` (`company_info` adds `"implied_shares_outstanding": info.get("impliedSharesOutstanding")`), `skills/valuation/scripts/inputs.py`
- Test: `tests/test_scripts_valuation.py` (extend the `fake_yahoo` fixture to accept overrides)

**Interfaces:**
- Produces in `inputs.py` output: `assumptions.shares_outstanding = {"value", "source"}`; flags `SHARE_CLASSES_COMBINED` (info) and `CORPORATE_ACTION_SUSPECTED`.

- [ ] **Step 1: Failing tests:**
  - `implied_shares_outstanding` 12.23e9 with `shares_outstanding` 5.867e9 → `dcf_input.shares_outstanding == 12.23e9`, flag `SHARE_CLASSES_COMBINED` naming both figures;
  - implied missing → uses `shares_outstanding`, no flag (Review Focus 2);
  - latest annual income statement `Diluted Average Shares` 634e6 and current shares 317e6 (ratio 0.5) → flag `CORPORATE_ACTION_SUSPECTED` whose message says a split, reverse split or spin-off may separate the statements from today's share count and the DCF per-share values are not meaningful until a post-action year is reported; ratio 0.9-1.1 → no flag;
  - no-debt/no-NCI company output unchanged apart from the new `assumptions.shares_outstanding` key (Review Focus 1).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `shares = implied or info shares or stmts shares`; when implied exceeds info shares by more than 5%, add `SHARE_CLASSES_COMBINED`. Compare against `_number(income, "Diluted Average Shares")`; flag when ratio < 0.75 or > 1.33. Document both in the docstring.
- [ ] **Step 4: Run** valuation tests and full suite — PASS.
- [ ] **Step 5: Commit** `fix(valuation): count every share class and flag corporate actions in inputs.py`.

---

### Task 5: `inputs.py` minority interests

**Files:**
- Modify: `skills/valuation/scripts/inputs.py`
- Test: `tests/test_scripts_valuation.py`

**Interfaces:**
- Produces: `assumptions.nci_share = {"value", "source"}` (share of net income attributable to noncontrolling interests, null when not reported); flag `LARGE_MINORITY_INTEREST`; `assumptions.tax_rate` recomputed on parent income when NCI is large.

- [ ] **Step 1: Failing tests** with income rows `Net Income Including Noncontrolling Interests` 2,800 and `Minority Interests` -960 (Yahoo reports it negative), `Tax Provision` 433, `Pretax Income` 3,233:
  - `nci_share` ≈ 0.343; flag `LARGE_MINORITY_INTEREST`; `fcf0` equals the consolidated FCFF × (1 − 0.343) (rounded to 2 dp);
  - tax rate = 433 / (3,233 − 960) ≈ 0.1905 → clipped normally, source says "on income attributable to the parent";
  - NCI share 5% → no flag, no scaling;
  - rows absent → `nci_share.value` null, output otherwise unchanged (Review Focus 1).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Threshold constant `_NCI_FLAG = 0.10`. Scale `fcf0` after the FCFF build; message: "partners own {share:.0%} of earnings; fcf0 is scaled to the parent's share. Book NCI understates the claim — value it from NCI earnings in a deep model."
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `fix(valuation): deduct minority interests in inputs.py`.

---

### Task 6: `inputs.py` cyclicals

**Files:**
- Modify: `skills/valuation/scripts/inputs.py`
- Test: `tests/test_scripts_valuation.py`

**Interfaces:**
- Produces: flag `CYCLICAL`; `assumptions.fcf0_latest = {"value", "source"}`; output key `dcf_input_latest` (same shape as `dcf_input`, built on the latest year's FCFF) present only when `CYCLICAL` fires; flag `CYCLE_BASE_SPLIT` when normalized and latest FCFF differ by more than 2x.

- [ ] **Step 1: Failing tests:** FCF margins [-0.10, 0.05, 0.30, 0.45] → `CYCLICAL`, `CYCLE_BASE_SPLIT`, `dcf_input_latest.fcf0` = latest FCFF; margins [0.20, 0.21, 0.22, 0.23] → neither flag and no `dcf_input_latest` key.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Cyclical when any margin ≤ 0 while the latest is > 0, or max/min margin > 3 with min > 0. Message for `CYCLE_BASE_SPLIT`: "normalized and latest-year cash flow differ more than 2x; present both and do not report one base value; intrinsic.py's normalized block gives a mid-cycle view."
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `fix(valuation): flag cyclicals and show latest-year cash flow beside the average`.

---

### Task 7: `inputs.py` WACC — net-cash weight, dated premium, `--erp`

**Files:**
- Modify: `skills/valuation/scripts/inputs.py` (usage becomes `inputs.py <symbol> [--erp RATE --erp-date YYYY-MM-DD]`)
- Modify: `skills/valuation/SKILL.md` (Background `What inputs.py builds` wacc row; Scripts block usage)
- Test: `tests/test_scripts_valuation.py`

**Interfaces:**
- Produces: `assumptions.equity_risk_premium = {"value", "source", "as_of"}`; flag `ERP_DEFAULT` (always when no `--erp`) and `ERP_STALE` (default older than 180 days from today); WACC debt weight on **net** debt: zero when cash ≥ debt.

- [ ] **Step 1: Failing tests:**
  - total_debt 6,750, total_cash 7,200 → `wacc == cost_of_equity` (unless the floor applies), source mentions "net cash: no debt weight";
  - total_debt 10,000, total_cash 2,000, market cap 50,000 → weight 8,000 / 58,000 (net-debt weight);
  - `--erp 0.045 --erp-date 2026-10-01` → cost of equity uses 0.045, no `ERP_DEFAULT`; `--erp` without date → exit 2; `--erp 0.3` → exit 2 (must be within 0.02-0.10);
  - default ERP: `_DEFAULT_ERP = 0.042`, `_DEFAULT_ERP_AS_OF = "2026-10-01"`, source "Damodaran implied ERP, 2026-10-01 (stated default; pass --erp with a dated figure)"; freeze `date.today()` 200 days later → `ERP_STALE`.
- [ ] **Step 2: Run** — FAIL. Update any existing test that asserted the 5% premium.
- [ ] **Step 3: Implement.** `dcf.py` still subtracts `net_debt`; the docstring must say debt is weighted net of cash so the two agree.
- [ ] **Step 4: Run** valuation + valuation_deep + full suite — PASS.
- [ ] **Step 5: Commit** `fix(valuation): weight net debt in the WACC and date the equity premium`.

---

### Task 8: Screener flags for minority interests and corporate actions

**Files:**
- Modify: `skills/stock-screener/scripts/screen_math.py` (flag logic and docstring), `skills/stock-screener/scripts/screen.py` (fetch the NCI frame; pass priced share count), `skills/stock-screener/SKILL.md` (Company flags table)
- Test: `tests/test_screen_math.py`, `tests/test_scripts_stock_screener.py`

**Interfaces:**
- Consumes: frame concept `NetIncomeLossAttributableToNoncontrollingInterest` (annual, USD) alongside the existing frames in `screen.py`; the priced share count Yahoo returns where `screen.py` prices survivors.
- Produces: company flags `LARGE_MINORITY_INTEREST` (NCI income > 10% of NCI + parent net income: cash yield overstates the shareholders' share) and `CORPORATE_ACTION` (priced shares / latest XBRL diluted shares outside 0.75-1.33 and no detected split: price figures meaningless). Add both to the "price figures are meaningless" handling wherever `MISSCALED` / `CASH_OUTRUNS_PROFIT` are treated so (search for those names).

- [ ] **Step 1: Failing tests** in `test_screen_math.py` for both flags on synthetic metric dicts (follow the file's existing builders), and a negative case each; in `test_scripts_stock_screener.py` assert the NCI frame is requested (follow how the test fakes `edgar.frame`).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** in the same style as `CASH_OUTRUNS_PROFIT`; add both rows to the SKILL.md Company flags table and to shortlist step 2's "drop when meaningless" list (`CORPORATE_ACTION` only; `LARGE_MINORITY_INTEREST` is named, not dropped).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-screener): flag large minority interests and corporate actions`.

---

### Task 9: `render_deep.py` shows the central case and value up front

**Files:**
- Modify: `skills/valuation/scripts/render_deep.py`
- Test: `tests/test_scripts_valuation_deep.py` (use `tests/page_dom.py` helpers the file already uses)

**Interfaces:**
- Produces: a `#headline` tile row before the scenario card; scenario table row for `model.scenarios[0]` labelled "Central" and pinned first; strip marks central; intro sentence. Docstring documents that the first scenario is the central case and nothing is averaged.

- [ ] **Step 1: Failing tests** (render a minimal model with three scenarios where the central one is not the highest value):
  - HTML contains `id="headline"` with tiles "Price", "Central value", "Central return / yr", "Worst case", "Range";
  - the rendered DATA / table setup pins the central row first (assert via the DOM helper or by checking the table config string contains `pin:` / the central name appears first in the rows JS) — follow how existing tests inspect the page;
  - intro text contains "not averaged";
  - central scenario with no matching returns row → page renders, central return "—" (Review Focus 4).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** In the JS: `const C = scs[0], cr = ret[C.name] || {}`; worst = scenario with lowest `value_per_share`; tiles via the existing `.tiles/.tile` CSS; table rows built with `central: i === 0` and a `pin` option (add to `FA.table` in `lib/second_opinion/page.py` only if needed: a row predicate kept first regardless of sort) — the name cell shows a "Central" pill; strip draws the central bar thicker with label "central". Intro lead: "…The central case is the scenario the research found most consistent with the evidence; the others are alternatives and are not averaged."
- [ ] **Step 4: Run** deep tests, page tests, full suite — PASS.
- [ ] **Step 5: Commit** `feat(valuation): put the central case and its value at the top of the deep page`.

---

### Task 10: `render_pick.py` leads each pick with the central value

**Files:**
- Modify: `skills/stock-screener/scripts/render_pick.py`
- Test: `tests/test_scripts_stock_picker.py`

- [ ] **Step 1: Failing test:** a passing pick card's first line reads `Central value $X vs price $Y · Z% a year` (format with the page's money/pct helpers) before the worst-case line; near-miss rows show central value too.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** using `r.central.value_per_share`, `r.price`, `r.central.irr`; keep the existing range text on the second line; update the Picks card help lead to say the central case is the deep valuation's first scenario and scenarios are not averaged.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-screener): lead each deep pick with its central value`.

---

### Task 11: Briefs, catalog and procedure — fetch before search

**Files:**
- Create: `skills/stock-screener/references/primary-sources.md`
- Modify: `skills/stock-screener/references/picker-roles.md`, `skills/valuation/references/deep-roles.md`, `skills/stock-screener/SKILL.md`, `skills/valuation/SKILL.md`, `tests/test_skills_structure.py` (register the new reference; add to `GUARDED_REFERENCES` if stock-screener is verb-guarded), `CHANGELOG.md`

- [ ] **Step 1: Failing test:** run `tests/test_skills_structure.py` after creating the catalog file without registering it — FAIL on registration; then register.
- [ ] **Step 2: Write `primary-sources.md`:** `## Contents`; one table per sector group with columns Data · Publisher · URL (template) · Updates · Checked. Rows from the sources the 2026-10-06 scanners cited: EIA STEO (`https://www.eia.gov/outlooks/steo/`), Census Advance Monthly Retail Trade (`https://www.census.gov/retail/marts/www/marts_current.pdf`), Census construction spending (`https://www.census.gov/construction/c30/current/index.html`), BLS CPI (`https://www.bls.gov/news.release/cpi.nr0.htm`), FRED series via `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES` (DGS10, IPMAN, BAMLC0A4CBBBEY), FDIC Quarterly Banking Profile, AAR weekly rail traffic, TSA checkpoint throughput, WSTS, FactSet Earnings Insight (`https://insight.factset.com/topic/earnings`), Damodaran implied ERP (`https://pages.stern.nyu.edu/~adamodar/`), Nareit, PJM Inside Lines, company IR pages via `edgar.py` `website`. Checked = 2026-10-06. A closing rule: a moved URL costs one search, then update the catalog row.
- [ ] **Step 3: Update `picker-roles.md` Shared rules:** before any search, read `primary-sources.md` and `context/macro.md`; SEC data only through the scripts (`edgar.py`, `filing.py`, `filing.py --url`, `earnings.py`); never write HTTP requests to sec.gov and never put a person's name, email or other identifier in a request, URL or file. Quick reader: management record from `earnings.py SYMBOL`; short volume and news from `sentiment.py`; check `inputs.py` flags (`SHARE_CLASSES_COMBINED`, `CORPORATE_ACTION_SUSPECTED`, `LARGE_MINORITY_INTEREST`, `CYCLICAL`, `CYCLE_BASE_SPLIT`) and, for `CYCLICAL`, read `intrinsic.py`'s `normalized` block.
- [ ] **Step 4: Update `deep-roles.md`:** same SEC/identifier rule in Shared rules; Management claims starts from `earnings.py`; Industry and news: "When the prompt hands you the picker's industry object and notes, take the sector outlook from them, check their dates against the latest earnings, and spend searches only on company news and competitors. Cap 4 in that case."
- [ ] **Step 5: Update stock-screener `SKILL.md`:** deep picker step 3.5 "Write `context/macro.md`" (10-year from FRED, oil/gas outlook from EIA STEO, retail and CPI headlines from the catalog, dated) before dispatching scanners; step 9 passes each finalist's industry object and `.md` into deep valuation; budget table 3-finalist row: scanners 10 each (30), quick reads 40, each deep valuation 30 (Industry and news 4) — total 160 with 40 in reserve; Reference files line for `primary-sources.md`; Scripts block lists `sentiment.py`. Keep under 500 lines.
- [ ] **Step 6: Update valuation `SKILL.md`:** `What inputs.py builds` rows for the new flags and `--erp`; Deep step 3 note that a picker-run deep valuation receives the industry notes; Deep step 7.8 says check `ERP_DEFAULT`/`ERP_STALE`.
- [ ] **Step 7: CHANGELOG** entry under Unreleased listing Tasks 1-11.
- [ ] **Step 8: Run** the full suite — PASS.
- [ ] **Step 9: Commit** `docs(stock-screener, valuation): fetch before search, catalog and new flags`.

---

### Task 12 (coordinator): Re-render and republish the run's pages

Not a subagent task. After Tasks 1-11 are merged on the branch: re-run `render_deep.py` on `DIR/deep-{ADBE,LDOS,THC,INTU}/page.json` and `render_pick.py` on `DIR/pick-2026-10-06/pick.json`, read each page, republish to the same artifact URLs, and tick the doc's to-dos for the fixed items.

## Out of scope (left in the doc)

- Bottom-up industry betas and credit spreads in `inputs.py` (needs a dated dataset).
- Changing deep-picker step 9 to one orchestrator per finalist (the doc's to-do asks to compare runs first).
- Where saved searches go (open question for the user).
