"""render_brief.py --history: the "Performance vs. the market" card."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from datetime import date, timedelta

import pytest
from page_dom import audit_html, requires_chrome
from scripts_util import PLUGIN_ROOT, load_script, run_json

SCRIPT = "portfolio-analysis/scripts/render_brief.py"
SNAP = json.loads((PLUGIN_ROOT / "docs/samples/portfolio-brief.json").read_text())
PRE_CHANGE = "fb92481"  # the commit before the card existed


def _history(days: int = 400, *, estimated: bool = True, series: bool = True) -> dict:
    start = date(2026, 11, 18) - timedelta(days=days)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]

    def pts(rate: float) -> list:
        return [[d, round(1.0 + rate * i, 5), round(1000 * (1 + rate * i), 2)] for i, d in enumerate(dates)]

    def bench(sym: str, label: str, rate: float) -> dict:
        return {"symbol": sym, "label": label, "points": [[d, round(1.0 + rate * i, 5)] for i, d in enumerate(dates)]}

    flags = [{"code": "SHORT_HISTORY", "message": "acct-b: only 20 days of history"}]
    out = {"as_of": "2026-11-18", "series": [], "benchmarks": [bench("SPY", "S&P 500", 0.0004), bench("QQQ", "Nasdaq", 0.0005),
           bench("DIA", "Dow", 0.0003)], "excluded": [{"account_id": "acct-x", "reason": "NO_HISTORY: run statement-import"}],
           "flags": flags}
    if series:
        out["series"] = [
            {"key": "combined", "label": "All accounts", "start": dates[0], "estimated": estimated, "accounts": ["acct-a", "acct-b"], "points": pts(0.0003)},
            {"key": "acct-a", "label": "Brokerage", "start": dates[0], "estimated": False, "points": pts(0.0002)},
            {"key": "acct-b", "label": "401(k)", "start": dates[0], "estimated": estimated, "points": pts(0.0004)},
        ]
        if estimated:
            flags.append({"code": "PROXY_PRICED", "message": "acct-b: ONN5 has no public price; history estimated from VOO"})
    else:
        out["flags"] = [{"code": "LEDGER_EMPTY", "message": "the ledger has no transactions"}]
    return out


def _old_build(tmp_path):
    try:
        src = subprocess.run(["git", "show", f"{PRE_CHANGE}:skills/portfolio-analysis/scripts/render_brief.py"], cwd=PLUGIN_ROOT,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"commit {PRE_CHANGE} not available")
    # the old file finds lib/ relative to its own location; point it at the real one
    src = src.replace('Path(__file__).resolve().parents[3] / "lib"', repr(str(PLUGIN_ROOT / "lib")).join(['Path(', ')']))
    f = tmp_path / "render_brief_old.py"
    f.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("render_brief_old", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build


# Deliberate page changes made after PRE_CHANGE, outside the history card: (old text, new text).
LATER_CHANGES = [
    ("<p class=\"sub\">Earnings and dividend dates coming up for what you hold.</p>",
     "<p class=\"sub\">Earnings and dividend dates for what you hold, and your next loan and card payments.</p>"),
    ("<th class=\"l\">Symbol</th><th class=\"l\">Type</th></tr></thead><tbody>' + D.events",
     "<th class=\"l\">Holding or account</th><th class=\"l\">Event</th></tr></thead><tbody>' + D.events"),
    ("${F.esc(e.type)}</td></tr>`)", "${F.esc(e.label || String(e.type || '').replace('_', '-'))}</td></tr>`)"),
    ("{lead: 'Upcoming earnings reports and dividend dates for what you hold.',",
     "{lead: 'Upcoming earnings reports and dividend dates for what you hold, and the next payment on each loan or card you recorded.',"),
    ("title: 'The two kinds of date', html: '<p>An earnings date is when the company reports results; prices often move more than usual around it. An ex-dividend date is the cutoff: own the shares before it to receive the next dividend.</p>'",
     "title: 'The three kinds of date', html: '<p>An earnings date is when the company reports results; prices often move more than usual around it. An ex-dividend date is the cutoff: own the shares before it to receive the next dividend. A fund has no announced date, so its date is marked expected: a year after the matching payment last year. A payment date comes from the last statement you recorded; when that statement is older, its due date is carried forward one month at a time.</p>'"),
    ("const mv = [...(M.up || []).map(m => ({...m, dir: 1})), ...(M.down || []).map(m => ({...m, dir: -1}))];",
     "// one scale, largest gain to largest loss, so the losers end with the biggest drop\n  const mv = [...(M.up || []), ...(M.down || [])].sort((a, b) => (b.day_change_pct || 0) - (a.day_change_pct || 0));"),
    # the total tiles moved to the top, above the summary card and Headlines
    ('<div id="explain"></div>\n', '<div id="explain"></div>\n<div class="tiles" id="tiles"></div>\n'),
    ('</details></section>\n<div class="tiles" id="tiles"></div>\n<div class="grid2">', '</details></section>\n<div class="grid2">'),
    # Holdings shows the top ten and Upcoming events the next eight, each with a View all toggle
    ("<style>#holdings td.l{white-space:normal;min-width:120px}</style>",
     "<style>#holdings td.l{white-space:normal;min-width:120px}#hold-more,#ev-more{margin-top:10px}</style>"),
    ("  <div class=\"twrap\" id=\"holdings\"></div>\n</section>",
     "  <div class=\"twrap\" id=\"holdings\"></div>\n  <button type=\"button\" class=\"chip\" id=\"hold-more\" hidden></button>\n</section>"),
    ("<div class=\"twrap\" id=\"events\"></div></section>",
     "<div class=\"twrap\" id=\"events\"></div><button type=\"button\" class=\"chip\" id=\"ev-more\" hidden></button></section>"),
    ("  const tbl = F.table(g('holdings'), cols, rows, {sortKey: 'market_value', onDraw: vis => { g('count').textContent = `${vis.length} of ${rows.length}`;\n    g('holdings').querySelectorAll('tbody tr').forEach((tr, i) => { tr.classList.add('clickable'); tr.tabIndex = 0; const open = () => detail(vis[i]); tr.addEventListener('click', open); tr.addEventListener('keydown', e => { if (e.key === 'Enter') open(); }); }); }});\n",
     "  // the ten largest by default; a search or an account filter shows every match\n  const HOLD_TOP = 10;\n  let holdAll = false;\n  const tbl = F.table(g('holdings'), cols, rows, {sortKey: 'market_value', onDraw: vis => {\n    const narrowed = !!g('acct').value || !!g('q').value.trim(), cut = !holdAll && !narrowed && vis.length > HOLD_TOP;\n    g('count').textContent = cut ? `top ${HOLD_TOP} of ${rows.length}` : `${vis.length} of ${rows.length}`;\n    g('holdings').querySelectorAll('tbody tr').forEach((tr, i) => { tr.classList.add('clickable'); tr.tabIndex = 0; if (cut && i >= HOLD_TOP) tr.hidden = true; const open = () => detail(vis[i]); tr.addEventListener('click', open); tr.addEventListener('keydown', e => { if (e.key === 'Enter') open(); }); });\n    const mb = g('hold-more'); mb.hidden = narrowed || vis.length <= HOLD_TOP; mb.textContent = holdAll ? `Show top ${HOLD_TOP}` : `View all ${vis.length} holdings`; }});\n  g('hold-more').addEventListener('click', () => { holdAll = !holdAll; tbl.redraw(); });\n"),
    ("    g('events').innerHTML = '<table><thead><tr><th class=\"l\">Date</th><th class=\"l\">Holding or account</th><th class=\"l\">Event</th></tr></thead><tbody>' + D.events.map(e => `<tr><td class=\"l\">${F.esc(e.date)}</td><td class=\"l\">${F.esc(e.symbol)}</td><td class=\"l\">${F.esc(e.label || String(e.type || '').replace('_', '-'))}</td></tr>`).join('') + '</tbody></table>'; }\n",
     "    const EV_TOP = 8;  // the next eight by date; the rest behind View all\n    g('events').innerHTML = '<table><thead><tr><th class=\"l\">Date</th><th class=\"l\">Holding or account</th><th class=\"l\">Event</th></tr></thead><tbody>' + D.events.map((e, i) => `<tr${i >= EV_TOP ? ' hidden' : ''}><td class=\"l\">${F.esc(e.date)}</td><td class=\"l\">${F.esc(e.symbol)}</td><td class=\"l\">${F.esc(e.label || String(e.type || '').replace('_', '-'))}</td></tr>`).join('') + '</tbody></table>';\n    if (D.events.length > EV_TOP) { const b = g('ev-more'); let all = false; b.hidden = false;\n      const label = () => { b.textContent = all ? `Show next ${EV_TOP}` : `View all ${D.events.length} events`; }; label();\n      b.addEventListener('click', () => { all = !all; g('events').querySelectorAll('tbody tr').forEach((tr, i) => { if (i >= EV_TOP) tr.hidden = !all; }); label(); }); } }\n"),
]


def _with_later_changes(page: str) -> str:
    for before, after in LATER_CHANGES:
        assert before in page, before
        page = page.replace(before, after)
    return page


def test_render_without_history_byte_identical(tmp_path) -> None:
    new = load_script(SCRIPT).build
    old = _old_build(tmp_path)
    assert new(SNAP) == _with_later_changes(old(SNAP))
    assert new(SNAP, None, None) == _with_later_changes(old(SNAP))
    assert "perf-card" not in new(SNAP)


def test_render_with_history_has_card_picker_ranges() -> None:
    html = load_script(SCRIPT).build(SNAP, None, _history())
    assert 'id="perf-card"' in html and 'id="perf-account"' in html and "Performance vs. the market" in html
    for r in ("1M", "3M", "YTD", "1Y", "All"):
        assert f"'{r}'" in html
    assert html.index('id="tiles"') < html.index('id="headlines-card"') < html.index('id="perf-card"') < html.index('id="accounts-card"')
    assert '"history":' in html


def test_history_flags_join_flags_section() -> None:
    html = load_script(SCRIPT).build(SNAP, None, _history())
    assert "SHORT_HISTORY" in html and "PROXY_PRICED" in html  # carried in the data
    assert "concat(hflags)" in html  # and merged into the list the Flags section draws


def test_build_rejects_malformed_history() -> None:
    from second_opinion.errors import InvalidInput
    with pytest.raises(InvalidInput):
        load_script(SCRIPT).build(SNAP, None, {"nope": 1})


def test_cli_history_flag(tmp_path, capsys) -> None:
    h = tmp_path / "history.json"
    h.write_text(json.dumps(_history()))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script(SCRIPT), ["--in", str(PLUGIN_ROOT / "docs/samples/portfolio-brief.json"), "--history", str(h), "--out", str(out)], capsys)
    assert rc == 0 and 'id="perf-card"' in out.read_text()
    rc, res = run_json(load_script(SCRIPT), ["--in", str(PLUGIN_ROOT / "docs/samples/portfolio-brief.json"), "--history", str(tmp_path / "missing.json"), "--out", str(out)], capsys)
    assert rc == 2 and "history" in res["error"]


def _page_text(html: str, tmp_path, probe: str) -> dict:
    """Run the page, then probe(): JS returning a JSON-able value, written into a script tag the audit does not touch."""
    from page_dom import chrome_cmd
    import html as html_mod
    page = tmp_path / "probe.html"
    page.write_text('<!doctype html><html><head><meta charset="utf-8"></head><body>' + html +
                    f'<script>window.addEventListener("load",()=>{{const r=(()=>{{{probe}}})();const s=document.createElement("pre");s.id="probe";s.textContent=JSON.stringify(r);document.body.appendChild(s);}});</script></body></html>', encoding="utf-8")
    out = subprocess.run([*chrome_cmd(tmp_path, budget_ms=3000), "--window-size=1280,2000", "--dump-dom", page.as_uri()], capture_output=True, text=True, timeout=90)
    m = re.search(r'<pre id="probe">(.*?)</pre>', out.stdout, re.S)
    assert m, out.stderr[-500:]
    return json.loads(html_mod.unescape(m.group(1)))


@requires_chrome
def test_estimated_series_labelled(tmp_path) -> None:
    html = load_script(SCRIPT).build(SNAP, None, _history())
    r = _page_text(html, tmp_path, "return {opts:[...document.querySelectorAll('#perf-account option')].map(o=>[o.textContent,o.disabled,o.title]),"
                                   "note:document.getElementById('perf-note').textContent,summary:document.getElementById('perf-summary').textContent,"
                                   "pressed:[...document.querySelectorAll('#perf-ranges button')].map(b=>[b.dataset.range,b.disabled,b.getAttribute('aria-pressed')]),"
                                   "svg:!!document.querySelector('#perf-chart svg')}")
    assert any("estimated via VOO" in o[0] for o in r["opts"] if o[0].startswith("401(k)"))
    assert "estimated via VOO" in r["note"]  # the combined series includes the estimated account
    assert ["acct-x (left out)", True, "NO_HISTORY: run statement-import"] in r["opts"]
    assert r["svg"] and "pts vs. S&P 500" in r["summary"] and "Your portfolio +" in r["summary"] and "Nasdaq" in r["summary"] and "Dow" in r["summary"]
    assert ["1Y", False, "true"] in r["pressed"]  # 400 days of data: 1Y is the default


@requires_chrome
def test_short_data_defaults_to_all_and_disables_long_ranges(tmp_path) -> None:
    html = load_script(SCRIPT).build(SNAP, None, _history(days=100, estimated=False))
    r = _page_text(html, tmp_path, "return [...document.querySelectorAll('#perf-ranges button')].map(b=>[b.dataset.range,b.disabled,b.getAttribute('aria-pressed')])")
    by = {k: (d, p) for k, d, p in r}
    assert by["All"] == (False, "true") and by["1Y"][0] is True and by["3M"][0] is False


@requires_chrome
def test_disabled_ranges_look_disabled_and_say_why(tmp_path) -> None:
    hist = _history(days=100, estimated=False)
    html = load_script(SCRIPT).build(SNAP, None, hist)
    r = _page_text(html, tmp_path, "return [...document.querySelectorAll('#perf-ranges button')].map(b=>"
                                   "[b.dataset.range,b.disabled,b.title,getComputedStyle(b).opacity,getComputedStyle(b).cursor])")
    by = {k: rest for k, *rest in r}
    first = hist["series"][0]["points"][0][0]
    from datetime import date
    label = date.fromisoformat(first).strftime("%b %-d, %Y")
    assert by["1Y"][0] is True and by["1Y"][1] == f"History starts {label}"
    assert float(by["1Y"][2]) < 0.6 and by["1Y"][3] == "not-allowed"
    assert by["3M"][1] == "" and float(by["3M"][2]) == 1.0


# wraps FA.lines so a probe can read what was drawn: each line's name and [x, y] points
CAPTURE = "const cap=[]; const orig=FA.lines; FA.lines=(el,o)=>{cap.push(o); return orig(el,o);};"
REDRAW = "document.querySelector('#perf-ranges button[aria-pressed=true]').click();"  # the default range, drawn again under CAPTURE
DRAWN = ("const o=cap[cap.length-1]; return {lines:o.series.map(l=>[l.name,l.points[0][1],l.points[l.points.length-1][1]]),"
         "note:document.getElementById('perf-note').textContent,sum:document.getElementById('perf-summary').textContent};")


@requires_chrome
def test_account_switch_rebases_to_zero(tmp_path) -> None:
    hist = _history()
    html = load_script(SCRIPT).build(SNAP, None, hist)
    r = _page_text(html, tmp_path, CAPTURE + "const s=document.getElementById('perf-account'); s.value='acct-a'; s.dispatchEvent(new Event('change'));"
                                   "const o=cap[cap.length-1]; return {lines:o.series.map(l=>[l.name,l.points[0][1]]),"
                                   "label:document.querySelector('#perf-chart .legend').textContent, sum:document.getElementById('perf-summary').textContent}")
    assert "Brokerage" in r["label"] and "S&P 500" in r["label"]
    assert [n for n, _ in r["lines"]] == ["Brokerage", "S&P 500", "Nasdaq", "Dow"]
    assert all(y == 0 for _, y in r["lines"])  # every line starts at 0% on the base day
    a = next(s for s in hist["series"] if s["key"] == "acct-a")
    h = load_script("portfolio-analysis/scripts/history.py")._headline(a["points"], hist["as_of"], hist["benchmarks"][0]["points"], False)
    assert f"Your portfolio +{h['portfolio_return'] * 100:.1f}%" in r["sum"]


def _weekdays(start: str, end: str, skip=()) -> list[str]:
    d, out = date.fromisoformat(start), []
    while d <= date.fromisoformat(end):
        if d.weekday() < 5 and d.isoformat() not in skip:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _custom(dates: list[str], idx, spy=None) -> dict:
    """A one-series history over ``dates`` with index values ``idx(date)``."""
    pts = [[d, idx(d), 1000.0] for d in dates]
    bench = [{"symbol": "SPY", "label": "S&P 500", "points": [[d, (spy or idx)(d)] for d in dates]}]
    return {"as_of": dates[-1], "series": [{"key": "combined", "label": "All accounts", "start": dates[0], "estimated": False,
            "accounts": ["a"], "points": pts}], "benchmarks": bench, "excluded": [], "flags": []}


@requires_chrome
def test_ytd_bases_on_last_close_of_prior_year(tmp_path) -> None:
    # the year's first trading day moves +10%; YTD must include it (base 2025-12-31), not start on it
    dates = _weekdays("2025-06-02", "2026-11-18", skip=("2026-01-01",))
    html = load_script(SCRIPT).build(SNAP, None, _custom(dates, lambda d: 1.0 if d < "2026" else 1.1 if d < "2026-11-18" else 1.21))
    r = _page_text(html, tmp_path, CAPTURE + "[...document.querySelectorAll('#perf-ranges button')].find(b=>b.dataset.range==='YTD').click();" + DRAWN)
    assert "Lines start at 0% on 2025-12-31" in r["note"]
    assert all(first == 0 for _, first, _ in r["lines"])
    assert r["lines"][0][2] == pytest.approx(0.21)
    assert "Your portfolio +21.0%" in r["sum"]


@requires_chrome
def test_range_switching_bases_on_last_point_on_or_before_start(tmp_path) -> None:
    dates = _weekdays("2025-06-02", "2026-11-18")
    hist = _custom(dates, lambda d: 1.0 + dates.index(d) * 0.001)
    html = load_script(SCRIPT).build(SNAP, None, hist)
    probe = CAPTURE + "const out={}; for (const r of ['1M','3M','1Y','All']) { [...document.querySelectorAll('#perf-ranges button')].find(b=>b.dataset.range===r).click();" \
        "const o=cap[cap.length-1]; out[r]=[document.getElementById('perf-note').textContent, o.series[0].points[0][1], o.series[0].points[o.series[0].points.length-1][1]]; } return out;"
    r = _page_text(html, tmp_path, probe)
    # 1M before 2026-11-18 is 2026-10-18, a Sunday: base is Friday 2026-10-16
    for rng, base in (("1M", "2026-10-16"), ("3M", "2026-08-18"), ("1Y", "2025-11-18"), ("All", "2025-06-02")):
        note, first, last = r[rng]
        assert f"on {base}." in note, (rng, note)
        b = 1.0 + dates.index(base) * 0.001
        assert first == 0 and last == pytest.approx((1.0 + (len(dates) - 1) * 0.001) / b - 1)


@requires_chrome
def test_month_end_ranges_clamp_to_shorter_months(tmp_path) -> None:
    dates = _weekdays("2025-12-01", "2026-03-31")
    html = load_script(SCRIPT).build(SNAP, None, _custom(dates, lambda d: 1.0))
    r = _page_text(html, tmp_path, CAPTURE + "[...document.querySelectorAll('#perf-ranges button')].find(b=>b.dataset.range==='1M').click();" + DRAWN)
    assert "on 2026-02-27." in r["note"]  # Mar 31 - 1M is Feb 28 (a Saturday), not Mar 3
    leap = [(date(2027, 1, 1) + timedelta(days=i)).isoformat() for i in range(425)]
    leap = leap[:leap.index("2028-02-29") + 1]
    html = load_script(SCRIPT).build(SNAP, None, _custom(leap, lambda d: 1.0))
    r = _page_text(html, tmp_path, CAPTURE + REDRAW + DRAWN)
    assert "on 2027-02-28." in r["note"]  # Feb 29 - 1Y is Feb 28, not Mar 1


@requires_chrome
def test_default_summary_agrees_with_headline(tmp_path) -> None:
    history = load_script("portfolio-analysis/scripts/history.py")
    days = _weekdays("2025-06-02", "2026-11-18")
    prices = {"AAPL": [{"date": d, "close": 100 + i * 0.05, "adj_close": 100 + i * 0.05} for i, d in enumerate(days)],
              "SPY": [{"date": d, "close": 400 + i * 0.3, "adj_close": 400 + i * 0.3} for i, d in enumerate(days)]}
    txns = [{"date": days[0], "type": "DEPOSIT", "amount": 1000.0, "account_id": "a"},
            {"date": days[0], "type": "BUY", "symbol": "AAPL", "units": 10.0, "amount": -1000.0, "account_id": "a"}]
    hist = history.run_history({"as_of": days[-1], "accounts": [{"account_id": "a", "cash": 0.0, "positions": [{"symbol": "AAPL", "units": 10.0}]}],
                                "transactions": txns, "prices": prices, "benchmarks": ["SPY"]})
    h = next(s for s in hist["series"] if s["key"] == "combined")["headline"]
    assert h["range"] == "1Y"
    r = _page_text(load_script(SCRIPT).build(SNAP, None, hist), tmp_path, CAPTURE + REDRAW + DRAWN)
    assert f"on {h['start']}." in r["note"]
    assert f"Your portfolio +{h['portfolio_return'] * 100:.1f}%" in r["sum"] and f"S&P 500 +{h['spy_return'] * 100:.1f}%" in r["sum"]
    assert r["lines"][0][2] == pytest.approx(h["portfolio_return"], abs=1e-6) and r["lines"][1][2] == pytest.approx(h["spy_return"], abs=1e-6)


@requires_chrome
def test_empty_history_renders_message_from_flags(tmp_path) -> None:
    html = load_script(SCRIPT).build(SNAP, None, _history(series=False))
    r = _page_text(html, tmp_path, "return {sub:document.getElementById('perf-sub').textContent,chart:document.getElementById('perf-chart').innerHTML,"
                                   "flags:document.getElementById('flags').textContent}")
    assert "the ledger has no transactions" in r["sub"] and "statement import" in r["sub"] and r["chart"] == ""
    assert "LEDGER_EMPTY" in r["flags"]


@requires_chrome
def test_page_with_history_passes_help_audit(tmp_path) -> None:
    from page_dom import assert_page_help
    a = audit_html(load_script(SCRIPT).build(SNAP, None, _history()), tmp_path)
    assert_page_help(a)
    assert any(c["h2"].startswith("Performance vs. the market") for c in a["cards"])
