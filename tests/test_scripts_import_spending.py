from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts_util import load_script, run_json

FIX = Path(__file__).resolve().parent / "fixtures" / "spending"
SCRIPT = "spending/scripts/import-spending.py"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _run(capsys, *argv):
    return run_json(load_script(SCRIPT), list(argv), capsys)


def _store(data_dir) -> dict:
    return json.loads((data_dir / "spending.json").read_text())


def test_presets_listing(data_dir, capsys) -> None:
    rc, out = _run(capsys, "presets")
    assert rc == 0 and {p["name"] for p in out["presets"]} >= {"amex", "chase-card", "chase-checking", "citi", "capital-one", "discover", "bofa-card", "apple-card"}
    assert all({"name", "kind", "sign", "columns"} <= set(p) for p in out["presets"])


def test_dry_run_detects_preset_and_writes_nothing(data_dir, capsys) -> None:
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--account", "amex-gold-9876", "--dry-run")
    assert rc == 0, out
    assert out["dry_run"] is True and out["preset"] == "amex" and out["header_line"] == 1 and out["count"] == 5
    assert out["date_range"] == {"start": "2026-08-14", "end": "2026-08-22"} and out["transfers_marked"] == 1
    assert len(out["sample"]) == 5 and out["sample"][0]["merchant"] == "Blue Bottle Coffee"
    assert not (data_dir / "spending.json").exists()


@pytest.mark.parametrize("file,preset,kind,count", [
    ("amex.csv", "amex", "card", 5), ("chase-card.csv", "chase-card", "card", 6), ("chase-checking.csv", "chase-checking", "checking", 4),
    ("citi.csv", "citi", "card", 2), ("capital-one.csv", "capital-one", "card", 2), ("discover.csv", "discover", "card", 2),
    ("bofa-card.csv", "bofa-card", "card", 2), ("apple-card.csv", "apple-card", "card", 3), ("card.ofx", "ofx", "card", 3),
])
def test_import_each_fixture(data_dir, capsys, file, preset, kind, count) -> None:
    rc, out = _run(capsys, str(FIX / file), "--account", "acct-1")
    assert rc == 0, out
    assert out["preset"] == preset and out["imported"] == count and out["duplicates"] == 0
    book = _store(data_dir)
    assert book["accounts"]["acct-1"] == {**book["accounts"]["acct-1"], "id": "acct-1", "kind": kind, "preset": preset}
    assert len(book["transactions"]) == count and all(t["id"].startswith("t-") for t in book["transactions"])
    assert book["imports"][-1]["file"] == file and book["imports"][-1]["added"] == count


def test_dedupe_key_uses_description_so_same_day_same_amount_rows_all_survive(data_dir, capsys, tmp_path) -> None:
    # Two Costco registers charged the same
    # amount on the same day (distinct descriptions) must both import, and a genuine
    # same-day/same-amount/same-description twin (two Starbucks charges) must also both
    # survive via occurrence, while a straight re-import of the whole file dedupes all four.
    csv_text = (
        "Date,Description,Amount\n"
        "08/14/2026,COSTCO WHSE #0684 SPRINGFIELD IL,240.00\n"
        "08/14/2026,COSTCO WHSE #0120 SPRINGFIELD IL,240.00\n"
        "08/14/2026,STARBUCKS STORE 12345,5.00\n"
        "08/14/2026,STARBUCKS STORE 12345,5.00\n"
    )
    probe = tmp_path / "probe.csv"
    probe.write_text(csv_text)
    rc, out = _run(capsys, str(probe), "--account", "amex-gold-9876")
    assert rc == 0, out
    assert out["imported"] == 4 and out["duplicates"] == 0
    book = _store(data_dir)
    assert len(book["transactions"]) == 4
    starbucks = [t for t in book["transactions"] if t["merchant"] == "Starbucks"]
    assert sorted(t["occurrence"] for t in starbucks) == [1, 2]
    rc, out = _run(capsys, str(probe), "--account", "amex-gold-9876")
    assert rc == 0, out
    assert out["imported"] == 0 and out["duplicates"] == 4
    assert len(_store(data_dir)["transactions"]) == 4


def test_reimport_dedupes(data_dir, capsys) -> None:
    _run(capsys, str(FIX / "amex.csv"), "--account", "amex-gold-9876")
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--account", "amex-gold-9876")
    assert rc == 0 and out["imported"] == 0 and out["duplicates"] == 5
    assert len(_store(data_dir)["transactions"]) == 5


def test_name_defaults_to_debt_tracker_register_then_id(data_dir, capsys) -> None:
    (data_dir / "statements.json").write_text(json.dumps({"accounts": {"chase-sapphire-1234": {"id": "chase-sapphire-1234", "name": "Chase Sapphire", "kind": "card"}}, "statements": [], "imports": []}))
    _run(capsys, str(FIX / "chase-card.csv"), "--account", "chase-sapphire-1234")
    _run(capsys, str(FIX / "amex.csv"), "--account", "amex-gold-9876")
    _run(capsys, str(FIX / "citi.csv"), "--account", "citi-1111", "--name", "Citi Double Cash")
    accounts = _store(data_dir)["accounts"]
    assert accounts["chase-sapphire-1234"]["name"] == "Chase Sapphire"
    assert accounts["amex-gold-9876"]["name"] == "amex-gold-9876"
    assert accounts["citi-1111"]["name"] == "Citi Double Cash"


def test_forced_preset_matches_on_columns_not_the_full_fingerprint(data_dir, capsys, tmp_path) -> None:
    # A Capital One export with the "Card No." column removed still has every column the
    # preset actually reads; forcing --preset capital-one must match on those, not the
    # (stricter) detection fingerprint that includes "Card No.".
    csv_text = (
        "Transaction Date,Posted Date,Description,Category,Debit,Credit\n"
        "2026-08-04,2026-08-05,UBER *TRIP HELP.UBER.COM,Other Travel,18.40,\n"
        "2026-08-06,2026-08-06,CAPITAL ONE MOBILE PYMT,Payment/Credit,,150.00\n"
    )
    path = tmp_path / "capone-no-card-no.csv"
    path.write_text(csv_text)
    rc, out = _run(capsys, str(path), "--account", "cap-one-1", "--preset", "capital-one")
    assert rc == 0, out
    assert out["preset"] == "capital-one" and out["imported"] == 2


def test_forced_preset_never_stricter_than_detection(data_dir, capsys, tmp_path) -> None:
    # Amex's "columns" (what it reads) is a superset of its detection "fingerprint" --
    # "Category" is optional. A bare Date,Description,Amount export auto-detects fine, so
    # forcing --preset amex on it must also succeed, not demand the optional column too.
    csv_text = (
        "Date,Description,Amount\n"
        "08/14/2026,BLUE BOTTLE COFFEE,6.50\n"
        "08/15/2026,WHOLE FOODS MARKET,42.10\n"
    )
    path = tmp_path / "amex-no-category.csv"
    path.write_text(csv_text)
    rc, out = _run(capsys, str(path), "--account", "amex-forced-1", "--preset", "amex")
    assert rc == 0, out
    assert out["preset"] == "amex" and out["imported"] == 2
    rc, out = _run(capsys, str(path), "--account", "amex-auto-1")
    assert rc == 0, out
    assert out["preset"] == "amex" and out["imported"] == 2


def test_forced_preset_no_header_match_names_expected_columns(data_dir, capsys, tmp_path) -> None:
    path = tmp_path / "wrong.csv"
    path.write_text("Foo,Bar\n1,2\n")
    rc, out = _run(capsys, str(path), "--account", "x-1", "--preset", "capital-one")
    assert rc == 2 and out["code"] == "NO_HEADER"
    for col in ("transaction date", "posted date", "description", "category", "debit", "credit"):
        assert col in out["error"]


def test_mapping_and_unknown_preset(data_dir, capsys) -> None:
    rc, out = _run(capsys, str(FIX / "custom.csv"), "--account", "x-1")
    assert rc == 2 and out["code"] == "NO_HEADER"
    rc, out = _run(capsys, str(FIX / "custom.csv"), "--account", "x-1", "--mapping", json.dumps({"date": "When", "description": "What", "amount": "Spent", "category": "Kind", "sign": "charges_positive"}))
    assert rc == 0 and out["imported"] == 2 and out["preset"] == "mapping"
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--account", "x-1", "--preset", "nope")
    assert rc == 2 and out["code"] == "UNKNOWN_PRESET"


def test_bad_account_and_kind(data_dir, capsys) -> None:
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--account", "Bad Id!")
    assert rc == 2 and out["code"] == "INVALID_ACCOUNT"
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--account", "x-1", "--kind", "wallet")
    assert rc == 2
    rc, out = _run(capsys, str(FIX / "amex.csv"))
    assert rc == 2 and "account" in out["error"]


def test_kind_cannot_change_once_rows_exist(data_dir, capsys) -> None:
    _run(capsys, str(FIX / "amex.csv"), "--account", "x-1")
    rc, out = _run(capsys, str(FIX / "chase-checking.csv"), "--account", "x-1")
    assert rc == 2 and out["code"] == "INVALID_ACCOUNT" and "kind" in out["error"]


def test_preset_kind_outranks_stored_kind_and_still_conflicts(data_dir, capsys, tmp_path) -> None:
    # An account first created via --rows (typed card by default) later imports a
    # chase-checking preset file without --kind: the preset's own implied kind (checking)
    # outranks the stored kind, so this is still a real conflict once rows exist.
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps([{"date": "2026-09-01", "description": "Coffee", "amount": -5.0}]))
    rc, out = _run(capsys, "--rows", str(payload), "--account", "x-2", "--source", "receipt")
    assert rc == 0, out
    assert _store(data_dir)["accounts"]["x-2"]["kind"] == "card"
    rc, out = _run(capsys, str(FIX / "chase-checking.csv"), "--account", "x-2")
    assert rc == 2 and out["code"] == "INVALID_ACCOUNT" and "kind" in out["error"]


def test_rows_without_kind_inherit_the_account_kind_from_a_preset_import(data_dir, capsys, tmp_path) -> None:
    # An account first created by the chase-checking preset (implied kind: checking); a later
    # --rows import with no kind signal of its own falls back to that stored kind, so income
    # rows are typed as checking deposits rather than defaulted to "card".
    rc, out = _run(capsys, str(FIX / "chase-checking.csv"), "--account", "checking-2")
    assert rc == 0, out
    assert _store(data_dir)["accounts"]["checking-2"]["kind"] == "checking"
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps([{"date": "2026-09-01", "description": "Paycheck", "amount": 1000.0}]))
    rc, out = _run(capsys, "--rows", str(payload), "--account", "checking-2", "--source", "statement-pdf")
    assert rc == 0, out
    book = _store(data_dir)
    assert book["accounts"]["checking-2"]["kind"] == "checking"
    row = next(t for t in book["transactions"] if t["description"] == "Paycheck")
    assert row["type"] == "deposit" and row["category"] == "Income"


def test_kind_remembers_after_the_first_explicit_kind(data_dir, capsys, tmp_path) -> None:
    # Finding 1: --rows defaulted account_kind to "card" internally, so a second --rows
    # import into a checking account (established with an explicit --kind) used to exit 2
    # INVALID_ACCOUNT for simply omitting --kind on the later call.
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps([{"date": "2026-09-01", "description": "Paycheck", "amount": 1000.0}]))
    rc, out = _run(capsys, "--rows", str(payload), "--account", "checking-1", "--source", "statement-pdf", "--kind", "checking")
    assert rc == 0, out
    assert _store(data_dir)["accounts"]["checking-1"]["kind"] == "checking"
    payload2 = tmp_path / "rows2.json"
    payload2.write_text(json.dumps([{"date": "2026-09-02", "description": "Grocery run", "amount": -50.0}]))
    rc, out = _run(capsys, "--rows", str(payload2), "--account", "checking-1", "--source", "receipt")
    assert rc == 0, out
    book = _store(data_dir)
    assert book["accounts"]["checking-1"]["kind"] == "checking"
    row = next(t for t in book["transactions"] if t["description"] == "Grocery run")
    assert row["type"] == "withdrawal"  # typed as a checking row, not defaulted to "card"


def test_second_import_pairs_transfers_across_accounts(data_dir, capsys) -> None:
    _run(capsys, str(FIX / "chase-card.csv"), "--account", "chase-sapphire-1234")
    rc, out = _run(capsys, str(FIX / "chase-checking.csv"), "--account", "chase-checking-5678")
    assert rc == 0 and out["transfer_pairs"] == 1
    rows = {t["description"]: t for t in _store(data_dir)["transactions"]}
    assert rows["Payment to Chase card ending in 1234"]["transfer"] is True
    assert rows["Payment to Chase card ending in 1234"]["transfer_pair"] == rows["Payment Thank You-Mobile"]["transfer_pair"]


def test_rules_file_is_applied_at_import(data_dir, capsys) -> None:
    (data_dir / "spending-rules.json").write_text(json.dumps({"categories": [{"match": "netflix", "category": "Subscriptions"}], "ignore": [{"match": "^interest charge"}]}))
    rc, out = _run(capsys, str(FIX / "chase-card.csv"), "--account", "chase-sapphire-1234")
    assert rc == 0 and out["imported"] == 5 and {"row": 6, "reason": "ignored by rule"} in out["skipped"]
    assert next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Netflix")["category"] == "Subscriptions"


def test_missing_file_and_corrupt_store(data_dir, capsys) -> None:
    rc, out = _run(capsys, str(FIX / "nope.csv"), "--account", "x-1")
    assert rc == 2 and "not found" in out["error"]
    (data_dir / "spending.json").write_text("{nope")
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--account", "x-1")
    assert rc == 5 and out["code"] == "SPENDING_CORRUPT"


def test_missing_rows_file_is_invalid_input_not_a_traceback(data_dir, capsys, tmp_path) -> None:
    rc, out = _run(capsys, "--rows", str(tmp_path / "nope.json"), "--account", "x-1", "--source", "receipt")
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "rows file not found" in out["error"]


def test_unreadable_rows_file_is_invalid_input(data_dir, capsys, tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe\x00")
    rc, out = _run(capsys, "--rows", str(bad), "--account", "x-1", "--source", "receipt")
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def _amex_workbook(path: Path) -> None:
    """A minimal Amex-style workbook: preamble rows, then Date/Description/Amount/Category."""
    import zipfile

    def cell(ref, value, kind="n", style=None):
        s = f' s="{style}"' if style is not None else ""
        if kind == "inline":
            return f'<c r="{ref}" t="inlineStr"{s}><is><t>{value}</t></is></c>'
        return f'<c r="{ref}"{s}><v>{value}</v></c>'

    rows = [
        (1, [cell("A1", "Transaction Details", "inline")]),
        (3, [cell("A3", "Date", "inline"), cell("B3", "Description", "inline"), cell("C3", "Amount", "inline"), cell("D3", "Category", "inline")]),
        (4, [cell("A4", 46246, style=1), cell("B4", "SQ *BLUE BOTTLE COFFEE SPRINGFIELD IL", "inline"), cell("C4", 6.5), cell("D4", "Restaurant-Bar &amp; Café", "inline")]),
        (5, [cell("A5", 46247, style=1), cell("B5", "COSTCO WHSE #0684 SPRINGFIELD IL", "inline"), cell("C5", 240), cell("D5", "Merchandise &amp; Supplies-Groceries", "inline")]),
        (6, [cell("A6", 46250, style=1), cell("B6", "AUTOPAY PAYMENT - THANK YOU", "inline"), cell("C6", -400)]),
    ]
    sheet = '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(f'<row r="{r}">{"".join(cs)}</row>' for r, cs in rows) + "</sheetData></worksheet>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def test_import_xlsx_through_the_amex_preset(data_dir, capsys, tmp_path) -> None:
    wb = tmp_path / "activity.xlsx"
    _amex_workbook(wb)
    rc, out = _run(capsys, str(wb), "--account", "amex-platinum-0000", "--dry-run")
    assert rc == 0, out
    assert out["preset"] == "amex" and out["header_line"] == 3 and out["count"] == 3
    assert out["date_range"] == {"start": "2026-08-12", "end": "2026-08-16"} and out["transfers_marked"] == 1
    assert out["sample"][0]["merchant"] == "Blue Bottle Coffee" and out["sample"][0]["category"] == "Dining"
    rc, out = _run(capsys, str(wb), "--account", "amex-platinum-0000")
    assert rc == 0 and out["imported"] == 3 and out["file"] == "activity.xlsx" and out["source"] == "preset:amex"
    rc, out = _run(capsys, str(wb), "--account", "amex-platinum-0000", "--sheet", "Nope")
    assert rc == 2 and "sheet" in out["error"]
    rc, out = _run(capsys, str(FIX / "card.ofx"), "--account", "amex-platinum-0000", "--sheet", "x")
    assert rc == 2 and ".xlsx" in out["error"]
    rc, out = _run(capsys, str(FIX / "card.ofx"), "--account", "amex-platinum-0000", "--mapping", '{"date": "D", "description": "X", "amount": "A"}')
    assert rc == 2 and "--mapping" in out["error"]


ROWS_PAYLOAD = [
    {"date": "2026-09-08", "description": "Grocery Order (15 items)", "amount": -60.00, "merchant": "Amazon", "category": "Groceries", "detail": "Groceries/Amazon Fresh"},
    {"date": "2026-09-07", "description": "Drain Strainer Set", "amount": -10.00, "merchant": "Amazon", "category": "Shopping", "detail": "Household"},
    {"date": "2026-09-05", "description": "COSTCO WHSE #0684 SPRINGFIELD IL", "amount": -240.00, "items": [{"name": "Food", "amount": -200, "category": "Groceries", "detail": "Groceries/Costco"}, {"name": "Paper towels", "amount": -40, "category": "Shopping", "detail": "Household/Paper"}]},
]


def test_rows_import_from_file_and_stdin(data_dir, capsys, tmp_path, monkeypatch) -> None:
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps(ROWS_PAYLOAD))
    rc, out = _run(capsys, "--rows", str(payload), "--account", "amex-platinum-0000", "--source", "amazon-chat", "--dry-run")
    assert rc == 0, out
    assert out["preset"] == "rows" and out["source"] == "transcribed:amazon-chat" and out["count"] == 3 and out["header_line"] is None
    assert not (data_dir / "spending.json").exists()
    rc, out = _run(capsys, "--rows", str(payload), "--account", "amex-platinum-0000", "--source", "amazon-chat")
    assert rc == 0 and out["imported"] == 3 and out["file"] == "rows.json"
    book = _store(data_dir)
    costco = next(t for t in book["transactions"] if t["merchant"] == "Costco")
    assert costco["source"] == "transcribed:amazon-chat" and len(costco["items"]) == 2 and costco["category"] == "Groceries"
    assert book["accounts"]["amex-platinum-0000"]["preset"] == "rows"
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"rows": ROWS_PAYLOAD[:1]})))
    rc, out = _run(capsys, "--rows", "-", "--account", "amex-platinum-0000", "--source", "amazon-chat")
    assert rc == 0 and out["imported"] == 0 and out["duplicates"] == 1


def test_rows_import_dedupes_against_a_card_row(data_dir, capsys, tmp_path) -> None:
    _run(capsys, str(FIX / "amex.csv"), "--account", "amex-gold-9876")
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps([{"date": "2026-08-15", "description": "COSTCO WHSE #0684 SPRINGFIELD IL", "amount": -240.00, "category": "Groceries"}]))
    rc, out = _run(capsys, "--rows", str(payload), "--account", "amex-gold-9876", "--source", "receipt")
    assert rc == 0 and out["imported"] == 0 and out["duplicates"] == 1


def test_rows_import_validation(data_dir, capsys, tmp_path) -> None:
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps([{"date": "2026-09-08", "amount": -1}]))
    rc, out = _run(capsys, "--rows", str(payload), "--account", "x-1", "--source", "receipt")
    assert rc == 0 and out["imported"] == 0 and out["skipped"] == [{"row": 1, "reason": "no description"}]
    rc, out = _run(capsys, "--rows", str(payload), "--account", "x-1")
    assert rc == 2 and "--source" in out["error"]
    payload.write_text("[]")
    rc, out = _run(capsys, "--rows", str(payload), "--account", "x-1", "--source", "receipt")
    assert rc == 2 and "rows" in out["error"]
    rc, out = _run(capsys, str(FIX / "amex.csv"), "--rows", str(payload), "--account", "x-1", "--source", "receipt")
    assert rc == 2 and "one of" in out["error"]
    rc, out = _run(capsys, "--account", "x-1")
    assert rc == 2
