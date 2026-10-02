from __future__ import annotations

import json

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client
from second_opinion.brokers import router

FIDELITY_CSV = """﻿

Brokerage

Run Date,Action,Symbol,Description,Type,Quantity,Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date
08/10/2026,YOU BOUGHT APPLE INC (AAPL),AAPL,APPLE INC,Cash,10,100.00,0,0.02,,-1000.02,08/12/2026
08/11/2026,DIVIDEND RECEIVED APPLE INC (AAPL),AAPL,APPLE INC,Cash,,,,,,2.60,
08/20/2026,YOU SOLD APPLE INC (AAPL),AAPL,APPLE INC,Cash,-4,110.00,0,0.01,,439.99,08/22/2026

"The data and information in this spreadsheet is provided to you solely for your use and is not for distribution."
Date downloaded 09/04/2026 10:00 AM ET
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def test_import_csv_skips_preamble_and_trailer_and_merges(data_dir, capsys) -> None:
    f = data_dir / "fid.csv"
    f.write_text(FIDELITY_CSV, encoding="utf-8")
    rc, out = run_json(load_script("statement-import/scripts/import-csv.py"), [str(f), "--account", "fid-1"], capsys)
    assert rc == 0, out
    assert out["imported"] == 3 and out["duplicates"] == 0 and out["types"] == {"BUY": 1, "DIVIDEND": 1, "SELL": 1}
    assert out["columns"]["date"] == "Run Date" and out["header_line"] == 5
    assert out["skipped_count"] == 2 and out["skipped"][0]["reason"].startswith("unparseable date")
    assert out["ledger_path"] == str(data_dir / "ledger.json") and out["ledger_count"] == 3
    book = json.loads((data_dir / "ledger.json").read_text())
    assert [t["type"] for t in book["transactions"]] == ["BUY", "DIVIDEND", "SELL"] and book["transactions"][0]["account_id"] == "fid-1"

    rc, out = run_json(load_script("statement-import/scripts/import-csv.py"), [str(f), "--account", "fid-1"], capsys)
    assert rc == 0 and out["imported"] == 0 and out["duplicates"] == 3 and out["ledger_count"] == 3


def test_import_csv_dry_run_does_not_write(data_dir, capsys) -> None:
    f = data_dir / "fid.csv"
    f.write_text(FIDELITY_CSV, encoding="utf-8")
    rc, out = run_json(load_script("statement-import/scripts/import-csv.py"), [str(f), "--dry-run"], capsys)
    assert rc == 0 and out["dry_run"] is True and out["count"] == 3 and out["transactions"][0]["account_id"] is None
    assert not (data_dir / "ledger.json").exists()


def test_import_csv_mapping_and_errors(data_dir, capsys) -> None:
    f = data_dir / "odd.csv"
    f.write_text("d,what,tkr,n,px,amt\n2026-02-01,Bought,X,1,2,-2\n")
    rc, out = run_json(load_script("statement-import/scripts/import-csv.py"), [str(f), "--mapping", json.dumps({"date": "d", "action": "what", "symbol": "tkr", "units": "n", "price": "px", "amount": "amt"})], capsys)
    assert rc == 0 and out["imported"] == 1
    rc, out = run_json(load_script("statement-import/scripts/import-csv.py"), [str(data_dir / "missing.csv")], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "missing.csv" in out["error"]
    (data_dir / "nohdr.csv").write_text("just,some,junk\n1,2,3\n")
    rc, out = run_json(load_script("statement-import/scripts/import-csv.py"), [str(data_dir / "nohdr.csv")], capsys)
    assert rc == 2 and "header" in out["error"]


ACTIVITIES = {
    "acc-1": [
        {"id": "a1", "type": "BUY", "symbol": {"symbol": "AAPL"}, "price": 100.0, "units": 10, "amount": -1000.0, "trade_date": "2026-08-10T00:00:00Z", "description": "APPLE", "fee": 0},
        {"id": "a2", "type": "DIVIDEND", "symbol": {"symbol": "AAPL"}, "units": 0, "amount": 2.6, "trade_date": "2026-08-11T00:00:00Z", "description": "DIV", "fee": 0},
    ],
    "acc-2": [{"id": "b1", "type": "CONTRIBUTION", "symbol": None, "units": 0, "amount": 500, "trade_date": "2026-08-01T00:00:00Z", "description": "EFT", "fee": 0}],
}


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_activities=lambda accounts, **kw: ACTIVITIES[accounts])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_sync_broker_pulls_two_years_per_account_and_merges(sdk, data_dir, capsys) -> None:
    rc, out = run_json(load_script("statement-import/scripts/sync-broker.py"), ["--start", "2025-01-01"], capsys)
    assert rc == 0, out
    assert [(a["account_id"], a["fetched"], a["imported"]) for a in out["accounts"]] == [("acc-1", 2, 2), ("acc-2", 1, 1)]
    assert out["ledger_count"] == 3 and out["start"] == "2025-01-01"
    assert sdk.kwargs_for("get_activities") == [{"accounts": "acc-1", "start_date": "2025-01-01"}, {"accounts": "acc-2", "start_date": "2025-01-01"}]
    rc, out = run_json(load_script("statement-import/scripts/sync-broker.py"), ["--account", "acc-2", "--start", "2025-01-01"], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-2"] and out["accounts"][0]["duplicates"] == 1


def test_sync_broker_login_first_unless_partial(sdk, data_dir, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("statement-import/scripts/sync-broker.py"), ["--start", "2025-01-01"], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH" and out["url"] == FailingDirect.LOGIN_URL and out["partial"] == "--partial"
    rc, out = run_json(load_script("statement-import/scripts/sync-broker.py"), ["--start", "2025-01-01", "--partial"], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]
    assert out["flags"][0]["code"] == "BROKER_UNAVAILABLE"


def test_sync_broker_default_start_is_within_two_years(sdk, data_dir, capsys) -> None:
    from datetime import date, timedelta

    rc, out = run_json(load_script("statement-import/scripts/sync-broker.py"), [], capsys)
    assert rc == 0 and out["start"] == (date.today() - timedelta(days=729)).isoformat()


def test_ledger_script_filters_and_summarises(data_dir, capsys) -> None:
    f = data_dir / "fid.csv"
    f.write_text(FIDELITY_CSV, encoding="utf-8")
    run_json(load_script("statement-import/scripts/import-csv.py"), [str(f), "--account", "fid-1"], capsys)
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), [], capsys)
    assert rc == 0 and out["count"] == 3 and out["symbols"] == ["AAPL"] and len(out["transactions"]) == 3 and out["imports"][0]["added"] == 3
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--type", "sell", "--limit", "1"], capsys)
    assert rc == 0 and out["count"] == 3 and out["filtered"] == 1 and out["transactions"][0]["type"] == "SELL"
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--summary"], capsys)
    assert rc == 0 and "transactions" not in out


def test_ledger_script_empty(data_dir, capsys) -> None:
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), [], capsys)
    assert rc == 0 and out["count"] == 0 and out["transactions"] == [] and "import-csv.py" in out["hint"]


# ── normalize.py split_ratio ─────────────────────────────────────────────────


def test_normalize_split_ratio_matches_backend_contract() -> None:
    mod = load_script("statement-import/scripts/normalize.py")
    rows = [
        {"Date": "2026-03-01", "Action": "Stock Split", "Symbol": "NVDA", "Description": "2:1", "Quantity": "90"},
        {"Date": "2026-03-02", "Action": "Split", "Symbol": "TSLA", "Description": "3-for-2", "Quantity": "15"},
        {"Date": "2026-03-03", "Action": "Reverse Split", "Symbol": "GE", "Description": "1:10", "Quantity": "1"},
        {"Date": "2026-03-04", "Action": "Stock Split", "Symbol": "F", "Description": "NVIDIA CORP", "Quantity": "5"},
        {"Date": "2026-03-05", "Action": "Stock Split", "Symbol": "T", "Description": "effective 08/01/2026", "Quantity": "5"},
    ]
    t = mod.run_normalize({"source": "csv", "rows": rows})["transactions"]
    assert [(x["symbol"], x["split_ratio"]) for x in t] == [
        ("NVDA", 2.0), ("TSLA", 1.5), ("GE", 0.1), ("F", None), ("T", None),
    ]
    # the ratio regex runs only on SPLIT-classified rows: a BUY whose text says "2:1" must not grow it
    plain = [{"Date": "2026-03-06", "Action": "YOU BOUGHT X", "Symbol": "X", "Description": "2:1", "Quantity": "1", "Amount": "-2"}]
    t2 = mod.run_normalize({"source": "csv", "rows": plain})["transactions"]
    assert t2[0]["type"] == "BUY" and "split_ratio" not in t2[0]


# ── reconcile.py ─────────────────────────────────────────────────────────────


POSITIONS = {
    "acc-1": [
        {"symbol": {"symbol": "AAPL"}, "units": 6.02},
        {"symbol": {"symbol": "TSLA"}, "units": 1.0},
        {"symbol": {"symbol": "HOOD"}, "units": 4.0},
    ],
    "acc-2": [],
}

RECONCILE_LEDGER = [
    {"date": "2026-08-10", "type": "BUY", "symbol": "AAPL", "units": 10.0, "amount": -1000.0, "account_id": "acc-1", "source_id": "s1"},
    {"date": "2026-08-20", "type": "SELL", "symbol": "AAPL", "units": 4.0, "amount": 440.0, "account_id": "acc-1", "source_id": "s2"},
    {"date": "2026-08-21", "type": "BUY", "symbol": "TSLA", "units": 2.0, "amount": -600.0, "account_id": "acc-1", "source_id": "s3"},
    {"date": "2026-08-22", "type": "BUY", "symbol": "MSFT", "units": 3.0, "amount": -900.0, "account_id": "acc-1", "source_id": "s4"},
    {"date": "2026-08-23", "type": "BUY", "symbol": "HOOD", "units": 5.0, "amount": -500.0, "account_id": "csv-only", "source_id": "s5"},
]


def _write_ledger(data_dir, rows) -> None:
    (data_dir / "ledger.json").write_text(json.dumps({"transactions": rows, "imports": []}))


@pytest.fixture
def positions_sdk(monkeypatch):
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id, **kw: POSITIONS[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_reconcile_reports_statuses_and_unassigned(positions_sdk, data_dir, capsys) -> None:
    _write_ledger(data_dir, RECONCILE_LEDGER)
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), [], capsys)
    assert rc == 0, out
    acct = out["accounts"][0]
    assert acct["account_id"] == "acc-1" and out["accounts"][1]["symbols"] == []
    got = {s["symbol"]: s for s in acct["symbols"]}
    assert got["AAPL"]["status"] == "matched" and got["AAPL"]["diff"] == -0.02  # within 1% of 6.02
    assert got["TSLA"]["status"] == "quantity_mismatched" and got["TSLA"]["diff"] == 1.0
    assert "unrecorded split" in got["TSLA"]["likely_cause"]
    assert got["MSFT"]["status"] == "ledger_only" and got["MSFT"]["broker_units"] is None
    # diff is ledger - broker with the absent (broker) side treated as 0
    assert got["MSFT"]["ledger_units"] == 3.0 and got["MSFT"]["diff"] == 3.0
    assert "stale/manual import" in got["MSFT"]["likely_cause"]
    assert got["HOOD"]["status"] == "broker_only" and got["HOOD"]["ledger_units"] is None
    # diff is ledger - broker with the absent (ledger) side treated as 0
    assert got["HOOD"]["broker_units"] == 4.0 and got["HOOD"]["diff"] == -4.0
    assert "acquired before the import window" in got["HOOD"]["likely_cause"]
    assert out["unassigned"] == {"symbols": [{"symbol": "HOOD", "ledger_units": 5.0}]}
    assert out["summary"] == {"matched": 1, "quantity_mismatched": 1, "ledger_only": 1, "broker_only": 1}
    assert out["sources"] == {"ledger": "ledger.json", "positions": "snaptrade"}


def test_reconcile_split_entries_scale_ledger_units(positions_sdk, data_dir, capsys) -> None:
    rows = [
        {"date": "2026-01-01", "type": "BUY", "symbol": "NVDA", "units": 10.0, "amount": -100.0, "account_id": "acc-2", "source_id": "n1"},
        {"date": "2026-02-01", "type": "SPLIT", "symbol": "NVDA", "units": 5.0, "amount": None, "split_ratio": 2.0, "account_id": "acc-2", "source_id": "n2"},
        {"date": "2026-03-01", "type": "SPLIT", "symbol": "GE", "units": 3.0, "amount": None, "split_ratio": None, "account_id": "acc-2", "source_id": "n3"},
    ]
    _write_ledger(data_dir, rows)
    monkeypositions = dict(POSITIONS, **{"acc-2": [{"symbol": {"symbol": "NVDA"}, "units": 20.0}]})
    positions_sdk.bodies["get_user_account_positions"] = lambda account_id, **kw: monkeypositions[account_id]
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), ["--account", "acc-2"], capsys)
    assert rc == 0, out
    got = {s["symbol"]: s for s in out["accounts"][0]["symbols"]}
    assert got["NVDA"]["ledger_units"] == 20.0 and got["NVDA"]["status"] == "matched"  # 10 + 5x2
    assert "GE" not in got  # an unparseable split contributes 0; netted-flat symbols are skipped


def test_reconcile_scopes_accounts_and_rejects_unknown(positions_sdk, data_dir, capsys) -> None:
    _write_ledger(data_dir, RECONCILE_LEDGER)
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), ["--account", "acc-2"], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-2"]
    assert out["unassigned"]["symbols"][0]["symbol"] == "HOOD"  # unassigned uses every connected account
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), ["--account", "nope"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "nope" in out["error"]


def test_reconcile_requires_credentials(data_dir, monkeypatch, capsys) -> None:
    from second_opinion.errors import ConfigError

    monkeypatch.setattr(client, "get_client", lambda settings=None: (_ for _ in ()).throw(ConfigError("missing")))
    monkeypatch.setattr(router, "load", lambda settings=None: (_ for _ in ()).throw(ConfigError("missing")))
    _write_ledger(data_dir, RECONCILE_LEDGER)
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), [], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING"


def test_reconcile_empty_ledger_hint_and_no_accounts(data_dir, monkeypatch, capsys) -> None:
    fake = FakeSdk(list_user_accounts=[], list_brokerage_authorizations=[TRADE_AUTH])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), [], capsys)
    assert rc == 5 and out["code"] == "NO_ACCOUNTS"
    fake2 = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH], get_user_account_positions=lambda **kw: [])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake2)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake2))
    _write_ledger(data_dir, [])
    rc, out = run_json(load_script("statement-import/scripts/reconcile.py"), [], capsys)
    assert rc == 0 and "import-csv.py" in out["hint"] and out["summary"] == {"matched": 0, "quantity_mismatched": 0, "ledger_only": 0, "broker_only": 0}


# ── ledger.py --verify ───────────────────────────────────────────────────────


VERIFY_LEDGER = [
    {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_id": "acc-1", "source_id": "s1"},
    {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.01, "account_id": "acc-1", "source_id": "s2"},
    {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.05, "account_id": "acc-1", "source_id": "s3"},
    {"date": "2026-01-05", "type": "BUY", "symbol": "F", "units": 2.0, "amount": -20.0, "account_id": "csv-only", "source_id": "x1"},
    {"date": "2026-01-06", "type": "BUY", "symbol": "F", "units": 2.0, "amount": -20.0, "account_id": "csv-only", "source_id": "x2"},
    {"date": "2026-01-05", "type": "BUY", "symbol": "T", "units": 1.0, "amount": -30.0, "account_id": "acc-2", "source_id": "g1"},
    {"date": "2026-05-01", "type": "BUY", "symbol": "T", "units": 1.0, "amount": -30.0, "account_id": "acc-2", "source_id": "g2"},
]


def test_ledger_verify_flags_orphans_near_duplicates_and_gaps(positions_sdk, data_dir, capsys) -> None:
    _write_ledger(data_dir, VERIFY_LEDGER)
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--verify", "--summary"], capsys)
    assert rc == 0 and "transactions" not in out  # --summary and --verify compose
    v = out["verify"]
    assert v["orphan_accounts"] == [{"account_id": "csv-only", "rows": 2}]
    assert len(v["near_duplicates"]) == 1
    dup = v["near_duplicates"][0]
    assert dup["source_ids"] == ["s1", "s2"] and dup["amounts"] == [-100.0, -100.01] and dup["symbol"] == "AAPL"
    assert v["gaps"] == [{"account_id": "acc-2", "start": "2026-01-05", "end": "2026-05-01", "days": 116}]
    assert v["ok"] is False
    assert "verify" not in run_json(load_script("statement-import/scripts/ledger.py"), [], capsys)[1]


def test_ledger_verify_skips_orphans_without_credentials(data_dir, monkeypatch, capsys) -> None:
    from second_opinion.errors import ConfigError

    err = ConfigError("E*Trade login required (token expired)", code="ETRADE_REAUTH", hint="log in again")
    monkeypatch.setattr(client, "get_client", lambda settings=None: (_ for _ in ()).throw(err))
    monkeypatch.setattr(router, "load", lambda settings=None: (_ for _ in ()).throw(err))
    _write_ledger(data_dir, VERIFY_LEDGER)
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--verify"], capsys)
    assert rc == 0, out
    v = out["verify"]
    assert v["skipped"] == "brokerage credentials missing or a login is required (see hint)" and v["orphan_accounts"] == []
    assert v["hint"] == "log in again"
    assert len(v["near_duplicates"]) == 1 and len(v["gaps"]) == 1 and v["ok"] is False


def test_ledger_verify_does_not_call_a_failed_brokers_rows_orphans(positions_sdk, data_dir, monkeypatch, capsys) -> None:
    from fakes import fake_hub
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(positions_sdk, extra_brokers=(FailingDirect(),)))
    _write_ledger(data_dir, [
        {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_id": "KEY1", "source_id": "e1"},
    ])
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--verify", "--summary"], capsys)
    v = out["verify"]
    assert rc == 0 and v["orphan_accounts"] == []  # KEY1 belongs to the broker that is down
    assert v["flags"] == [{"code": "BROKER_UNAVAILABLE", "message": "etrade: E*Trade login required (token expired); its accounts are excluded from this run"}]
    assert "orphan check skipped" in v["skipped"] and v["ok"] is True


def test_ledger_verify_uses_the_failed_brokers_cached_ids(positions_sdk, data_dir, monkeypatch, tmp_path, capsys) -> None:
    from second_opinion.brokers import registry
    from second_opinion.brokers.snaptrade import SnapTradeBroker
    from test_brokers_router import FailingDirect

    reg = registry.Registry(tmp_path / "brokers.json")
    reg.save([{"account_id": "KEY1", "broker": "etrade", "account_number": "1234"}])
    hub = router.Hub([FailingDirect(), SnapTradeBroker(positions_sdk)], account_types={}, registry=reg)
    monkeypatch.setattr(router, "load", lambda settings=None: hub)
    _write_ledger(data_dir, [
        {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_id": "KEY1", "source_id": "e1"},
        {"date": "2026-01-11", "type": "BUY", "symbol": "F", "units": 2.0, "amount": -20.0, "account_id": "csv-only", "source_id": "x1"},
    ])
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--verify", "--summary"], capsys)
    v = out["verify"]
    assert rc == 0 and "skipped" not in v  # the cache covers the broker that is down
    assert v["orphan_accounts"] == [{"account_id": "csv-only", "rows": 1}]  # KEY1 is not an orphan
    assert v["flags"][0]["code"] == "BROKER_UNAVAILABLE"


def test_ledger_verify_reports_the_same_history_under_two_account_ids(positions_sdk, data_dir, capsys) -> None:
    _write_ledger(data_dir, [
        {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_id": "acc-1", "source_id": "s1"},
        {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_id": "KEY1", "source_id": "e1"},
    ])
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--verify", "--summary"], capsys)
    v = out["verify"]
    assert rc == 0 and v["duplicate_across_accounts_count"] == 1 and v["ok"] is False
    assert v["duplicate_across_accounts"][0] == {
        "date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_ids": ["KEY1", "acc-1"],
    }


def test_ledger_verify_ok_on_clean_ledger(positions_sdk, data_dir, capsys) -> None:
    _write_ledger(data_dir, [
        {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 1.0, "amount": -100.0, "account_id": "acc-1", "source_id": "s1"},
        {"date": "2026-02-20", "type": "SELL", "symbol": "AAPL", "units": 1.0, "amount": 100.0, "account_id": "acc-1", "source_id": "s2"},
    ])
    rc, out = run_json(load_script("statement-import/scripts/ledger.py"), ["--verify"], capsys)
    assert rc == 0 and out["verify"]["ok"] is True and out["verify"]["gaps"] == [] and out["verify"]["orphan_accounts"] == []
    assert len(out["transactions"]) == 2  # without --summary the rows are still printed
