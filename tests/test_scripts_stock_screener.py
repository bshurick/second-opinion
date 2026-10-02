"""stock-screener: screen.py assembles EDGAR frames into screen_math's input and prices the survivors.

No network: frames, the ticker list and quotes are faked.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys

import pytest

from scripts_util import load_script, run_json
from page_dom import assert_page_help, render_and_audit, requires_chrome

SCREEN = load_script("stock-screener/scripts/screen.py")
MATH = load_script("stock-screener/scripts/screen_math.py")
LOOKBACK = load_script("stock-screener/scripts/lookback.py")
TODAY = dt.date(2026, 9, 27)
YEARS = [2022, 2023, 2024, 2025]
NAMES = {1: {"ticker": "GROW", "title": "Grower Inc"}, 2: {"ticker": "SLOW", "title": "Slow Co"}, 3: {"ticker": "BANK", "title": "Bank Corp"}}
NO_MOMENTUM = lambda tickers, today: {}  # noqa: E731 -- the real one downloads from Yahoo


def _fake_frames():
    """GROW: +30%/yr; SLOW: +5%/yr; BANK: +30%/yr but Yahoo files it under financials.
    GROW changed revenue concepts: Revenues in 2022 only, the ASC 606 concept after, so its
    series has to be stitched from both. SLOW tags capital spending as productive assets."""
    rev = {1: [1000e6, 1300e6, 1690e6, 2197e6], 2: [1000e6, 1050e6, 1100e6, 1160e6], 3: [1000e6, 1300e6, 1690e6, 2197e6]}
    f: dict[tuple[str, str], list] = {}

    def put(concept, period, cik, val):
        f.setdefault((concept, period), []).append({"cik": cik, "val": val})

    for cik, series in rev.items():
        for y, v in zip(YEARS, series):
            if cik == 1 and y > 2022:
                put("RevenueFromContractWithCustomerExcludingAssessedTax", f"CY{y}", cik, v)
            else:
                put("Revenues", f"CY{y}", cik, v)
            put("GrossProfit", f"CY{y}", cik, 0.7 * v)
            put("OperatingIncomeLoss", f"CY{y}", cik, v * (0.05 + 0.03 * (y - 2022)))
            put("NetIncomeLoss", f"CY{y}", cik, 0.1 * v)
            put("NetCashProvidedByUsedInOperatingActivities", f"CY{y}", cik, 0.25 * v)
            put("PaymentsToAcquireProductiveAssets" if cik == 2 else "PaymentsToAcquirePropertyPlantAndEquipment", f"CY{y}", cik, 0.03 * v)
            put("ShareBasedCompensation", f"CY{y}", cik, 0.04 * v)
            put("WeightedAverageNumberOfDilutedSharesOutstanding", f"CY{y}", cik, 100e6 * (1.01 ** (y - 2022)))
        put("StockholdersEquity", "CY2025Q4I", cik, 2000e6)
        put("LongTermDebtNoncurrent", "CY2025Q4I", cik, 200e6)
        put("Assets", "CY2025Q4I", cik, 3000e6)
        put("Assets", "CY2024Q4I", cik, 2600e6)
        put("AssetsCurrent", "CY2025Q4I", cik, 1200e6)
        put("LiabilitiesCurrent", "CY2025Q4I", cik, 500e6)
        put("CashAndCashEquivalentsAtCarryingValue", "CY2025Q4I", cik, 300e6)
        concept = "RevenueFromContractWithCustomerExcludingAssessedTax" if cik == 1 else "Revenues"
        put(concept, "CY2026Q2", cik, 650e6)
        put(concept, "CY2025Q2", cik, 500e6)
    return f


@pytest.fixture
def frames():
    data = _fake_frames()
    calls = []

    def frame(concept, period, unit="USD", taxonomy="us-gaap"):
        calls.append((concept, period, unit))
        return data.get((concept, period), [])

    frame.calls = calls
    frame.data = data
    return frame


def quoter(ticker):
    return {
        "GROW": {"market_cap": 3e9, "enterprise_value": 3e9, "price": 30.0, "sector": "Technology", "financial": False},
        "BANK": {"market_cap": 3e9, "enterprise_value": 3e9, "price": 30.0, "sector": "Financial Services", "financial": True},
    }.get(ticker)


def _ns(*argv):
    return SCREEN.parser().parse_args(list(argv))


def _run(frames, *argv, **kw):
    kw.setdefault("quoter", quoter)
    return SCREEN.run(_ns(*argv), frame=frames, today=TODAY, names=NAMES, momentum_of=kw.pop("momentum_of", NO_MOMENTUM), **kw)


def test_quarter_periods_allow_for_the_filing_lag() -> None:
    assert SCREEN.quarter_periods(TODAY) == [("CY2026Q2", "CY2025Q2"), ("CY2026Q1", "CY2025Q1")]
    assert SCREEN.quarter_periods(dt.date(2026, 2, 10)) == [("CY2025Q3", "CY2024Q3"), ("CY2025Q2", "CY2024Q2")]


def test_build_companies_stitches_revenue_across_concepts(frames) -> None:
    cos = {c["ticker"]: c for c in SCREEN.build_companies(frames, YEARS, SCREEN.quarter_periods(TODAY), NAMES)}
    assert cos["GROW"]["annual"]["revenue"] == {"2022": 1000e6, "2023": 1300e6, "2024": 1690e6, "2025": 2197e6}
    assert cos["GROW"]["quarter"] == {"revenue": 650e6, "revenue_year_ago": 500e6, "period": "CY2026Q2"}
    assert cos["GROW"]["balance"] == {"equity": 2000e6, "assets": 3000e6, "current_assets": 1200e6, "current_liabilities": 500e6, "debt": 200e6, "cash": 300e6}
    assert cos["GROW"]["balance_prior"] == {"assets": 2600e6, "current_assets": None, "current_liabilities": None, "debt": None}
    assert cos["GROW"]["financial"] is False
    assert ("WeightedAverageNumberOfDilutedSharesOutstanding", "CY2025", "shares") in frames.calls


def test_each_frame_is_fetched_once(frames) -> None:
    SCREEN.build_companies(frames, YEARS, SCREEN.quarter_periods(TODAY), NAMES)
    assert len(frames.calls) == len(set(frames.calls))


def test_capex_adds_software_and_falls_back_to_other_concepts(frames) -> None:
    frames.data[("PaymentsToDevelopSoftware", "CY2025")] = [{"cik": 1, "val": 10e6}]
    cos = {c["ticker"]: c for c in SCREEN.build_companies(frames, YEARS, SCREEN.quarter_periods(TODAY), NAMES)}
    assert cos["GROW"]["annual"]["capex"]["2025"] == pytest.approx(0.03 * 2197e6 + 10e6)
    assert cos["SLOW"]["annual"]["capex"]["2025"] == pytest.approx(0.03 * 1160e6)  # productive-assets concept
    del frames.data[("PaymentsToAcquireProductiveAssets", "CY2025")]
    cos = {c["ticker"]: c for c in SCREEN.build_companies(frames, YEARS, SCREEN.quarter_periods(TODAY), NAMES)}
    assert "2025" not in cos["SLOW"]["annual"]["capex"]  # unknown, never zero


def test_debt_is_the_largest_total_plus_short_term_borrowings(frames) -> None:
    frames.data[("LongTermDebt", "CY2025Q4I")] = [{"cik": 1, "val": 260e6}]            # includes the current part
    frames.data[("LongTermDebtCurrent", "CY2025Q4I")] = [{"cik": 1, "val": 50e6}, {"cik": 2, "val": 50e6}]
    frames.data[("ShortTermBorrowings", "CY2025Q4I")] = [{"cik": 1, "val": 40e6}]
    frames.data[("ShortTermInvestments", "CY2025Q4I")] = [{"cik": 1, "val": 100e6}]
    cos = {c["ticker"]: c for c in SCREEN.build_companies(frames, YEARS, SCREEN.quarter_periods(TODAY), NAMES)}
    assert cos["GROW"]["balance"]["debt"] == 300e6 and cos["GROW"]["balance"]["cash"] == 400e6
    assert cos["SLOW"]["balance"]["debt"] == 250e6  # noncurrent + current


def test_a_filer_reporting_deposits_is_financial_and_never_priced(frames) -> None:
    frames.data[("Deposits", "CY2025Q4I")] = [{"cik": 3, "val": 9e9}]
    asked = []

    def spy(ticker):
        asked.append(ticker)
        return quoter(ticker)

    out = _run(frames, quoter=spy)
    assert asked == ["GROW"] and out["funnel"][1] == {"stage": "financial_filer", "remaining": 2}
    assert [s["ticker"] for s in out["survivors"]] == ["GROW"]


def test_growth_screen_end_to_end(frames) -> None:
    out = _run(frames, momentum_of=lambda tickers, today: {"GROW": 0.4, "BANK": -0.3})
    assert out["universe"] == 3
    assert [s["ticker"] for s in out["survivors"]] == ["GROW"]  # SLOW fails growth, BANK is financial
    assert out["priced"] == {"count": 2, "of": 2, "limit": 400}
    m = out["survivors"][0]["metrics"]
    assert m["implied_growth"] is not None and m["momentum"] == 0.4 and m["sector"] == "Technology"
    assert "companies" not in out and out["latest_quarter_periods"] == ["CY2026Q2", "CY2026Q1"]
    assert out["funnel"][0] == {"stage": "universe", "remaining": 3}
    assert out["coverage"] == {"2022": 3, "2023": 3, "2024": 3, "2025": 3}


def test_a_thin_latest_year_is_flagged(frames) -> None:
    for concept in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"):
        frames.data[(concept, "CY2025")] = [r for r in frames.data.get((concept, "CY2025"), []) if r["cik"] == 1]
    out = _run(frames, "--no-price")
    flag = next(f for f in out["flags"] if f["code"] == "LATEST_YEAR_THIN")
    assert "only 1 companies" in flag["message"] and "--year 2024" in flag["message"] and out["universe"] == 1


def test_held_symbols_are_marked_and_can_be_left_out(frames) -> None:
    out = _run(frames, "--held", "grow, MSFT")
    assert out["held"] == {"given": 2, "matched": 1, "survivors_held": ["GROW"], "excluded": False}
    assert out["survivors"][0]["held"] is True
    out = _run(frames, "--held", "GROW", "--exclude-held")
    assert out["survivors"] == [] and out["held"]["excluded"] is True
    with pytest.raises(SCREEN.InvalidInput, match="--held"):
        _run(frames, "--exclude-held")


def test_set_overrides_and_switches_off(frames) -> None:
    out = _run(frames, "--set", "min_revenue_cagr=0.03", "--set", "min_latest_year_growth=none", "--set", "min_growth_each_year=0.04", "--no-price")
    assert out["criteria"]["min_revenue_cagr"] == 0.03 and out["criteria"]["min_latest_year_growth"] is None
    assert {s["ticker"] for s in out["survivors"]} == {"GROW", "SLOW", "BANK"}
    assert out["priced"]["count"] == 0


def test_unpriced_survivors_are_flagged(frames) -> None:
    out = _run(frames, "--set", "min_revenue_cagr=0.03", "--set", "min_latest_year_growth=none", "--set", "min_growth_each_year=0.04")
    codes = [f["code"] for f in out["flags"]]
    assert "UNPRICED" in codes and "SLOW" in next(f["message"] for f in out["flags"] if f["code"] == "UNPRICED")


def test_momentum_skips_the_latest_month() -> None:
    closes = [100.0] * 100 + [float(100 + i) for i in range(1, 201)]  # 300 bars ending at 300
    assert SCREEN.momentum_from_closes(closes) == pytest.approx(closes[-22] / closes[-253] - 1)
    assert SCREEN.momentum_from_closes(closes[:200]) is None


def _bars(start: dt.date, days: int, first: float, last: float) -> list[dict]:
    step = (last - first) / (days - 1)
    return [{"date": (start + dt.timedelta(days=i)).isoformat(), "close": round(first + step * i, 4), "adj_close": round(first + step * i, 4), "volume": 1} for i in range(days)]


def test_lookback_prices_the_past_screen_and_reports_what_happened(frames) -> None:
    """Screen dated 2026-07-01 on fiscal 2025, looked back from a year later."""
    today = dt.date(2027, 7, 1)
    start = dt.date(2025, 4, 1)
    days = (today - start).days + 1
    at = (dt.date(2026, 7, 1) - start).days
    grow, spy = _bars(start, days, 10.0, 60.0), _bars(start, days, 100.0, 120.0)

    def hist(tickers, since):
        assert since < "2025-07-01"
        return {"GROW": grow, "SPY": spy}

    ns = LOOKBACK.parser().parse_args(["--year", "2025"])
    out = LOOKBACK.run(ns, frame=frames, quoter=quoter, today=today, names=NAMES, history_of=hist)
    assert out["screen_date"] == "2026-07-01" and out["years"] == YEARS and out["years_held"] == 1.0
    s = out["survivors"][0]
    assert s["ticker"] == "GROW" and s["rank"] == 1
    assert s["forward_return"] == pytest.approx(60.0 / grow[at]["close"] - 1, abs=1e-4) and s["beat_benchmark"] is True
    assert s["metrics"]["market_cap"] == pytest.approx(3e9 * grow[at]["close"] / 60.0)  # scaled back to the screen date
    assert out["benchmark"]["symbol"] == "SPY" and out["benchmark"]["return"] == pytest.approx(120.0 / spy[at]["close"] - 1, abs=1e-4)
    assert out["summary"]["survivors"] == 1 and out["summary"]["beat_benchmark_share"] == 1.0 and out["summary"]["rank_correlation"] is None
    assert {"ONE_PERIOD", "SURVIVORSHIP", "APPROXIMATE_VALUE", "SMALL_SAMPLE"} <= {f["code"] for f in out["flags"]}


def test_lookback_leaves_out_companies_with_no_price_on_the_screen_date(frames) -> None:
    today = dt.date(2027, 7, 1)
    late = _bars(dt.date(2026, 9, 1), 300, 10.0, 20.0)  # listed after the screen date
    ns = LOOKBACK.parser().parse_args(["--year", "2025"])
    out = LOOKBACK.run(ns, frame=frames, quoter=quoter, today=today, names=NAMES, history_of=lambda t, s: {"GROW": late})
    assert out["survivors"] == [] and out["priced"]["count"] == 0 and out["benchmark"]["return"] is None
    assert "NO_BENCHMARK" in {f["code"] for f in out["flags"]}


def test_lookback_rejects_a_future_screen_date(frames) -> None:
    ns = LOOKBACK.parser().parse_args(["--year", "2026"])
    with pytest.raises(LOOKBACK.InvalidInput, match="future"):
        LOOKBACK.run(ns, frame=frames, quoter=quoter, today=TODAY, names=NAMES, history_of=lambda t, s: {})


def test_rank_correlation() -> None:
    assert LOOKBACK.rank_correlation([0.5, 0.4, 0.3, 0.2, 0.1]) == 1.0
    assert LOOKBACK.rank_correlation([0.1, 0.2, 0.3, 0.4, 0.5]) == -1.0
    assert LOOKBACK.rank_correlation([0.1, 0.2]) is None


def test_bad_set_and_unknown_criterion_exit_2(frames, capsys, monkeypatch) -> None:
    monkeypatch.setattr(SCREEN.edgar, "frame", frames)
    monkeypatch.setattr(SCREEN.edgar, "tickers", lambda: NAMES)
    rc, out = run_json(SCREEN, ["--set", "nonsense"], capsys)
    assert rc == 2 and "KEY=VALUE" in out["error"]
    rc, out = run_json(SCREEN, ["--set", "min_vibes=1", "--no-price"], capsys)
    assert rc == 2 and "unknown criterion" in out["error"]


def test_math_script_reads_stdin(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([])))
    with pytest.raises(SystemExit) as exc:
        MATH.main()
    assert exc.value.code == 2 and "error" in json.loads(capsys.readouterr().out)


def test_render_builds_a_page_from_a_screen_result(frames, tmp_path, capsys) -> None:
    result = _run(frames)
    src = tmp_path / "screen.json"
    src.write_text(json.dumps(result))
    render = load_script("stock-screener/scripts/render.py")
    rc, out = run_json(render, ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0 and out["survivors"] == 1 and out["universe"] == 3
    html = (tmp_path / "p.html").read_text()
    assert "window.DATA" in html and "Stock Screener — growth" in html


def test_render_rejects_a_non_screen_input(tmp_path, capsys) -> None:
    src = tmp_path / "x.json"
    src.write_text(json.dumps({"symbol": "BND"}))
    rc, out = run_json(load_script("stock-screener/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "screen.py result" in out["error"]


@requires_chrome
def test_every_card_explains_itself(frames, tmp_path, capsys) -> None:
    result = _run(frames)
    src = tmp_path / "screen.json"
    src.write_text(json.dumps(result))
    assert_page_help(render_and_audit("stock-screener/scripts/render.py", ["--in", str(src)], tmp_path, capsys))
