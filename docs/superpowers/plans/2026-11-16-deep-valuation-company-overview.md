# Deep Valuation Company Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put an "About SYMBOL" card at the top of the deep valuation page: profile facts, a short model-written business summary, and a five-year weekly share-price line chart.

**Architecture:** `render_deep.py --case` reads the facts from the research pack's `baseline/fundamentals.json`, takes the summary from a new optional `company` object in `blocks.json`, and fetches the price history through `second_opinion.market.price_history`. All three are written into `page.json`, so `--in` reproduces the page without a fetch. The page builds one card between the intro and the headline tiles, using the existing `F.lines` toolkit.

**Tech Stack:** Python 3.10+ standard library, pytest, headless Chrome for page tests, the shared `lib/second_opinion/page.py` toolkit.

**Spec:** `docs/superpowers/specs/2026-11-16-deep-valuation-company-overview-design.md`

## Global Constraints

- `render_deep.py --in` fetches nothing. Only `--case` may call `market.price_history()`.
- The page stays one self-contained HTML fragment: no external scripts, stylesheets or runtime fetches.
- Every card carries an `F.help` modal, and the audit rejects `recommend`, `advis`, `should` and `suggest` in that text.
- `company.summary` is at most 80 words and carries no advice word. The Yahoo `description` fallback is clipped to 90 words.
- Profile facts come from `baseline/fundamentals.json` `info`, whose keys are `name`, `sector`, `industry`, `country`, `employees`, `market_cap`, `website`, `description`.
- The history is `market.price_history(symbol, period="5y", interval="1wk")`, trimmed to `date` and `close`, and stored in `page.json`.
- An input with no `company` and no `price_history` renders exactly as the page does today.
- `--case` writes `page.json` and `page.html` only after validation passes.
- No change to `deep_prep.py`, `model.py`, `returns.py`, the picker or the quick page.
- Version 1.14.0 in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, with a CHANGELOG entry.
- Run `python3 -m pytest tests -q` from the repository root.

## Review Focus

1. **A `page.json` written before this change.** It has no `company` and no `price_history`; the page must render unchanged, with no empty About card. Tested in Task 2.
2. **A summary with no profile facts.** `blocks.json` may carry `company.summary` while `baseline/fundamentals.json` is absent (an older case folder); the card must show the summary and chart with no facts line. Tested in Task 3.
3. **Bad Yahoo rows.** A history row with a null close or no date must be dropped, not crash the build or leave a gap in the chart. Tested in Tasks 1 and 3.
4. **A failed history fetch.** The page must still publish, keep the company card, and add `PRICE_HISTORY_UNAVAILABLE`. Tested in Task 3.
5. **A one-point history.** The card must render without an empty chart. Tested in Task 2.

---

### Task 1: Page input contract and history normalization

**Files:**
- Modify: `skills/valuation/scripts/render_deep.py`
- Modify: `tests/test_scripts_valuation_deep.py`
- Modify: `docs/samples/valuation-deep.json`

**Interfaces:**
- Produces: `COMPANY_WORDS = 80`, `COMPANY_DESCRIPTION_WORDS = 90`
- Produces: `_clean_history(raw: dict | None) -> dict | None` — returns `{"symbol"?, "period"?, "interval"?, "prices": [{"date": str, "close": float}]}`, dropping rows without a date or a numeric close, and `None` when no valid row remains.
- Input gained: optional top-level `company` (object), `price_history` (object with `prices`), `flags` (list of `{"code", "message"}`).

- [ ] **Step 1: Extend the fixture and write the failing validation tests**

Add `from datetime import date, timedelta` to the test module's imports. In `page_input()`, add these two keys beside `"symbol"`, `"price"`, `"as_of"`:

```python
"company": {
    "summary": "Acme makes industrial fasteners for builders in North America. It sells through distributors and earns a gross margin near 30%.",
    "name": "Acme Corporation", "sector": "Industrials", "industry": "Tools and Accessories",
    "country": "United States", "employees": 12345, "market_cap": 4.2e9,
    "website": "https://acme.example",
    "description": "Acme Corporation makes industrial fasteners and sells them through distributors in North America.",
},
"price_history": {"symbol": "ACME", "period": "5y", "interval": "1wk", "prices": [
    {"date": (date(2021, 11, 19) + timedelta(weeks=i)).isoformat(),
     "close": round(15 + 2 * ((i % 26) / 26) + i * 0.01, 2)} for i in range(261)]},
```

Add these tests after the existing rejection tests:

```python
@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["company"].__setitem__("summary", "word " * 81), "81 words"),
    (lambda d: d["company"].__setitem__("summary", "You should buy the shares."), "forbidden word"),
    (lambda d: d.__setitem__("company", "Acme"), "company must be an object"),
])
def test_render_deep_rejects_bad_company(mutate, needle, tmp_path, capsys) -> None:
    data = page_input()
    mutate(data)
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["price_history"].__setitem__("prices", "x"), "prices must be a list"),
    (lambda d: d["price_history"]["prices"].append({"date": "2026-01-01", "close": "high"}), "close must be a number"),
    (lambda d: d["price_history"]["prices"].append({"close": 3}), "needs a date"),
])
def test_render_deep_rejects_bad_price_history(mutate, needle, tmp_path, capsys) -> None:
    data = page_input()
    mutate(data)
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


def test_render_deep_rejects_bad_flags(tmp_path, capsys) -> None:
    data = page_input()
    data["flags"] = [{"code": "X"}]
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "flags[0]" in res["error"]


def test_clean_history_drops_rows_without_a_close() -> None:
    mod = load_script(RENDER)
    hist = mod._clean_history({"symbol": "ACME", "period": "5y", "interval": "1wk", "prices": [
        {"date": "2021-11-19", "close": 15.0, "volume": 9},
        {"date": "2021-11-26", "close": None},
        {"close": 16.0},
    ]})
    assert hist == {"symbol": "ACME", "period": "5y", "interval": "1wk",
                    "prices": [{"date": "2021-11-19", "close": 15.0}]}
    assert mod._clean_history({"prices": []}) is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q -k "bad_company or bad_price_history or bad_flags or clean_history"`
Expected: FAIL — the renderer accepts every case, and `_clean_history` does not exist.

- [ ] **Step 3: Implement validation and normalization**

In `skills/valuation/scripts/render_deep.py`:

1. Import the shared advice-word check: `from second_opinion import output, page, summary_card`.
2. Add `COMPANY_WORDS = 80` and `COMPANY_DESCRIPTION_WORDS = 90` beside `HEADLINE_MAX`.
3. Add this function above `_validate`:

```python
def _clean_history(raw: dict | None) -> dict | None:
    """The page's price history: points with a date and a numeric close, trimmed to those two fields."""
    if not isinstance(raw, dict):
        return None
    prices = [
        {"date": str(p["date"]), "close": float(p["close"])}
        for p in raw.get("prices") or []
        if isinstance(p, dict) and isinstance(p.get("date"), str) and p["date"]
        and isinstance(p.get("close"), (int, float)) and not isinstance(p.get("close"), bool)
    ]
    if not prices:
        return None
    out = {"symbol": raw.get("symbol"), "period": raw.get("period"), "interval": raw.get("interval"), "prices": prices}
    return {k: v for k, v in out.items() if v is not None}
```

4. In `_validate`, after the ledger checks, add:

```python
    company = data.get("company")
    if company is not None:
        if not isinstance(company, dict):
            raise InvalidInput("company must be an object")
        summary = company.get("summary")
        if summary is not None:
            if not isinstance(summary, str) or not summary.strip():
                raise InvalidInput("company.summary must be a non-empty string")
            words = len(summary.split())
            if words > COMPANY_WORDS:
                raise InvalidInput(f"company.summary is {words} words; the limit is {COMPANY_WORDS}")
            found = summary_card.FORBIDDEN_VERB_RE.search(summary)
            if found:
                raise InvalidInput(f"company.summary uses the forbidden word {found.group(0)!r}")
        for key in ("name", "sector", "industry", "country", "website", "description"):
            value = company.get(key)
            if value is not None and not isinstance(value, str):
                raise InvalidInput(f"company.{key} must be a string")
        for key in ("employees", "market_cap"):
            value = company.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise InvalidInput(f"company.{key} must be a number")
    history = data.get("price_history")
    if history is not None:
        if not isinstance(history, dict):
            raise InvalidInput("price_history must be an object")
        prices = history.get("prices")
        if not isinstance(prices, list):
            raise InvalidInput("price_history.prices must be a list")
        for i, point in enumerate(prices):
            if not isinstance(point, dict) or not isinstance(point.get("date"), str) or not point["date"]:
                raise InvalidInput(f"price_history.prices[{i}] needs a date")
            close = point.get("close")
            if close is not None and (isinstance(close, bool) or not isinstance(close, (int, float))):
                raise InvalidInput(f"price_history.prices[{i}].close must be a number or null")
    flags = data.get("flags")
    if flags is not None:
        if not isinstance(flags, list):
            raise InvalidInput("flags must be a list")
        for i, flag in enumerate(flags):
            if not isinstance(flag, dict) or not isinstance(flag.get("code"), str) or not flag["code"] \
                    or not isinstance(flag.get("message"), str):
                raise InvalidInput(f"flags[{i}] needs code and message strings")
```

5. In `build()`, after `_validate(data)` and before the ledger line:

```python
    data["price_history"] = _clean_history(data.get("price_history"))
    if data["price_history"] is None:
        data.pop("price_history", None)
```

6. Count renderer flags in `build()`'s return: add `+ len(data.get("flags") or [])` to the `flags` expression.

7. Update the module docstring's input shape to name `company`, `price_history` and `flags`, the 80-word and 90-word limits, and the advice-word rule.

- [ ] **Step 4: Regenerate the committed sample**

Run from the repository root:

```bash
cd tests && python3 -c "import json, test_scripts_valuation_deep as t; open('../docs/samples/valuation-deep.json','w').write(json.dumps(t.page_input(), indent=1) + '\n')"
```

Then `git diff --stat docs/samples/valuation-deep.json` shows the two new keys.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q`
Expected: PASS, including `test_render_deep_sample_is_current`.

- [ ] **Step 6: Commit**

```bash
git add skills/valuation/scripts/render_deep.py tests/test_scripts_valuation_deep.py docs/samples/valuation-deep.json
git commit -m "Deep valuation: page input accepts company profile, price history and renderer flags"
```

---

### Task 2: The About card and price chart

**Files:**
- Modify: `skills/valuation/scripts/render_deep.py`
- Modify: `tests/test_scripts_valuation_deep.py`

**Interfaces:**
- Consumes: `_clean_history`'s `prices` (`{date, close}`), `COMPANY_DESCRIPTION_WORDS`.
- Produces: a `section.card#about-card` in the rendered page, inserted into `#about` between `#intro` and `#headline`, with an `h2` beginning "About ", a facts line, a summary paragraph and, with two or more points, an `svg` labelled `"{SYMBOL} five-year weekly share price"`.

- [ ] **Step 1: Write the failing page tests**

Add these after `test_render_deep_central_without_returns_row_shows_dash`:

```python
@requires_chrome
def test_render_deep_about_card_shows_company_and_chart(tmp_path) -> None:
    import re
    dom = _dom(page_input(), tmp_path)
    card = re.search(r'id="about-card".*?</section>', dom, re.S).group(0)
    assert "About Acme Corporation" in card
    assert "Industrials" in card and "Tools and Accessories" in card and "United States" in card
    assert "12,345 employees" in card and "$4.2B market cap" in card
    assert "Acme makes industrial fasteners" in card
    assert 'aria-label="ACME five-year weekly share price"' in card


@requires_chrome
def test_render_deep_without_company_or_history_has_no_about_card(tmp_path) -> None:
    data = page_input()
    data.pop("company")
    data.pop("price_history")
    assert 'id="about-card"' not in _dom(data, tmp_path)


@requires_chrome
def test_render_deep_one_price_point_draws_no_chart(tmp_path) -> None:
    import re
    data = page_input()
    data["price_history"]["prices"] = data["price_history"]["prices"][:1]
    card = re.search(r'id="about-card".*?</section>', _dom(data, tmp_path), re.S).group(0)
    assert "<svg" not in card


@requires_chrome
def test_render_deep_about_card_falls_back_to_the_yahoo_description(tmp_path) -> None:
    import re
    data = page_input()
    data["company"].pop("summary")
    data["company"]["description"] = " ".join(f"word{i}" for i in range(120))
    card = re.search(r'id="about-card".*?</section>', _dom(data, tmp_path), re.S).group(0)
    assert "word89" in card and "word90" not in card and "Business description from Yahoo Finance." in card


@requires_chrome
def test_render_deep_about_card_with_summary_only(tmp_path) -> None:
    import re
    data = page_input()
    data["company"] = {"summary": "Acme sells fasteners."}
    data.pop("price_history")
    card = re.search(r'id="about-card".*?</section>', _dom(data, tmp_path), re.S).group(0)
    assert "Acme sells fasteners." in card and "employee" not in card and "<svg" not in card
```

Note: the `_dom` helper already takes `tmp_path`; the first test's unused `_` parameter exists only to keep the same signature style as neighbours and may be dropped.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q -k "about_card or about-card or without_company or one_price_point"`
Expected: FAIL — `id="about-card"` is absent.

- [ ] **Step 3: Implement the card**

In the `BODY` string, replace

```html
<div id="intro"></div>
<div class="tiles" id="headline"></div>
```

with

```html
<div id="intro"></div>
<div id="about"></div>
<div class="tiles" id="headline"></div>
```

In `SCRIPT`, immediately after the `F.intro(...)` line and before the `const gated = ...` line, insert:

```js
  // about: the company's profile, business summary and five-year weekly share price
  const CO = D.company || {}, PH = D.price_history || {}, PP = PH.prices || [];
  const clip = (t, n) => { const w = String(t || '').trim().split(/\s+/); return w.length > n ? w.slice(0, n).join(' ') + '…' : w.join(' '); };
  if (CO.name || CO.summary || CO.description || PP.length > 1) {
    const card = F.el('section', {class: 'card', id: 'about-card'});
    card.innerHTML = `<h2>About ${esc(CO.name || D.symbol || 'the company')}</h2>`;
    const facts = [CO.sector, CO.industry, CO.country].filter(Boolean).map(esc);
    if (F.isNum(CO.employees)) facts.push(`${esc(F.num(CO.employees, 0))} employees`);
    if (F.isNum(CO.market_cap)) facts.push(`${esc(F.moneyC(CO.market_cap))} market cap`);
    if (CO.website) facts.push(`<a href="${esc(CO.website)}" target="_blank" rel="noopener">Website</a>`);
    if (facts.length) card.insertAdjacentHTML('beforeend', `<p class="sub" style="margin:0 0 10px">${facts.join(' · ')}</p>`);
    const text = CO.summary ? esc(CO.summary) : CO.description ? esc(clip(CO.description, 90)) : '';
    if (text) card.insertAdjacentHTML('beforeend', `<p style="font-size:14px;margin:0 0 6px">${text}</p>
      <p class="muted" style="font-size:12px;margin:0 0 10px">${CO.summary ? 'Business summary written from this valuation’s research.' : 'Business description from Yahoo Finance.'}</p>`);
    if (PP.length > 1) {
      const box = F.el('div', {id: 'price-chart'}); card.appendChild(box);
      F.lines(box, {series: [{name: D.symbol || 'Price', points: PP.map(p => [Date.parse(p.date), p.close]), color: F.S[0], area: true}],
        xIsDate: true, yFmt: v => F.money(v, 2), height: 260, aria: `${D.symbol || 'Share'} five-year weekly share price`});
      const last = PP[PP.length - 1], end = Date.parse(last.date);
      const yr = PP.filter(p => end - Date.parse(p.date) <= 366 * 864e5);
      const vals = (yr.length > 1 ? yr : PP).map(p => p.close).filter(F.isNum);
      if (vals.length) card.insertAdjacentHTML('beforeend', `<p class="sub" style="font-size:12px;margin:6px 0 0">Five years of weekly closes from Yahoo Finance, through ${esc(last.date)}. ${yr.length > 1 ? 'Range over the last 52 weeks' : 'Range since ' + esc(PP[0].date)}: ${esc(F.money(Math.min(...vals)))} to ${esc(F.money(Math.max(...vals)))}.</p>`);
    }
    g('about').appendChild(card);
    F.help(card, {lead: 'What the company does and how its shares have traded, before the valuation below.',
      sections: [{title: 'Where this comes from', html: '<p>The profile facts, and the business description when the research wrote no summary, come from Yahoo Finance. A summary written by this valuation’s research takes the place of the description.</p>'},
                 {title: 'The chart', html: '<p>One point per week for five years, ending at the latest close Yahoo returned when this page was built.</p>'}]});
  }
```

- [ ] **Step 4: Run the page tests**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q -k "about_card or about-card or without_company or one_price_point or explains_itself"`
Expected: PASS, including `test_render_deep_every_card_explains_itself`.

- [ ] **Step 5: Run the whole deep test module**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/valuation/scripts/render_deep.py tests/test_scripts_valuation_deep.py
git commit -m "Deep valuation: About card with company facts, summary and five-year price chart"
```

---

### Task 3: `--case` reads the profile and fetches the history

**Files:**
- Modify: `skills/valuation/scripts/render_deep.py`
- Modify: `tests/test_scripts_valuation_deep.py`

**Interfaces:**
- Produces: `_company(case: Path, spec: dict) -> dict | None` — the pack's `info` facts merged with `spec["company"]["summary"]`.
- Produces: `_fetch_price_history(symbol: str) -> tuple[dict | None, dict | None]` — `(cleaned_history, flag)`.
- Consumes: `market.price_history(symbol, period="5y", interval="1wk")` from `second_opinion.market`.
- `case_input()` output gains `company`, `price_history` and `flags` when available.

- [ ] **Step 1: Add the market stub and update `case_dir`**

At module level near `SAMPLE`, add:

```python
HISTORY = {"symbol": "ACME", "period": "5y", "interval": "1wk", "prices": [
    {"date": "2021-11-19", "close": 15.0, "open": 14.0},
    {"date": "2021-11-26", "close": 16.5},
    {"date": "2021-12-03", "close": None},
    {"date": "2021-12-10", "close": 17.2},
]}


@pytest.fixture(autouse=True)
def market_history(monkeypatch):
    """No network in this module: every --case render sees the same history."""
    from second_opinion import market
    calls = []
    def fake(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return HISTORY
    monkeypatch.setattr(market, "price_history", fake)
    return calls
```

In `case_dir`, create the profile beside the other case files:

```python
    profile = {"info": {"name": "Acme Corporation", "sector": "Industrials", "industry": "Tools and Accessories",
                        "country": "United States", "website": "https://acme.example", "employees": 12345,
                        "market_cap": 4.2e9, "description": "Acme sells fasteners."}}
    (case / "baseline").mkdir()
    (case / "baseline" / "fundamentals.json").write_text(json.dumps(profile))
```

and add the summary to the `blocks.json` body:

```python
        "blocks.json": {"blocks": data["blocks"], "company": {"summary": "Acme sells fasteners to builders."},
                        "as_of": data["as_of"], "notes": data["notes"], "missing_roles": data["missing_roles"]},
```

- [ ] **Step 2: Write the failing `--case` tests**

Add these after `test_render_deep_case_builds_page_json_and_html`:

```python
def test_render_deep_case_carries_profile_and_history(tmp_path, capsys, market_history) -> None:
    case, _ = case_dir(tmp_path)
    rc, res = run_json(load_script(RENDER), ["--case", str(case)], capsys)
    assert rc == 0, res
    page_json = json.loads((case / "page.json").read_text())
    assert page_json["company"]["summary"] == "Acme sells fasteners to builders."
    assert page_json["company"]["name"] == "Acme Corporation" and page_json["company"]["employees"] == 12345
    assert page_json["price_history"]["prices"] == [
        {"date": "2021-11-19", "close": 15.0}, {"date": "2021-11-26", "close": 16.5},
        {"date": "2021-12-10", "close": 17.2}]
    assert market_history == [("ACME", {"period": "5y", "interval": "1wk"})]


def test_render_deep_case_fetch_failure_still_publishes(tmp_path, capsys, monkeypatch) -> None:
    from second_opinion import market
    case, _ = case_dir(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("Yahoo down")

    monkeypatch.setattr(market, "price_history", boom)
    rc, res = run_json(load_script(RENDER), ["--case", str(case)], capsys)
    assert rc == 0, res
    page_json = json.loads((case / "page.json").read_text())
    assert "price_history" not in page_json and page_json["company"]["summary"]
    assert {"code": "PRICE_HISTORY_UNAVAILABLE", "message": "Yahoo price history failed: Yahoo down"} in page_json["flags"]
    assert "Yahoo down" in (case / "page.html").read_text()


def test_render_deep_case_summary_without_a_profile_still_renders(tmp_path, capsys) -> None:
    case, _ = case_dir(tmp_path)
    (case / "baseline" / "fundamentals.json").unlink()
    rc, res = run_json(load_script(RENDER), ["--case", str(case)], capsys)
    assert rc == 0, res
    page_json = json.loads((case / "page.json").read_text())
    assert page_json["company"] == {"summary": "Acme sells fasteners to builders."}
    assert len(page_json["price_history"]["prices"]) == 3
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q -k "carries_profile or fetch_failure or summary_without_a_profile"`
Expected: FAIL — `page.json` has no `company` or `price_history`.

- [ ] **Step 4: Implement the case assembly**

In `render_deep.py`:

1. Add `market` to the shared import: `from second_opinion import market, output, page, summary_card`.
2. Add `FACT_KEYS = ("name", "sector", "industry", "country", "employees", "market_cap", "website", "description")` beside the other constants.
3. Add these functions above `case_input`:

```python
def _company(case: Path, spec: dict) -> dict | None:
    """The About card's facts (Yahoo's profile) and the summary written in blocks.json."""
    profile = _case_file(case / "baseline", "fundamentals.json", required=False)
    info = profile.get("info") if isinstance(profile, dict) and isinstance(profile.get("info"), dict) else {}
    company = {k: info[k] for k in FACT_KEYS if info.get(k) not in (None, "")}
    extra = spec.get("company")
    if isinstance(extra, dict) and isinstance(extra.get("summary"), str) and extra["summary"].strip():
        company["summary"] = extra["summary"]
    return company or None


def _fetch_price_history(symbol: str) -> tuple[dict | None, dict | None]:
    """Five years of weekly closes from Yahoo, trimmed for the page; (history, flag) with one of them None."""
    if not symbol:
        return None, {"code": "PRICE_HISTORY_UNAVAILABLE", "message": "the model names no symbol"}
    try:
        raw = market.price_history(symbol, period="5y", interval="1wk")
    except Exception as exc:  # noqa: BLE001 — a failed fetch leaves the chart out, not the page
        return None, {"code": "PRICE_HISTORY_UNAVAILABLE", "message": f"Yahoo price history failed: {exc}"}
    history = _clean_history(raw)
    if not history or len(history["prices"]) < 2:
        return None, {"code": "PRICE_HISTORY_UNAVAILABLE",
                      "message": f"Yahoo returned no usable price history for {symbol}"}
    return history, None
```

4. In `case_input`, after `data` is built and before the `missing_roles`/`notes` loop:

```python
    company = _company(case, spec)
    if company:
        data["company"] = company
    history, flag = _fetch_price_history(str(model.get("symbol") or ""))
    if history:
        data["price_history"] = history
    if flag:
        data["flags"] = [flag]
```

5. Update the docstring's `--case` paragraph to name `baseline/fundamentals.json`, the five-year weekly fetch and `PRICE_HISTORY_UNAVAILABLE`.

- [ ] **Step 5: Run the deep tests**

Run: `python3 -m pytest tests/test_scripts_valuation_deep.py -q`
Expected: PASS, including the round-trip test `test_render_deep_case_builds_page_json_and_html`.

- [ ] **Step 6: Commit**

```bash
git add skills/valuation/scripts/render_deep.py tests/test_scripts_valuation_deep.py
git commit -m "Deep valuation: --case reads the company profile and fetches five years of weekly closes"
```

---

### Task 4: Skill text, docs and version

**Files:**
- Modify: `skills/valuation/SKILL.md`
- Modify: `docs/scripts.md`
- Modify: `CHANGELOG.md`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `tests/test_version.py`

**Interfaces:**
- Consumes: the page behaviour and data contract from Tasks 1–3.

- [ ] **Step 1: Update `skills/valuation/SKILL.md`**

Make these edits:

1. In the case-folder table, replace the `blocks.json` row with:

```
| `blocks.json` | The page's blocks and the company summary: `{"blocks": [...], "company": {"summary"}, "as_of"?, "notes"?, "missing_roles"?}` |
```

and the `page.json`, `page.html` row with:

```
| `page.json`, `page.html` | Written by `render_deep.py --case` from `model.out.json`, `returns.out.json`, `ledger.json`, `blocks.json` and `baseline/fundamentals.json` |
```

2. Replace the paragraph beginning "`render_deep.py` always opens with the scenario table" with:

```
`render_deep.py` opens with an About card: the company name, profile facts and a business summary, then a five-year weekly share-price chart. The facts come from `baseline/fundamentals.json`; the summary is the one you write in `blocks.json`; without one the card shows Yahoo's business description. A failed chart fetch leaves the chart out and adds `PRICE_HISTORY_UNAVAILABLE` to the flags. Then the page shows the scenario table and the price against the scenarios. After that it shows the blocks you list, in your order. `segments`, `drivers`, `ledger`, `track_record`, `forensics`, `skepticism`, `sensitivity`, `custom` and `text` are described in its docstring. A ledger claim without a source and a date is exit 2.
```

3. In Step 12, after the "It takes the model..." bullet, add:

```
    - Write `company.summary`: two or three sentences, at most 80 words, on what the business sells, to whom, where, and how it earns, taken from the research pack. Do not give advice.
```

4. In the scripts table, replace the `render_deep.py` row with:

```
| `render_deep.py` | The deep-mode page: an About card with the company profile, business summary and five-year weekly share-price chart, the scenario table, the price strip, then the chosen blocks. `--case` assembles `page.json` from the case folder and `baseline/fundamentals.json`, fetches the price history, and writes `page.html` beside it. |
```

5. In the exit-code table's row 2, replace "a missing `model.out.json` or `blocks.json`, an unknown block, or an undated ledger claim" with "a missing `model.out.json` or `blocks.json`, an unknown block, an undated ledger claim, a company summary over 80 words or with an advice word, or a malformed price history".

- [ ] **Step 2: Update `docs/scripts.md`**

Replace the `render_deep.py` table row with:

```
| `render_deep.py` | `render_deep.py --case DIR` or `render_deep.py [--in page.json] --out page.html` — the deep valuation page: an About card (company profile facts and summary from `baseline/fundamentals.json` and `blocks.json`'s `company`, plus a five-year weekly price chart fetched at build), the scenario table, price strip, then the chosen blocks; `--case` assembles `DIR/page.json` and writes `DIR/page.html` beside it; a failed history fetch adds `PRICE_HISTORY_UNAVAILABLE` and publishes without the chart; prints `{"out","title","symbol","scenarios","blocks","flags"}`; exit 2 on a missing model, a missing `model.out.json` or `blocks.json` under `--case`, an unknown block, an undated ledger claim, a summary over 80 words or with an advice word, or a malformed price history |
```

- [ ] **Step 3: Add the CHANGELOG entry and bump both manifests**

Prepend after `# Changelog`:

```markdown
## 1.14.0

- deep valuation: the page opens with an About card. It carries the company's profile facts from `baseline/fundamentals.json`, a business summary written by the valuation's research, and a five-year weekly share-price chart. `render_deep.py --case` fetches the history from Yahoo and writes both into `page.json`, so a later `--in` run reproduces the page without a fetch. A failed fetch publishes the page without the chart and adds `PRICE_HISTORY_UNAVAILABLE`. Without a written summary the card shows Yahoo's description, clipped at 90 words. `blocks.json` gains an optional top-level `company` object; an input without it renders as before.
```

Set `"version": "1.14.0"` in `.claude-plugin/plugin.json` and in the `plugins[0]` object in `.claude-plugin/marketplace.json`.

- [ ] **Step 4: Update the version test**

In `tests/test_version.py`, change the assertion to `assert v == m == "1.14.0"`.

- [ ] **Step 5: Run the full suite and the version check**

Run: `python3 -m pytest tests -q`
Expected: PASS.

Run: `bash scripts/check-version.sh`
Expected: exit 0 with no output.

- [ ] **Step 6: Commit**

```bash
git add skills/valuation/SKILL.md docs/scripts.md CHANGELOG.md .claude-plugin/plugin.json .claude-plugin/marketplace.json tests/test_version.py
git commit -m "Deep valuation: document the About card and bump to 1.14.0"
```

---

## Self-Review

- **Spec coverage:** the About card (Task 2), summary and fallback (Tasks 1–2), facts from `fundamentals.json` and summary from `blocks.json` (Tasks 1, 3), `--case` fetch and `page.json` (Task 3), failure handling (Task 3), old-input compatibility (Task 2 test), docs and version (Task 4). Every rendering detail in the spec has a step.
- **Step scan:** every step names the test or the edit and its expected result. No "handle edge cases" steps remain.
- **Type consistency:** `_clean_history` returns the shape `_fetch_price_history` and the renderer both consume; `company` field names match `market.company_info`'s snake_case output; `case_input` adds the keys Task 2's script reads.
- **Review Focus:** all five entries have a test in Tasks 2 or 3.
- **Proportion:** the only code block beyond a test or a one-line edit is the card builder, whose markup, source lines and chart options the spec fixes.
