from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts_util import load_script, run_json
from scripts_util import PLUGIN_ROOT
from page_dom import assert_page_help, render_and_audit, requires_chrome

FIX = Path(__file__).resolve().parent / "fixtures" / "spending"


@pytest.fixture
def data_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    imp = load_script("spending/scripts/import-spending.py")
    for file, account in (("chase-card.csv", "chase-sapphire-1234"), ("chase-checking.csv", "chase-checking-5678"), ("amex.csv", "amex-gold-9876")):
        rc, out = run_json(imp, [str(FIX / file), "--account", account], capsys)
        assert rc == 0, out
    return tmp_path


def _spend(capsys, *argv):
    return run_json(load_script("spending/scripts/spend.py"), list(argv), capsys)


def test_month_over_imported_fixtures(data_dir, capsys) -> None:
    rc, out = _spend(capsys, "month", "2026-08", "--as-of", "2026-09-11")
    assert rc == 0, out
    # chase card: 17.99 + 240 + 245 - 12 (Target return) + 4.10 interest = 495.09; checking: 120; amex: 6.50 + 240 + 32.10 - 30 = 248.60 -> 863.69
    assert out["spend_total"] == 863.69 and out["income_total"] == 5000.0 and out["refunds_total"] == 42.0
    assert out["transfers_total"] == 400 + 400 + 400 + 400.0   # card payment, checking debit paired to it, Amex ACH from checking, Amex autopay credit
    assert out["fees_and_interest"] == 4.1 and out["uncategorized"]["count"] == 0
    assert set(out["accounts"]) == {"chase-sapphire-1234", "chase-checking-5678", "amex-gold-9876"} and out["spending_path"].endswith("spending.json")
    cats = {c["category"]: c["amount"] for c in out["by_category"]}
    assert cats["Groceries"] == 450.0 and cats["Dining"] == 251.5 and cats["Utilities"] == 137.99


def test_changes_recurring_cashflow_uncategorized(data_dir, capsys) -> None:
    rc, out = _spend(capsys, "changes", "2026-08", "--as-of", "2026-09-11")
    assert rc == 0 and out["month"] == "2026-08" and all(c["new"] for c in out["categories"])
    rc, out = _spend(capsys, "recurring")
    assert rc == 0 and out["series"] == [] and out["totals"]["count"] == 0
    rc, out = _spend(capsys, "cashflow", "--as-of", "2026-09-11")
    assert rc == 0 and out["months"][0]["month"] == "2026-08" and out["avg_monthly_income"] == 5000.0
    rc, out = _spend(capsys, "uncategorized")
    assert rc == 0 and out["merchants"] == []


def test_search_merchants_range(data_dir, capsys) -> None:
    rc, out = _spend(capsys, "search", "costco")
    assert rc == 0 and out["count"] == 3 and out["total"] == -450.0
    rc, out = _spend(capsys, "merchants", "--top", "2")
    assert rc == 0 and [m["merchant"] for m in out["merchants"]] == ["Costco", "Bella Vista"]
    rc, out = _spend(capsys, "range", "--start", "2026-08-01", "--end", "2026-08-31", "--by", "account")
    assert rc == 0 and {r["key"]: r["amount"] for r in out["by"]} == {"chase-sapphire-1234": 495.09, "amex-gold-9876": 248.6, "chase-checking-5678": 120.0}


def test_errors(data_dir, capsys) -> None:
    rc, out = _spend(capsys, "month", "August")
    assert rc == 2 and "month" in out["error"]
    rc, out = _spend(capsys, "range", "--start", "2026-08-01")
    assert rc == 2
    rc, out = _spend(capsys, "search")
    assert rc == 2


def test_no_store_exits_4(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = _spend(capsys, "month")
    assert rc == 4 and out["code"] == "CONFIG_MISSING" and "import-spending.py" in out["hint"]
    (tmp_path / "spending.json").write_text("{nope")
    rc, out = _spend(capsys, "month")
    assert rc == 5 and out["code"] == "SPENDING_CORRUPT"


def test_items_flag_and_drill(data_dir, capsys, tmp_path) -> None:
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"name": "Food", "amount": -200, "category": "Groceries", "detail": "Groceries/Costco"}, {"name": "Paper towels", "amount": -40, "category": "Shopping", "detail": "Household/Paper"}]))
    rc, out = run_json(load_script("spending/scripts/items.py"), ["attach", "--items", str(items), "--date", "2026-08-15", "--amount", "-240", "--merchant", "costco"], capsys)
    assert rc == 0, out
    rc, plain = _spend(capsys, "month", "2026-08", "--as-of", "2026-09-11")
    assert rc == 0, plain
    rc, exploded = _spend(capsys, "month", "2026-08", "--as-of", "2026-09-11", "--items")
    assert plain["spend_total"] == exploded["spend_total"] == 863.69
    cats = {c["category"]: c["amount"] for c in exploded["by_category"]}
    assert cats["Groceries"] == 410.0 and cats["Shopping"] == 28.0   # 450 - 40 paper towels; -12 Target return + 40
    rc, out = _spend(capsys, "drill", "Groceries", "--start", "2026-08-01", "--end", "2026-08-31")
    assert rc == 0 and out["level"] == "category" and [(c["key"], c["amount"]) for c in out["children"]] == [("(none)", 210.0), ("Costco", 200.0)]
    rc, out = _spend(capsys, "drill")
    assert rc == 0 and out["level"] == "root" and out["children"][0]["key"] == "Groceries"
    rc, out = _spend(capsys, "drill", "Groceries", "--no-items")
    assert rc == 0 and out["children"] == [{"key": "(none)", "amount": 450.0, "share": 1.0, "count": 3}]
    rc, out = _spend(capsys, "range", "--start", "2026-08-01", "--end", "2026-08-31", "--by", "detail", "--items")
    assert rc == 0 and {r["key"] for r in out["by"]} == {"(none)", "Groceries/Costco", "Household/Paper"}
    rc, out = _spend(capsys, "drill", "Snacks")
    assert rc == 2 and "path" in out["error"]
    rc, out = _spend(capsys, "drill", "--start", "notadate")
    assert rc == 2 and "start" in out["error"]


def test_month_carries_transactions_months_and_recurring(data_dir, capsys, tmp_path) -> None:
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"name": "Food", "amount": -200, "category": "Groceries", "detail": "Groceries/Costco"}, {"name": "Paper towels", "amount": -40, "category": "Shopping", "detail": "Household/Paper"}]))
    rc, out = run_json(load_script("spending/scripts/items.py"), ["attach", "--items", str(items), "--date", "2026-08-15", "--amount", "-240", "--merchant", "costco"], capsys)
    assert rc == 0, out
    rc, out = _spend(capsys, "month", "2026-08", "--as-of", "2026-09-11", "--items")
    assert rc == 0, out
    tx = out["transactions"]
    assert len(tx) == 11 and tx == sorted(tx, key=lambda t: (t["date"], t["merchant"]))
    assert set(tx[0]) == {"id", "date", "merchant", "description", "amount", "category", "detail", "account_id", "item_name", "has_items", "parent_id"}
    food = next(t for t in tx if t["item_name"] == "Food")
    assert food["amount"] == 200.0 and food["category"] == "Groceries" and food["detail"] == "Groceries/Costco" and food["parent_id"] and food["has_items"]
    assert sum(t["amount"] for t in tx) == out["spend_total"] == 863.69
    assert out["months"] == [{"month": "2026-08", "income": 5000.0, "spend": 863.69, "transfers_out": 800.0, "transfers_in": 800.0, "net": 4136.31, "savings_rate": 0.8273}]
    assert out["recurring"] == []   # one month of data: no series of three yet
    rc, plain = _spend(capsys, "month", "2026-08", "--as-of", "2026-09-11")
    assert len(plain["transactions"]) == 10 and all(t["item_name"] is None for t in plain["transactions"])


def test_render_builds_a_self_contained_page(data_dir, capsys, tmp_path) -> None:
    rc, month = _spend(capsys, "month", "2026-08", "--as-of", "2026-09-11")
    rc2, changes = _spend(capsys, "changes", "2026-08", "--as-of", "2026-09-11")
    assert rc == 0 and rc2 == 0
    month["month"] = "<b>x"   # a value the static lede prints must come out escaped
    month["flags"] = ["PARTIAL_MONTH", "NO_INCOME_DATA"]
    src, chg, out = tmp_path / "month.json", tmp_path / "changes.json", tmp_path / "page.html"
    src.write_text(json.dumps(month))
    chg.write_text(json.dumps(changes))
    rc, res = run_json(load_script("spending/scripts/render.py"), ["--in", str(src), "--changes", str(chg), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Spending Review", "month": "<b>x", "transactions": 10, "flags": 2}
    html = out.read_text()
    assert html.startswith("<title>Spending Review</title>") and "<html" not in html and "<body" not in html
    assert '<p class="sub" id="lede">&lt;b&gt;x · spend $863.69 · income — · net — · savings rate —</p>' in html
    assert "window.DATA = " in html and '"by_category"' in html and '"transactions"' in html and '"changes":{' in html and '"explained_by"' in html
    assert 'id="cats"' in html and 'id="back"' in html and 'id="flow-card"' in html and 'id="recurring"' in html and 'id="banner"' in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html and "not financial advice" in html
    # glossary: the explain box and the term markers are built by JS, so the markers live in the toolkit and the calls in the SCRIPT
    assert 'id="explain"' in html and 'class="explain"' in html and 'data-term=' in html
    assert "FA.explain(" in html and "FA.term('savings rate'" in html and "FA.term('recurring charge'" in html and "Object.assign(FA.glossary, {" in html
    rc, res = run_json(load_script("spending/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "p2.html")], capsys)
    assert rc == 0 and '"changes":null' in (tmp_path / "p2.html").read_text()


def test_render_rejects_non_month_input(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"series": [], "totals": {}}')
    rc, res = run_json(load_script("spending/scripts/render.py"), ["--in", str(bad), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "month result" in res["error"]
    good = tmp_path / "month.json"
    good.write_text('{"month": "2026-08", "spend_total": 1.0, "by_category": []}')
    rc, res = run_json(load_script("spending/scripts/render.py"), ["--in", str(good), "--changes", str(bad), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "changes result" in res["error"]
    rc, res = run_json(load_script("spending/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    s = PLUGIN_ROOT / "docs/samples"
    a = render_and_audit("spending/scripts/render.py", ["--in", str(s / "spending-month.json"), "--changes", str(s / "spending-changes.json")], tmp_path, capsys)
    assert_page_help(a)


@requires_chrome
def test_categories_lead_escapes_the_month(tmp_path, capsys) -> None:
    d = json.loads((PLUGIN_ROOT / "docs/samples/spending-month.json").read_text())
    d["month"] = "2026-08<i>"
    src = tmp_path / "m.json"
    src.write_text(json.dumps(d))
    a = render_and_audit("spending/scripts/render.py", ["--in", str(src)], tmp_path, capsys)
    assert "2026-08<i>" in next(c for c in a["cards"] if c["h2"].startswith("Categories"))["modal"]["lead"]
