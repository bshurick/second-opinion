from __future__ import annotations

import json

from scripts_util import load_script, run_json
from second_opinion import market
from page_dom import assert_page_help, render_and_audit, requires_chrome


def test_fundamentals_script(monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "company_info", lambda s: {"symbol": s, "market_cap": 1})
    monkeypatch.setattr(market, "financials", lambda s, quarterly=False: {"symbol": s, "quarterly": quarterly, "income_statement": {}})
    rc, out = run_json(load_script("valuation/scripts/fundamentals.py"), ["aapl", "--quarterly"], capsys)
    assert rc == 0 and out["info"]["symbol"] == "AAPL" and out["statements"]["quarterly"] is True


def test_fundamentals_usage(capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/fundamentals.py"), [], capsys)
    assert rc == 2


def test_indices_script(monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "index_snapshot", lambda: {"as_of": "x", "indices": [], "sectors": [], "rates": []})
    rc, out = run_json(load_script("market-analysis/scripts/indices.py"), [], capsys)
    assert rc == 0 and out["as_of"] == "x"


def test_earnings_script(monkeypatch, capsys) -> None:
    events = {"AAPL": {"next_earnings": "2026-10-29", "next_ex_dividend": "2026-11-07"}, "MSFT": {"next_earnings": "2026-10-28", "next_ex_dividend": None}, "BRK": {"next_earnings": None, "next_ex_dividend": None}}
    monkeypatch.setattr(market, "next_events", lambda s: events[s])
    rc, out = run_json(load_script("market-analysis/scripts/earnings.py"), ["aapl", "MSFT", "BRK"], capsys)
    assert rc == 0 and out["as_of"]
    assert out["earnings"] == [
        {"symbol": "AAPL", "next_earnings_date": "2026-10-29", "next_ex_dividend": "2026-11-07"},
        {"symbol": "MSFT", "next_earnings_date": "2026-10-28", "next_ex_dividend": None},
    ]
    assert out["missing"] == ["BRK"]


def test_earnings_script_requires_a_symbol(capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/earnings.py"), [], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_earnings_script_rejects_invalid_symbol(capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/earnings.py"), ["AA PL"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_earnings_script_caps_symbols_at_20(monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "next_events", lambda s: {"next_earnings": None, "next_ex_dividend": None})
    rc, out = run_json(load_script("market-analysis/scripts/earnings.py"), [f"S{i}" for i in range(21)], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


INDICES = {
    "as_of": "2026-09-12T20:00:00Z",
    "indices": [{"symbol": "^GSPC", "name": "S&P 500", "last": 6500.12, "day_change_pct": 0.42, "week_change_pct": 1.1}, {"symbol": "^VIX", "name": "VIX", "last": 15.2, "day_change_pct": -3.0, "week_change_pct": -8.0}],
    "sectors": [{"symbol": "XLK", "name": "Technology", "last": 187.7, "day_change_pct": 0.8, "week_change_pct": 2.1}, {"symbol": "XLE", "name": "Energy", "last": 65.1, "day_change_pct": -1.2, "week_change_pct": -0.4}],
    "rates": [{"symbol": "^TNX", "name": "10-year Treasury", "last": 4.95, "day_change_pct": 0.1, "week_change_pct": 0.3}],
    "macro": {"gold": {"last": 3400.0, "day_change_pct": 0.2}, "dollar": {"last": 101.2, "day_change_pct": -0.1}, "oil": {"last": 70.5, "day_change_pct": 1.4}, "bitcoin": {"last": 110000.0, "day_change_pct": 2.0}, "vix_3m": {"last": 17.0, "day_change_pct": -1.0}},
    "spreads": {"10y_13w": 0.7, "5y_13w": 0.4, "30y_5y": 0.6, "30y_13w": 1.0},
    "breadth": {"rsp_spy_1m": -0.5, "rsp_spy_3m": -1.2, "sectors_above_50sma": 7, "sectors_total": 11, "note": "proxy"},
    "vix_percentile_1y": 40.0,
}
FLOWS = {
    "as_of": "2026-09-14T15:00:00Z",
    "positioning": {"report_date": "2026-09-08", "weeks": 52, "missing": ["124603"], "contracts": [
        {"code": "13874A", "name": "E-MINI S&P 500", "label": "S&P 500 e-mini", "group": "index", "report_date": "2026-09-08", "open_interest": 2071836, "open_interest_change": 24922, "weeks": 52, "weeks_behind": 0,
         "classes": {"asset_managers": {"long": 1153305, "short": 240944, "net": 912361, "net_change": -21819, "net_pct_oi": 44.0, "percentile": 23.5, "long_change": -3488, "short_change": 18331},
                     "leveraged_funds": {"long": 155517, "short": 496621, "net": -341104, "net_change": -23540, "net_pct_oi": -16.5, "percentile": 80.4, "long_change": -9794, "short_change": 13746},
                     "dealers": {"long": 213184, "short": 898526, "net": -685342, "net_change": 35405, "net_pct_oi": -33.1, "percentile": 50.0, "long_change": 11225, "short_change": -24180},
                     "other_reportables": {"long": 56464, "short": 68432, "net": -11968, "net_change": -6045, "net_pct_oi": -0.6, "percentile": 30.0, "long_change": -683, "short_change": 5362},
                     "small_traders": {"long": 263462, "short": 137409, "net": 126053, "net_change": 15999, "net_pct_oi": 6.1, "percentile": 76.5, "long_change": 6763, "short_change": -9236}},
         "history": [{"date": "2026-09-01", "open_interest": 2046914, "asset_managers": 934180, "leveraged_funds": -317564, "dealers": -720747, "other_reportables": -5923, "small_traders": 110054},
                     {"date": "2026-09-08", "open_interest": 2071836, "asset_managers": 912361, "leveraged_funds": -341104, "dealers": -685342, "other_reportables": -11968, "small_traders": 126053}]},
        {"code": "13874I", "name": "E-MINI S&P TECHNOLOGY INDEX", "label": "Technology sector", "group": "sector", "report_date": "2026-09-08", "open_interest": 13222, "open_interest_change": 786, "weeks": 52, "weeks_behind": 0,
         "classes": {"asset_managers": {"long": 9000, "short": 826, "net": 8174, "net_change": 310, "net_pct_oi": 61.8, "percentile": 5.9, "long_change": 1, "short_change": 2},
                     "leveraged_funds": {"long": 100, "short": 131, "net": -31, "net_change": -37, "net_pct_oi": -0.2, "percentile": 52.9, "long_change": 0, "short_change": 0},
                     "dealers": {"long": 10, "short": 5000, "net": -4990, "net_change": 0, "net_pct_oi": -37.7, "percentile": 10.0, "long_change": 0, "short_change": 0},
                     "other_reportables": {"long": 0, "short": 0, "net": 0, "net_change": 0, "net_pct_oi": 0.0, "percentile": 50.0, "long_change": 0, "short_change": 0},
                     "small_traders": {"long": 2500, "short": 47, "net": 2453, "net_change": 100, "net_pct_oi": 18.6, "percentile": 80.4, "long_change": 0, "short_change": 0}}},
        {"code": "13874R", "name": "E-MINI S&P REAL ESTATE </script> INDEX", "label": "Real estate sector", "group": "sector", "report_date": "2025-09-16", "open_interest": 18459, "open_interest_change": 0, "weeks": 2, "weeks_behind": 51,
         "classes": {k: {"long": 1, "short": 0, "net": 1, "net_change": None, "net_pct_oi": 0.0, "percentile": None, "long_change": None, "short_change": None} for k in ("asset_managers", "leveraged_funds", "dealers", "other_reportables", "small_traders")}},
    ]},
    "etf_flows": {"as_of": "2026-09-11", "unavailable": [], "series_file": "/data/etf-shares.json", "funds": [
        {"ticker": "XLK", "name": "Technology", "as_of": "2026-09-11", "nav": 187.73, "aum_usd": 121839350000.0, "shares": 649013743, "observations": 3, "first_observation": "2026-09-09", "flow_1d_usd": 375460000.0, "flow_1d_pct_aum": 0.31, "flow_1d_span_days": 1, "flow_5d_usd": 500000000.0, "flow_5d_pct_aum": 0.41, "flow_20d_usd": 500000000.0, "flow_20d_pct_aum": 0.41},
        {"ticker": "XLE", "name": "Energy", "as_of": "2026-09-11", "nav": 65.14, "aum_usd": 42699710000.0, "shares": 655506755, "observations": 1, "first_observation": "2026-09-11", "flow_1d_usd": None, "flow_1d_pct_aum": None, "flow_1d_span_days": None, "flow_5d_usd": None, "flow_5d_pct_aum": None, "flow_20d_usd": None, "flow_20d_pct_aum": None},
    ]},
    "cash": {"series": "WRMFNS", "name": "Retail Money Market Funds", "unit": "billions of dollars, weekly", "latest": 3009.1, "date": "2026-08-03", "change_1w": -6.1, "change_4w": -13.7, "change_13w": -20.0, "change_52w": -5.9, "change_52w_pct": -0.2, "observations": [{"date": "2026-07-27", "value": 3015.2}, {"date": "2026-08-03", "value": 3009.1}]},
    "short_volume": {"days": 20, "symbols": [{"symbol": "AAPL", "date": "2026-09-11", "short_ratio": 43.9, "short_ratio_avg": 41.2, "ratio_vs_avg": 2.7, "short_volume": 343107.0, "total_volume": 782289.0, "days": 20}]},
    "sources": {"positioning": "CFTC", "etf_flows": "SSGA", "cash": "FRED", "short_volume": "FINRA"},
    "notes": ["Positioning is futures only."],
}


def test_market_render_builds_a_page_from_indices_and_flows(tmp_path, capsys) -> None:
    import json

    (tmp_path / "indices.json").write_text(json.dumps(INDICES))
    (tmp_path / "flows.json").write_text(json.dumps(FLOWS))
    out = tmp_path / "market.html"
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--indices", str(tmp_path / "indices.json"), "--in", str(tmp_path / "flows.json"), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Market Flows", "indices": 2, "contracts": 3, "funds": 2, "flags": 1}
    html = out.read_text()
    assert html.startswith("<title>Market Flows</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and "const FA" in html and '"flows"' in html and '"indices"' in html
    assert "</script> INDEX" not in html and "<\\/script> INDEX" in html
    assert "S&amp;P 500 6,500.12 (+0.4%) · VIX 15.2 (1y percentile 40) · 10y 4.95% · positioning as of 2026-09-08 · ETF flows as of 2026-09-11 · retail money funds $3,009B (2026-08-03)" in html
    for section in ("Indices", "Positioning", "Crowdedness", "Sectors", "ETF flows", "Cash on the sidelines", "Short volume", "Flags", "not financial advice"):
        assert section in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "http" not in html.split("</style>")[1].split("<script>")[0]
    assert 'id="explain"' in html and "FA.explain(" in html and "FA.term(" in html
    assert "weekly" in html and "monthly" not in html.split("<script>")[0]


def test_market_render_leaves_out_a_yield_the_source_did_not_deliver(tmp_path, capsys) -> None:
    import json

    indices = {**INDICES, "rates": [{"symbol": "^TNX", "name": "10-year Treasury", "last": None, "day_change_pct": None, "week_change_pct": None}]}
    (tmp_path / "indices.json").write_text(json.dumps(indices))
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--indices", str(tmp_path / "indices.json"), "--out", str(tmp_path / "c.html")], capsys)
    html = (tmp_path / "c.html").read_text()
    assert rc == 0 and "10y" not in html.split("<script>")[0].split('id="asof"')[1].split("</p>")[0]


def test_market_render_accepts_either_input_alone(tmp_path, capsys) -> None:
    import json

    (tmp_path / "flows.json").write_text(json.dumps({k: v for k, v in FLOWS.items() if k != "short_volume"}))
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--in", str(tmp_path / "flows.json"), "--out", str(tmp_path / "a.html")], capsys)
    assert rc == 0 and res["indices"] == 0 and res["contracts"] == 3
    html = (tmp_path / "a.html").read_text()
    assert "positioning as of 2026-09-08" in html and "S&amp;P 500 6,500" not in html
    (tmp_path / "indices.json").write_text(json.dumps(INDICES))
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--indices", str(tmp_path / "indices.json"), "--out", str(tmp_path / "b.html")], capsys)
    assert rc == 0 and res["contracts"] == 0 and res["indices"] == 2


def test_market_render_rejects_wrong_or_missing_input(tmp_path, capsys) -> None:
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "--in" in res["error"]
    (tmp_path / "bad.json").write_text('{"portfolio": 1}')
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--in", str(tmp_path / "bad.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "flows.py result" in res["error"]
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--indices", str(tmp_path / "bad.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "indices.py result" in res["error"]
    rc, res = run_json(load_script("market-analysis/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


# --- indicators.py ------------------------------------------------------------------
# Full-text literals, not anchors: an anchor cannot see a sentence added beside intact
# wording, which is how a trade signal would arrive in a skill that may never give one.
INDICATOR_MEANINGS = {
    "curve_10y_3m": (
        "The 10-year yield minus the 3-month bill. It goes negative when short rates are above "
        "long ones, which has preceded every US recession since 1970 with a lag of roughly one to "
        "two years — a lag long and variable enough that the sign is context, not timing."
    ),
    "curve_10y_2y": (
        "The 10-year yield minus the 2-year. The same shape read against a maturity the market "
        "trades more heavily than the bill, so it turns earlier and is noisier."
    ),
    "vix": (
        "The VIX, ranked against its whole history rather than the trailing year that "
        "indices.py reports. A high rank is fear already priced, not fear to come; a low rank is "
        "calm already priced."
    ),
    "financial_conditions": (
        "The Chicago Fed's National Financial Conditions Index, a weekly summary of money, debt "
        "and equity markets. Zero is the historical average: positive is tighter than average, "
        "negative is looser."
    ),
}


def _fake_fred(monkeypatch, series_values):
    """Deterministic FRED: each series id maps to a list of daily values."""
    from second_opinion import fred

    def observations(series_id, n):
        vals = series_values[series_id]
        return [{"date": f"2020-01-{i + 1:02d}", "value": v} for i, v in enumerate(vals)]

    monkeypatch.setattr(fred, "observations", observations)


def test_indicators_ranks_each_series_against_its_own_history(monkeypatch, capsys) -> None:
    _fake_fred(monkeypatch, {
        "T10Y3M": [1.0, 2.0, 3.0, 4.0],      # latest 4.0 -> 3 of 4 below -> 75th
        "T10Y2Y": [5.0, 1.0, 2.0, 3.0],      # latest 3.0 -> 2 of 4 below -> 50th
        "VIXCLS": [10.0, 20.0, 30.0, 15.0],  # latest 15.0 -> 1 of 4 below -> 25th
        "NFCI":   [-1.0, 0.0, 1.0, -0.5],    # latest -0.5 -> 1 of 4 below -> 25th
    })
    rc, out = run_json(load_script("market-analysis/scripts/indicators.py"), [], capsys)
    assert rc == 0
    i = out["indicators"]
    assert i["curve_10y_3m"]["value"] == 4.0 and i["curve_10y_3m"]["percentile"] == 75
    assert i["curve_10y_2y"]["value"] == 3.0 and i["curve_10y_2y"]["percentile"] == 50
    assert i["vix"]["value"] == 15.0 and i["vix"]["percentile"] == 25
    assert i["financial_conditions"]["value"] == -0.5 and i["financial_conditions"]["percentile"] == 25
    # median, history_from and observations travel with every reading
    assert i["curve_10y_3m"]["median"] == 2.5
    assert i["curve_10y_3m"]["history_from"] == "2020-01-01"
    assert i["curve_10y_3m"]["observations"] == 4


def test_indicators_emits_every_meaning_verbatim(monkeypatch, capsys) -> None:
    _fake_fred(monkeypatch, {k: [1.0, 2.0] for k in ("T10Y3M", "T10Y2Y", "VIXCLS", "NFCI")})
    rc, out = run_json(load_script("market-analysis/scripts/indicators.py"), [], capsys)
    assert rc == 0
    for key, text in INDICATOR_MEANINGS.items():
        assert out["indicators"][key]["meaning"] == text


def test_indicators_reads_as_no_call(monkeypatch, capsys) -> None:
    # The skill's unbreakable rule. Ranking today against history is describable; a call is not.
    _fake_fred(monkeypatch, {k: [1.0, 2.0] for k in ("T10Y3M", "T10Y2Y", "VIXCLS", "NFCI")})
    rc, out = run_json(load_script("market-analysis/scripts/indicators.py"), [], capsys)
    blob = json.dumps(out).lower()
    for word in ("recommend", "advise", "should", "suggest", "you buy", "you sell"):
        assert word not in blob, f"output contains {word!r}"


def test_indicators_key_sets_are_exactly_these(monkeypatch, capsys) -> None:
    # A value-level pin cannot see a key that did not exist.
    _fake_fred(monkeypatch, {k: [1.0, 2.0] for k in ("T10Y3M", "T10Y2Y", "VIXCLS", "NFCI")})
    rc, out = run_json(load_script("market-analysis/scripts/indicators.py"), [], capsys)
    assert tuple(sorted(out)) == ("as_of", "indicators", "note")
    assert tuple(sorted(out["indicators"])) == (
        "curve_10y_2y", "curve_10y_3m", "financial_conditions", "vix",
    )
    assert tuple(sorted(out["indicators"]["vix"])) == (
        "history_from", "label", "meaning", "median", "observations",
        "percentile", "series", "value",
    )


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    import json

    (tmp_path / "indices.json").write_text(json.dumps(INDICES))
    (tmp_path / "flows.json").write_text(json.dumps(FLOWS))
    a = render_and_audit("market-analysis/scripts/render.py", ["--indices", str(tmp_path / "indices.json"), "--in", str(tmp_path / "flows.json")], tmp_path, capsys)
    assert_page_help(a)
