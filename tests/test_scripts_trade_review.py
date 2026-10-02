from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from scripts_util import load_script, run_json
from second_opinion import ledger, market
from page_dom import assert_page_help, render_and_audit, requires_chrome


def _t(d: str, kind: str, symbol: str, units, price, amount, account="a", fee=0.0) -> dict:
    return {"date": d, "type": kind, "symbol": symbol, "units": units, "price": price, "amount": amount, "fee": fee, "reinvested": False, "description": kind, "security_name": None, "account_id": account, "source_id": d}


LEDGER = [
    _t("2025-01-02", "BUY", "AAPL", 10, 100.0, -1000.0),
    _t("2025-04-01", "SELL", "AAPL", 10, 130.0, 1300.0),
    _t("2025-05-01", "BUY", "XYZ", 10, 50.0, -500.0, account="b"),
]


def _flat(price: float, start: str = "2024-01-01", end: str = "2025-12-31") -> list[dict]:
    d, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= last:
        if d.weekday() < 5:
            out.append({"date": d.isoformat(), "close": price, "adj_close": price})
        d += timedelta(days=1)
    return out


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    book = ledger.load(tmp_path / "ledger.json")
    ledger.merge(book, LEDGER, source="test")
    ledger.save(book, tmp_path / "ledger.json")
    return tmp_path


@pytest.fixture
def yahoo(monkeypatch):
    calls: list[dict] = []

    def close_histories(symbols, start):
        calls.append({"symbols": list(symbols), "start": start})
        return {s: _flat({"AAPL": 110.0, "XYZ": 30.0, "SPY": 400.0, "VTI": 200.0}[s]) for s in symbols}

    monkeypatch.setattr(market, "close_histories", close_histories)
    return calls


def test_run_review_reads_ledger_fetches_prices_and_benchmark(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--as-of", "2025-12-31"], capsys)
    assert rc == 0, out
    assert out["summary"]["round_trips"] == 1 and out["summary"]["realized_pnl"] == 300.0
    assert out["counterfactual"]["benchmark_symbol"] == "SPY" and out["open_lots"][0]["symbol"] == "XYZ"
    assert yahoo == [{"symbols": ["AAPL", "SPY", "XYZ"], "start": "2023-11-29"}]  # first trade minus 400 days (2024 is a leap year)
    assert out["sources"] == {"ledger": str(data_dir / "ledger.json"), "prices": "yahoo", "benchmark": "SPY"}
    assert out["ledger"] == {"transactions_used": 3, "accounts": ["a", "b"], "date_range": {"start": "2025-01-02", "end": "2025-05-01"}}


def test_run_review_filters_and_benchmark_override(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--account", "a", "--benchmark", "vti", "--as-of", "2025-12-31"], capsys)
    assert rc == 0 and out["ledger"]["accounts"] == ["a"] and out["counterfactual"]["benchmark_symbol"] == "VTI"
    assert yahoo[0]["symbols"] == ["AAPL", "VTI"]
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--symbol", "xyz", "--as-of", "2025-12-31"], capsys)
    assert rc == 0 and out["summary"]["round_trips"] == 0 and out["open_lots"][0]["symbol"] == "XYZ"
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--start", "2025-03-01", "--as-of", "2025-12-31"], capsys)
    assert rc == 0 and out["unmatched_sells"] == [{"symbol": "AAPL", "account_id": "a", "date": "2025-04-01", "units": 10.0}]


def test_run_review_no_prices_flag_skips_yahoo(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--no-prices", "--as-of", "2025-12-31"], capsys)
    assert rc == 0 and yahoo == [] and out["sources"]["prices"] is None and out["missing_prices"] == ["AAPL", "XYZ"]


def test_run_review_empty_ledger_exit_2(tmp_path, monkeypatch, yahoo, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), [], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "import-csv.py" in out["error"]


def test_run_review_yahoo_failure_degrades(data_dir, monkeypatch, capsys) -> None:
    def boom(symbols, start):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "close_histories", boom)
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--as-of", "2025-12-31"], capsys)
    assert rc == 0 and out["sources"]["prices"] is None and out["summary"]["round_trips"] == 1
    assert {"code": "PRICES_UNAVAILABLE", "message": "Yahoo prices failed (yahoo down); drift, context and counterfactuals are unavailable"} in out["flags"]


def test_run_review_writes_report_file(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--as-of", "2025-12-31", "--save"], capsys)
    assert rc == 0 and out["report_path"] == str(data_dir / "trade-review-2025-12-31.json")
    assert json.loads((data_dir / "trade-review-2025-12-31.json").read_text())["summary"]["round_trips"] == 1


# ---------------------------------------------------------------------------
# --research-top, largest_buys (run-review.py) and the new review.py blocks
# ---------------------------------------------------------------------------

TRUNCATION_LEDGER = [
    _t("2025-01-02", "BUY", "AAPL", 10, 100.0, -1000.0),
    _t("2025-04-01", "SELL", "AAPL", 10, 130.0, 1300.0),  # +300, biggest gain
    _t("2025-01-05", "BUY", "AAPL", 5, 120.0, -600.0),  # second-largest AAPL buy
    _t("2025-02-03", "BUY", "MSFT", 10, 200.0, -2000.0),
    _t("2025-05-03", "SELL", "MSFT", 10, 150.0, 1500.0),  # -500, largest loss
    _t("2025-03-03", "BUY", "TINY", 1, 10.0, -10.0),
    _t("2025-06-03", "SELL", "TINY", 1, 11.0, 11.0),  # +1
]


def _seed(tmp_path, rows):
    from second_opinion import ledger as ledger_lib

    book = ledger_lib.load(tmp_path / "ledger.json")
    ledger_lib.merge(book, rows, source="test")
    ledger_lib.save(book, tmp_path / "ledger.json")


def _any_flat(symbols, start):
    return {s: _flat(10.0) for s in symbols}


def test_run_review_research_top_truncates_by_abs_pnl(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    _seed(tmp_path, TRUNCATION_LEDGER)
    monkeypatch.setattr(market, "close_histories", _any_flat)
    mod = load_script("trade-review/scripts/run-review.py")
    argv = ["--as-of", "2025-12-31"]
    rc, out = run_json(mod, argv, capsys)
    assert rc == 0 and [q["symbol"] for q in out["research_queue"]] == ["AAPL", "MSFT", "TINY"]
    assert all("first_buy_date" in q for q in out["research_queue"])
    rc, out = run_json(mod, argv + ["--research-top", "2"], capsys)
    # top 2 by |total_pnl|: MSFT (500) then AAPL (300)
    assert rc == 0 and [q["symbol"] for q in out["research_queue"]] == ["MSFT", "AAPL"]
    rc, out = run_json(mod, argv + ["--research-top", "0"], capsys)
    assert rc == 0 and out["research_queue"] == []
    rc, out = run_json(mod, argv + ["--research-top", "-1"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_run_review_largest_buys_per_symbol(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    _seed(tmp_path, TRUNCATION_LEDGER)
    monkeypatch.setattr(market, "close_histories", _any_flat)
    mod = load_script("trade-review/scripts/run-review.py")
    rc, out = run_json(mod, ["--as-of", "2025-12-31"], capsys)
    assert rc == 0 and out["largest_buys"] == [
        {"symbol": "AAPL", "date": "2025-01-02", "units": 10, "price": 100.0, "amount": -1000.0},
        {"symbol": "AAPL", "date": "2025-01-05", "units": 5, "price": 120.0, "amount": -600.0},
        {"symbol": "MSFT", "date": "2025-02-03", "units": 10, "price": 200.0, "amount": -2000.0},
        {"symbol": "TINY", "date": "2025-03-03", "units": 1, "price": 10.0, "amount": -10.0},
    ]
    rc, out = run_json(mod, ["--symbol", "msft", "--as-of", "2025-12-31"], capsys)
    assert rc == 0 and [b["symbol"] for b in out["largest_buys"]] == ["MSFT"]


def test_run_review_largest_buys_caps_at_25_symbols(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rows = [_t("2025-01-02", "BUY", f"S{i:02d}", 1, 10.0, -10.0) for i in range(30)]
    _seed(tmp_path, rows)
    monkeypatch.setattr(market, "close_histories", _any_flat)
    rc, out = run_json(load_script("trade-review/scripts/run-review.py"), ["--as-of", "2025-12-31"], capsys)
    assert rc == 0 and len(out["largest_buys"]) == 25
    assert [b["symbol"] for b in out["largest_buys"]] == sorted(f"S{i:02d}" for i in range(25))


def test_plugin_review_script_streaks_fees_reentries_and_yearly() -> None:
    review = load_script("trade-review/scripts/review.py")
    ledger = [
        _t("2025-01-02", "BUY", "AAPL", 10, 100.0, -1000.0, fee=60.0),
        _t("2025-02-03", "SELL", "AAPL", 10, 120.0, 1200.0, fee=50.0),
        _t("2025-03-01", "BUY", "AAPL", 10, 100.0, -1000.0),  # lower rebuy: averaging down
        _t("2025-04-01", "SELL", "AAPL", 10, 130.0, 1300.0),
        _t("2025-04-15", "BUY", "AAPL", 10, 140.0, -1400.0),  # higher rebuy: re-entry
    ]
    out = review.run_review({"as_of": "2025-12-31", "transactions": ledger})
    assert out["streaks"] == {"current": {"kind": "win", "length": 2}, "max_win": 2, "max_loss": 0}
    assert out["fees_total"] == 110.0
    assert {"code": "FEE_DRAG", "message": "fees totalled $110.00 over the span"} in out["flags"]
    assert out["reentries"] == [
        {"symbol": "AAPL", "sell_date": "2025-04-01", "sell_price": 130.0, "rebuy_date": "2025-04-15", "rebuy_price": 140.0, "delta_pct": 0.0769}
    ]
    assert {"code": "REENTERED_HIGHER", "message": out["flags"][-1]["message"]} in out["flags"]
    assert out["yearly"] == [{"year": 2025, "round_trips": 2, "realized_pnl": 500.0, "dividends": 0.0}]


def test_reentry_with_two_in_window_higher_buys_lists_only_the_first() -> None:
    review = load_script("trade-review/scripts/review.py")
    ledger = [
        _t("2025-01-02", "BUY", "DDD", 10, 100.0, -1000.0),
        _t("2025-02-01", "SELL", "DDD", 10, 80.0, 800.0),
        _t("2025-02-05", "BUY", "DDD", 10, 82.0, -820.0),  # first in-window higher buy
        _t("2025-02-20", "BUY", "DDD", 10, 90.0, -900.0),  # second in-window higher buy: not listed
    ]
    out = review.run_review({"as_of": "2025-12-31", "transactions": ledger})
    assert out["reentries"] == [
        {
            "symbol": "DDD",
            "sell_date": "2025-02-01",
            "sell_price": 80.0,
            "rebuy_date": "2025-02-05",
            "rebuy_price": 82.0,
            "delta_pct": 0.025,
        }
    ]


# ---------------------------------------------------------------------------
# render.py: the interactive page from a run-review.py / review.py result
# ---------------------------------------------------------------------------


def _review_sample() -> dict:
    review = load_script("trade-review/scripts/review.py")
    rows = [
        _t("2025-01-02", "BUY", "AAPL", 10, 100.0, -1000.0),
        _t("2025-02-03", "DIVIDEND", "AAPL", None, None, 2.5),
        _t("2025-04-01", "SELL", "AAPL", 10, 130.0, 1300.0),
        _t("2025-02-03", "BUY", "MSFT", 5, 200.0, -1000.0),
        _t("2025-05-01", "SELL", "MSFT", 5, 180.0, 900.0),
        _t("2025-05-01", "BUY", "XYZ", 10, 50.0, -500.0, account="b"),
    ]
    steps = {"AAPL": 140.0, "MSFT": 210.0, "XYZ": 30.0}
    out = review.run_review({"as_of": "2025-12-31", "transactions": rows, "prices": {s: _flat(p) for s, p in steps.items()},
                             "benchmark": {"symbol": "SPY", "prices": _flat(400.0)}})
    out["ledger"] = {"transactions_used": 6, "accounts": ["a", "b"], "date_range": {"start": "2025-01-02", "end": "2025-05-01"}}
    out["largest_buys"] = [{"symbol": "AAPL", "date": "2025-01-02", "units": 10, "price": 100.0, "amount": -1000.0}]
    return out


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    sample = _review_sample()
    assert sample["summary"]["round_trips"] == 2 and sample["strategy_matrix"] and sample["round_trips"][0]["drift"]["90"] is not None
    sample["flags"].append({"code": "NOTE", "message": "a <b>tag</b> in a flag"})
    src = tmp_path / "review.json"
    src.write_text(json.dumps(sample))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("trade-review/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Trade Review", "round_trips": 2, "flags": len(sample["flags"])}
    html = out.read_text()
    assert html.startswith("<title>Trade Review</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"strategy_matrix"' in html and '"benchmark_symbol":"SPY"' in html
    assert "a <b>tag<\\/b> in a flag" in html and "<b>tag</b> in a flag" not in html  # data is JSON; the page escapes it at build time
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html
    for section in ("Round trips", "Drift after sale", "Counterfactuals", "Disposition effect (Odean 1998)", "Open lots", "What was happening", "Strategy matrix", "Flags"):
        assert section in html
    assert "not financial, tax, or legal advice" in html and "http" not in html.split("window.DATA")[0]  # nothing fetched at runtime
    # plain-language layer: the explain box and glossary terms are built by the page script at runtime
    script = html.split("const FA")[1]
    assert '<div id="explain"></div>' in html and "FA.explain(" in script and "FA.term(" in script and "FA.armTerms(" in script and 'class="explain"' in script
    assert "What am I looking at?" in html and 'data-term=' in script
    for local_term in ('"profit factor"', '"pgr"', '"plr"', '"holding period"'):
        assert local_term in script.split("Object.assign(FA.glossary")[1]


def test_render_reads_stdin_and_accepts_a_bare_review_result(tmp_path, capsys, monkeypatch) -> None:
    import io
    import sys

    sample = _review_sample()
    sample.pop("ledger"), sample.pop("largest_buys")  # review.py's own output, without run-review.py's extras
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(sample)))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("trade-review/scripts/render.py"), ["--out", str(out)], capsys)
    assert rc == 0 and res["round_trips"] == 2 and out.exists()


def test_render_rejects_non_review_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"totals": {}}')
    rc, res = run_json(load_script("trade-review/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "run-review.py result" in res["error"]
    rc, res = run_json(load_script("trade-review/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read review JSON" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    src = tmp_path / "review.json"
    src.write_text(json.dumps(_review_sample()))
    assert_page_help(render_and_audit("trade-review/scripts/render.py", ["--in", str(src)], tmp_path, capsys))


@requires_chrome
def test_held_instead_adds_up_or_stays_out(tmp_path, capsys) -> None:
    from page_dom import card_text
    sample = _review_sample()
    sample["counterfactual"].update({"proceeds": 3000.0, "hold_value": 2450.0, "hold_delta": 250.0})  # one trip without a hold value
    src = tmp_path / "r.json"
    src.write_text(json.dumps(sample))
    text = card_text(render_and_audit("trade-review/scripts/render.py", ["--in", str(src)], tmp_path, capsys), "Counterfactuals")
    assert "$2,200" in text and "$3,000" not in text
    sample["counterfactual"]["hold_value"] = None
    src.write_text(json.dumps(sample))
    text = card_text(render_and_audit("trade-review/scripts/render.py", ["--in", str(src)], tmp_path, capsys), "Counterfactuals")
    assert "—" not in text
