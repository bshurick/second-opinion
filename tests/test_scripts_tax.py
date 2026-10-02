from __future__ import annotations

import json
import re

import pytest
from scripts_util import load_script, run_json
from second_opinion import ledger, market
from page_dom import assert_page_help, render_and_audit, requires_chrome


def _t(d: str, kind: str, symbol: str | None, units, price, amount, account="a") -> dict:
    return {"date": d, "type": kind, "symbol": symbol, "units": units, "price": price, "amount": amount, "fee": 0.0, "reinvested": False, "description": kind, "security_name": None, "account_id": account, "source_id": d}


LEDGER = [
    _t("2025-01-15", "BUY", "AAPL", 10, 100.0, -1000.0),
    _t("2026-06-01", "BUY", "AAPL", 10, 150.0, -1500.0),
    _t("2026-01-05", "BUY", "Y", 10, 100.0, -1000.0, account="b"),
    _t("2026-03-10", "SELL", "Y", 10, 80.0, 800.0, account="b"),
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    book = ledger.load(tmp_path / "ledger.json")
    ledger.merge(book, LEDGER, source="test")
    ledger.save(book, tmp_path / "ledger.json")
    return tmp_path


@pytest.fixture
def yahoo(monkeypatch):
    calls: list[list[str]] = []

    def day_changes(symbols):
        calls.append(list(symbols))
        return {"AAPL": {"price": 140.0, "previous_close": 138.0}}

    monkeypatch.setattr(market, "day_changes", day_changes)
    return calls


def test_tax_report_reads_ledger_and_prices_open_symbols_only(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), ["--as-of", "2026-09-04", "--short-term", "0.32", "--long-term", "0.15"], capsys)
    assert rc == 0, out
    assert yahoo == [["AAPL"]]  # Y is fully sold: no quote needed
    assert out["rates"] == {"short_term": 0.32, "long_term": 0.15, "state": 0.0, "niit": 0.0}
    assert out["unrealized"]["total"] == 300.0 and out["summary"]["short_term_net"] == -200.0
    assert out["sources"] == {"ledger": str(data_dir / "ledger.json"), "prices": "yahoo"} and out["missing_prices"] == []
    assert out["ledger"]["transactions_used"] == 4 and out["ledger"]["accounts"] == ["a", "b"]


def test_tax_report_planned_sale_and_filters(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), ["--as-of", "2026-09-04", "--sell", "AAPL", "5", "--account", "a"], capsys)
    assert rc == 0 and out["lot_selection"]["symbol"] == "AAPL" and out["lot_selection"]["tax_saved_vs_fifo"] == 42.0
    assert out["ledger"]["accounts"] == ["a"] and out["summary"]["short_term_net"] == 0.0


def test_tax_report_price_override_and_missing_prices(data_dir, yahoo, monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "day_changes", lambda symbols: {})
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), ["--as-of", "2026-09-04", "--price", "AAPL=120"], capsys)
    assert rc == 0 and out["unrealized"]["total"] == -100.0 and out["missing_prices"] == []
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0 and out["missing_prices"] == ["AAPL"] and out["unrealized"]["total"] == 0.0
    assert {"code": "MISSING_PRICES", "message": "no current price for: AAPL; unrealized figures exclude them (pass --price SYMBOL=PRICE)"} in out["flags"]


def test_tax_report_yahoo_failure_degrades(data_dir, monkeypatch, capsys) -> None:
    def boom(symbols):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "day_changes", boom)
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0 and out["sources"]["prices"] is None and out["missing_prices"] == ["AAPL"]


def test_tax_report_bad_args_and_empty_ledger(tmp_path, monkeypatch, yahoo, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), [], capsys)
    assert rc == 2 and "import-csv.py" in out["error"]
    rc, out = run_json(load_script("tax-aware/scripts/tax-report.py"), ["--price", "AAPL"], capsys)
    assert rc == 2 and "SYMBOL=PRICE" in out["error"]


def test_tax_report_repeatable_sells_and_sell_after(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(
        load_script("tax-aware/scripts/tax-report.py"),
        [
            "--as-of", "2026-09-04", "--account", "a",
            "--sell", "AAPL", "5", "--sell", "AAPL", "12",
            "--sell-after", "2027-06-10",
        ],
        capsys,
    )
    assert rc == 0, out
    assert [s["units"] for s in out["lot_selections"]] == [5.0, 12.0]
    assert all("minimal" in s and "tax_saved_vs_minimal" in s for s in out["lot_selections"])
    # sold on 2027-06-10 the 2026 lot (374 days) is long-term
    assert out["lot_selections"][1]["fifo"]["lots"][1]["term"] == "long"
    assert out["lot_selections"][1]["fifo"]["tax"] == 57.0
    assert out["lot_selection"] is None  # several --sell: only lot_selections
    assert out["summary"]["carryforward_history"][-1]["year"] == 2026


def test_tax_report_single_sell_keeps_lot_selection(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(
        load_script("tax-aware/scripts/tax-report.py"),
        ["--as-of", "2026-09-04", "--account", "a", "--sell", "AAPL", "15", "--sell-after", "2027-06-10"],
        capsys,
    )
    assert rc == 0, out
    # single --sell keeps the singular lot_selection, and --sell-after moves
    # the holding period: the 2026 lot is long-term by 2027-06-10
    sel = out["lot_selection"]
    assert sel["units"] == 15.0 and sel["fifo"]["tax"] == 52.5
    assert sel["fifo"]["lots"][1]["term"] == "long"
    sels = out["lot_selections"]
    # minimal as of the later date: 10 units of the 2026 lot (-100 long) then
    # 5 of the 2025 lot (+200 long) -> 52.50 - 15.00
    assert len(sels) == 1 and sels[0]["tax_saved_vs_minimal"] == 37.5


def test_tax_report_sell_after_requires_sell(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(
        load_script("tax-aware/scripts/tax-report.py"), ["--as-of", "2026-09-04", "--sell-after", "2027-01-01"], capsys
    )
    assert rc == 2 and "--sell" in out["error"]


def test_tax_math_script_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    params = {"as_of": "2026-09-04", "transactions": LEDGER[:2], "prices": {"AAPL": 140.0}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(params)))
    load_script("tax-aware/scripts/tax.py").main()
    assert json.loads(capsys.readouterr().out)["unrealized"]["total"] == 300.0


TAX_REPORT = {
    "as_of": "2026-09-04", "year": 2026, "rates": {"short_term": 0.32, "long_term": 0.15, "state": 0.05, "niit": 0.0},
    "sources": {"ledger": "/x/ledger.json", "prices": "yahoo"}, "ledger": {"transactions_used": 12, "accounts": ["a", "b"]}, "missing_prices": [],
    "open_lots": [
        {"symbol": "AAPL", "account_id": "a", "buy_date": "2025-01-15", "units": 10.0, "cost": 1000.0, "basis_adjustment": 0.0, "price": 140.0, "value": 1400.0, "unrealized": 400.0, "holding_days": 597, "term": "long", "long_term_date": "2026-01-16", "days_to_long_term": 0, "tax_if_sold": 80.0, "tax_if_sold_long": 80.0},
        {"symbol": "AAPL", "account_id": "a", "buy_date": "2025-10-20", "units": 10.0, "cost": 1500.0, "basis_adjustment": 0.0, "price": 140.0, "value": 1400.0, "unrealized": -100.0, "holding_days": 319, "term": "short", "long_term_date": "2026-10-21", "days_to_long_term": 47, "tax_if_sold": -37.0, "tax_if_sold_long": -20.0},
        {"symbol": "LOSS<X>", "account_id": "a", "buy_date": "2026-02-01", "units": 100.0, "cost": 3000.0, "basis_adjustment": 0.0, "price": 22.0, "value": 2200.0, "unrealized": -800.0, "holding_days": 215, "term": "short", "long_term_date": "2027-02-02", "days_to_long_term": 151, "tax_if_sold": -296.0, "tax_if_sold_long": -160.0},
        {"symbol": "Y", "account_id": "b", "buy_date": "2026-03-25", "units": 10.0, "cost": 980.0, "basis_adjustment": 200.0, "price": 70.0, "value": 700.0, "unrealized": -280.0, "holding_days": 163, "term": "short", "long_term_date": "2027-03-26", "days_to_long_term": 203, "tax_if_sold": -103.6, "tax_if_sold_long": -56.0},
    ],
    "unrealized": {"short": -1180.0, "long": 400.0, "total": -780.0, "tax_if_all_sold": -356.6},
    "realized": [
        {"symbol": "Y", "account_id": "b", "sell_date": "2026-03-10", "units": 10.0, "proceeds": 800.0, "cost": 1000.0, "gain": -200.0, "holding_days": 64, "term": "short", "wash_sale": True, "wash_buy_date": "2026-03-25", "disallowed": 200.0, "allowed_gain": 0.0},
        {"symbol": "WIN", "account_id": "a", "sell_date": "2026-07-01", "units": 20.0, "proceeds": 1800.0, "cost": 1000.0, "gain": 800.0, "holding_days": 422, "term": "long", "wash_sale": False, "wash_buy_date": None, "disallowed": 0.0, "allowed_gain": 800.0},
    ],
    "prior_year_sales_ignored": 1,
    "summary": {"short_term_net": 0.0, "long_term_net": 800.0, "disallowed_losses": 200.0, "net_capital_gain": 800.0, "taxed_as": "long", "capital_gains_tax": 160.0, "deductible_against_income": 0.0, "ordinary_income_tax_saved": 0.0, "loss_carryforward": 0.0, "prior_year_net_losses": 2000.0,
                "carryforward_history": [{"year": 2024, "net": -2000.0, "deductible": 2000.0, "carryforward": 0.0}, {"year": 2025, "net": 0.0, "deductible": 0.0, "carryforward": 0.0}, {"year": 2026, "net": 800.0, "deductible": 0.0, "carryforward": 0.0}],
                "dividends": 25.0, "dividend_tax": 5.0, "interest": 12.5, "interest_tax": 4.62, "estimated_tax": 169.62},
    "harvest_candidates": [
        {"symbol": "LOSS<X>", "units": 100.0, "cost": 3000.0, "value": 2200.0, "unrealized": -800.0, "pct": -0.2667, "term": "short", "tax_benefit": 296.0, "last_buy_date": "2026-02-01", "recent_buy_within_30d": False, "warning": None},
        {"symbol": "Y", "units": 10.0, "cost": 980.0, "value": 700.0, "unrealized": -280.0, "pct": -0.2857, "term": "short", "tax_benefit": 103.6, "last_buy_date": "2026-03-25", "recent_buy_within_30d": False, "warning": None},
    ],
    "harvest_total": {"losses": -1080.0, "tax_benefit": 399.6},
    "lot_selection": None,
    "lot_selections": [{"symbol": "AAPL", "units": 5.0, "price": 140.0,
                        "fifo": {"lots": [{"buy_date": "2025-01-15", "units": 5.0, "cost": 500.0, "gain": 200.0, "term": "long"}], "gain": 200.0, "tax": 40.0},
                        "highest_cost": {"lots": [{"buy_date": "2025-10-20", "units": 5.0, "cost": 750.0, "gain": -50.0, "term": "short"}], "gain": -50.0, "tax": -18.5},
                        "tax_saved_vs_fifo": 58.5,
                        "minimal": {"lots": [{"buy_date": "2025-10-20", "units": 5.0, "cost": 750.0, "gain": -50.0, "term": "short"}], "gain": -50.0, "tax": -18.5},
                        "tax_saved_vs_minimal": 58.5}],
    "flags": [{"code": "WASH_SALE", "message": "Y loss of 200.0 on 2026-03-10 is disallowed (200.0) by the 2026-03-25 purchase; the amount is added to that lot's basis"}],
}


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    src = tmp_path / "tax.json"
    src.write_text(json.dumps(TAX_REPORT))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("tax-aware/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Tax View", "realized": 2, "open_lots": 4, "flags": 1}
    html = out.read_text()
    assert html.startswith("<title>Tax View</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"LOSS<X>"' in html and '"WASH_SALE"' in html  # data is JSON; the page escapes at render time
    disclaimer = "Estimate for planning at the stated rates; not tax advice or a return."
    assert html.count(disclaimer) >= 2 and html.index(disclaimer) < html.index('id="tiles"')  # at the top and in the closing note
    for section in ("Realized year to date", "Open lots", "Harvesting candidates", "Planned sales", "Flags", "Not modelled", "Qualified-dividend holding-period test", "td.wash"):
        assert section in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html
    assert "<script src" not in html and "<link" not in html and "fetch(" not in html  # nothing fetched at runtime
    assert all(u.startswith(("https://www.investopedia.com/", "http://www.w3.org/")) for u in re.findall(r"https?://[^\s\"'<>]+", html))  # only glossary links
    # plain-language layer: the explain box and glossary terms (the term spans are produced by JS at runtime, so check the script source)
    assert 'id="explain"' in html and 'class="explain"' in html and "data-term=" in html
    assert "FA.explain(" in html and "FA.term(" in html and "FA.armTerms(" in html
    assert "Object.assign(FA.glossary, {" in html and '"short-term gain"' in html and '"niit"' in html and '"capital loss deduction"' in html


def test_render_rejects_non_tax_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"totals": {"total_value": 1}}')
    rc, res = run_json(load_script("tax-aware/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "tax.py result" in res["error"]
    rc, res = run_json(load_script("tax-aware/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    src = tmp_path / "tax.json"
    src.write_text(json.dumps(TAX_REPORT))
    assert_page_help(render_and_audit("tax-aware/scripts/render.py", ["--in", str(src)], tmp_path, capsys))


@requires_chrome
def test_year_flow_shows_the_carried_in_loss_and_harvest_uses_the_combined_rate(tmp_path, capsys) -> None:
    import copy
    from page_dom import card_text
    report = copy.deepcopy(TAX_REPORT)
    report["summary"]["net_capital_gain"] = 300.0  # 0 + 800 - 500 carried in
    src = tmp_path / "tax.json"
    src.write_text(json.dumps(report))
    a = render_and_audit("tax-aware/scripts/render.py", ["--in", str(src)], tmp_path, capsys)
    assert "carried in" in card_text(a, "Realized") and "500.00" in card_text(a, "Realized")
    assert "37.0%" in card_text(a, "Harvesting")  # 32% short-term + 5% state + 0% NIIT


# --- holding period: long-term only when held MORE than one year (calendar anniversary) ---------


def _sale_term(buy: str, sell: str) -> dict:
    tax = load_script("tax-aware/scripts/tax.py")
    out = tax.run_tax({"as_of": sell, "prices": {"Z": 10.0}, "transactions": [
        _t(buy, "BUY", "Z", 10, 10.0, -100.0),
        _t(sell, "SELL", "Z", 5, 12.0, 60.0),
    ]})
    (row,) = out["realized"]
    (lot,) = out["open_lots"]
    return {"sale": row["term"], "lot": lot["term"], "long_term_date": lot["long_term_date"]}


@pytest.mark.parametrize(
    ("buy", "sell", "term", "long_term_date"),
    [
        # 366 days across Feb 29 2024 is still only the one-year anniversary: short.
        ("2023-03-01", "2024-03-01", "short", "2024-03-02"),
        ("2023-03-01", "2024-03-02", "long", "2024-03-02"),
        # Ordinary year: the anniversary is short, the day after is long.
        ("2024-06-15", "2025-06-15", "short", "2025-06-16"),
        ("2024-06-15", "2025-06-16", "long", "2025-06-16"),
        # Bought on Feb 29: the one-year period ends Feb 28 the next year, so long-term from Mar 1.
        ("2024-02-29", "2025-02-28", "short", "2025-03-01"),
        ("2024-02-29", "2025-03-01", "long", "2025-03-01"),
    ],
)
def test_holding_period_uses_the_calendar_anniversary(buy, sell, term, long_term_date) -> None:
    got = _sale_term(buy, sell)
    assert got == {"sale": term, "lot": term, "long_term_date": long_term_date}


def test_planned_sale_term_uses_the_calendar_anniversary() -> None:
    tax = load_script("tax-aware/scripts/tax.py")
    txs = [_t("2023-03-01", "BUY", "Z", 10, 10.0, -100.0)]
    base = {"as_of": "2024-01-02", "prices": {"Z": 12.0}, "transactions": txs}
    on_anniv = tax.run_tax({**base, "planned_sale": {"symbol": "Z", "units": 1, "price": 12.0, "sell_as_of": "2024-03-01"}})
    after = tax.run_tax({**base, "planned_sale": {"symbol": "Z", "units": 1, "price": 12.0, "sell_as_of": "2024-03-02"}})
    assert on_anniv["lot_selection"]["fifo"]["lots"][0]["term"] == "short"
    assert after["lot_selection"]["fifo"]["lots"][0]["term"] == "long"
