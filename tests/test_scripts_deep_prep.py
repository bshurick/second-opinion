from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts_util import load_script, run_json

from second_opinion.errors import ConfigError, InvalidInput

deep_prep = load_script("valuation/scripts/deep_prep.py")


def _fake_build(flags=("ERP_DEFAULT", "ERP_STALE"), missing=(), dilution=-0.02):
    def build(symbol, out_dir, level="card", workers=4):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        inputs = {"business_type": "industrial",
                  "assumptions": {"wacc": {"value": 0.091, "source": "weights"}, "tax_rate": {"value": 0.23, "source": "latest income statement"},
                                  "cost_of_debt": {"value": 0.061, "source": "interest / debt"}, "cost_of_equity": {"value": 0.1, "source": "CAPM"},
                                  "shares_outstanding": {"value": 953_000_000, "source": "Yahoo info.impliedSharesOutstanding (every share class)"}},
                  "dcf_input": {"wacc": 0.091, "net_debt": 5.1e9, "shares_outstanding": 953_000_000, "current_share_price": 28.4},
                  "flags": [{"code": c, "message": f"{c} message"} for c in flags]}
        (out_dir / "inputs.json").write_text(json.dumps(inputs))
        (out_dir / "edgar.json").write_text(json.dumps({"growth": {"diluted_shares_cagr": dilution}}))
        (out_dir / "fundamentals.json").write_text(json.dumps({"info": {"total_debt": 9.6e9, "total_cash": 3.7e9}}))
        (out_dir / "INDEX.md").write_text("# index\n")
        files = {n: {"path": str(out_dir / n), "ok": n not in missing} for n in ("inputs.json", "edgar.json", "fundamentals.json", "earnings.json")}
        pack = {"symbol": symbol, "as_of": "2026-11-10", "level": level, "dir": str(out_dir), "files": files, "missing": list(missing),
                "summary": {"company": "HP Inc", "price": 28.4, "market_cap": 2.7e10, "business_type": "industrial", "flags": list(flags),
                            "quick_value": {"basis": "dcf", "bear": 20.0, "base": 30.0, "bull": 40.0, "irr_5y": 0.1, "note": "n"},
                            "analysts": {"target_mean": 27.4, "count": 18}, "red_flag_hits": {}, "insiders": {"buys": 0, "sells": 3}}}
        (out_dir / "pack.json").write_text(json.dumps(pack))
        return pack

    return build


def test_case_folder_skeleton_and_budget(monkeypatch, tmp_path, capsys):
    seen = {}

    def build(symbol, out_dir, level="card", workers=4):
        seen.update(symbol=symbol, out_dir=Path(out_dir), level=level)
        return _fake_build()(symbol, out_dir, level, workers)

    monkeypatch.setattr(deep_prep.pack, "build", build)
    case = tmp_path / "deep-HPQ"
    rc, out = run_json(deep_prep, ["hpq", "--case", str(case)], capsys)
    assert rc == 0, out
    for sub in ("baseline", "research", "threads", "custom"):
        assert (case / sub).is_dir()
    assert seen == {"symbol": "HPQ", "out_dir": case / "baseline", "level": "deep"}
    assert out["symbol"] == "HPQ" and out["case"] == str(case) and out["missing"] == []
    assert out["index"] == str(case / "baseline" / "INDEX.md") and out["skeleton"] == str(case / "model.skeleton.json")
    assert out["summary"]["quick_value"]["base"] == 30.0
    assert out["budget"]["plan"] == "valuation" and out["budget"]["total"] == 25 and out["budget"]["caps"]["industry"] == 6
    assert json.loads((case / "budget.json").read_text())["plan"] == "valuation"
    assert {"ERP_DEFAULT", "ERP_STALE"} <= {f["code"] for f in out["flags"]}

    sk = json.loads((case / "model.skeleton.json").read_text())
    assert sk["symbol"] == "HPQ" and sk["price"] == 28.4
    assert sk["shares_outstanding"] == 953.0  # millions
    assert sk["base_discount_rate"] == 0.091 and sk["tax_rate"] == 0.23 and sk["cost_of_debt"] == 0.061
    assert sk["years"] == 10 and sk["horizon"] == 5 and sk["payout"] == 1 and sk["hurdle"] == 0.10
    assert sk["annual_dilution"] == -0.02
    assert sk["claims"] == {} and sk["segments"] == [] and sk["scenarios"] == []
    notes = "\n".join(sk["_notes"])
    assert "ERP_DEFAULT" in notes and "ERP_STALE" in notes and "millions" in notes
    for word in ("segments", "claims", "scenarios", "sensitivity", "research/segments.md"):
        assert word in notes, word
    assert not (case / "model.json").exists()


def test_picker_plan_industry_files_and_null_dilution(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(deep_prep.pack, "build", _fake_build(flags=(), missing=("earnings.json",), dilution=None))
    ind = tmp_path / "run" / "industries"
    ind.mkdir(parents=True)
    (ind / "pc-hardware.json").write_text('{"industry": "PC hardware", "note": "worth $100M"}')
    (ind / "pc-hardware.md").write_text("notes: $2.9B market")
    case = tmp_path / "deep-HPQ"
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(case), "--plan", "valuation-picker", "--industry", str(ind / "pc-hardware.json"), "--industry", str(ind / "pc-hardware.md")], capsys)
    assert rc == 0, out
    assert out["budget"]["caps"]["industry"] == 4 and out["budget"]["total"] == 23
    assert (case / "baseline" / "picker-industry-pc-hardware.json").read_text() == '{"industry": "PC hardware", "note": "worth $100M"}'
    assert (case / "baseline" / "picker-industry-pc-hardware.md").read_text() == "notes: $2.9B market"
    assert "picker-industry-pc-hardware.json" in (case / "baseline" / "INDEX.md").read_text()
    assert out["missing"] == ["earnings.json"] and "PACK_INCOMPLETE" in {f["code"] for f in out["flags"]}
    assert json.loads((case / "model.skeleton.json").read_text())["annual_dilution"] == 0


def test_rerun_keeps_the_budget_spent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(deep_prep.pack, "build", _fake_build())
    case = tmp_path / "deep-HPQ"
    run_json(deep_prep, ["HPQ", "--case", str(case)], capsys)
    budget = load_script("valuation/scripts/budget.py")
    run_json(budget, [str(case), "add", "claims=2"], capsys)
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(case)], capsys)
    assert rc == 0 and out["budget"]["used"]["claims"] == 2
    assert "BUDGET_KEPT" in {f["code"] for f in out["flags"]}


def test_exit_codes_pass_through(monkeypatch, tmp_path, capsys):
    def unknown(symbol, out_dir, level="card", workers=4):
        raise InvalidInput("ZZZZ is not in the SEC ticker list")

    monkeypatch.setattr(deep_prep.pack, "build", unknown)
    rc, out = run_json(deep_prep, ["ZZZZ", "--case", str(tmp_path / "a")], capsys)
    assert rc == 2 and "SEC ticker list" in out["error"]
    assert not (tmp_path / "a" / "model.skeleton.json").exists() and not (tmp_path / "a" / "budget.json").exists()

    def unconfigured(symbol, out_dir, level="card", workers=4):
        raise ConfigError("EDGAR is not configured", code="CONFIG_MISSING")

    monkeypatch.setattr(deep_prep.pack, "build", unconfigured)
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(tmp_path / "b")], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING"

    monkeypatch.setattr(deep_prep.pack, "build", _fake_build())
    rc, _ = run_json(deep_prep, ["HPQ"], capsys)
    assert rc == 2
    rc, _ = run_json(deep_prep, ["HPQ", "--case", str(tmp_path / "c"), "--plan", "picker-3"], capsys)
    assert rc == 2
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(tmp_path / "d"), "--industry", str(tmp_path / "nope.json")], capsys)
    assert rc == 2 and "nope.json" in out["error"]


def _hollow_build(symbol, out_dir, level="card", workers=4):
    """The pack when the SEC refuses every request: no edgar.json on disk, nearly everything missing."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "INDEX.md").write_text("# index\n")
    names = ("edgar.json", "inputs.json", "filings/10k-item8.txt")
    files = {n: {"path": str(out_dir / n), "ok": False, "error": "edgar.py exit 5: EDGAR returned HTTP 403 for https://www.sec.gov/files/company_tickers.json"} for n in names}
    return {"symbol": symbol, "level": level, "dir": str(out_dir), "files": files, "missing": list(names),
            "summary": {"company": None, "price": None, "quick_value": {"basis": None}}}


def test_edgar_unreadable_is_exit_5_and_names_the_default_user_agent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(deep_prep.pack, "build", _hollow_build)
    monkeypatch.setattr(deep_prep.edgar, "user_agent_is_default", lambda: True)
    case = tmp_path / "deep-HPQ"
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(case)], capsys)
    assert rc == 5, out
    assert out["code"] == "EDGAR_UNREADABLE" and "EDGAR could not be read" in out["error"] and "HTTP 403" in out["error"]
    assert "DEFAULT_USER_AGENT" in out["error"] and "EDGAR_USER_AGENT" in out["error"]
    assert [f["code"] for f in out["flags"]] == ["DEFAULT_USER_AGENT"] and "edgar.json" in out["missing"]
    assert not (case / "model.skeleton.json").exists() and not (case / "budget.json").exists()
    assert (case / "baseline").is_dir()  # the folders already made stay

    monkeypatch.setattr(deep_prep.edgar, "user_agent_is_default", lambda: False)
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(tmp_path / "b")], capsys)
    assert rc == 5 and "EDGAR could not be read" in out["error"]
    assert "DEFAULT_USER_AGENT" not in out["error"] and out["flags"] == []


def test_edgar_json_with_the_filing_index_only_goes_on(monkeypatch, tmp_path, capsys):
    """A filer without us-gaap facts: edgar.json is in missing but holds the filing index, so the SEC answered."""
    monkeypatch.setattr(deep_prep.pack, "build", _fake_build(missing=("edgar.json",)))
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(tmp_path / "deep-HPQ")], capsys)
    assert rc == 0 and out["missing"] == ["edgar.json"] and "PACK_INCOMPLETE" in {f["code"] for f in out["flags"]}


def _build_with_edgar(edgar_out, **kwargs):
    inner = _fake_build(**kwargs)

    def build(symbol, out_dir, level="card", workers=4):
        built = inner(symbol, out_dir, level, workers)
        (Path(out_dir) / "edgar.json").write_text(json.dumps(edgar_out))
        return built

    return build


def _shares(*counts):
    return [{"fiscal_year": 2020 + i, "diluted_shares": c} for i, c in enumerate(counts)]


def test_split_inflated_dilution_is_zeroed_and_flagged(monkeypatch, tmp_path, capsys):
    """NVDA: two splits make EDGAR's diluted_shares_cagr 0.4971, which model.py would compound every year."""
    edgar_out = {"growth": {"years": 9, "diluted_shares_cagr": 0.4971}, "annual": _shares(628e6, 2535e6, 2507e6, 2494e6, 24804e6, 24514e6)}
    monkeypatch.setattr(deep_prep.pack, "build", _build_with_edgar(edgar_out))
    rc, out = run_json(deep_prep, ["NVDA", "--case", str(tmp_path / "c")], capsys)
    assert rc == 0, out
    sk = json.loads((tmp_path / "c" / "model.skeleton.json").read_text())
    assert sk["annual_dilution"] == 0
    note = next(n for n in sk["_notes"] if n.startswith("annual_dilution"))
    assert "0.4971" in note and "split" in note and "fiscal 2021" in note and "fiscal 2024" in note
    flag = next(f for f in out["flags"] if f["code"] == "DILUTION_UNRELIABLE")
    assert "0.4971" in flag["message"] and "annual_dilution" in flag["message"]


def test_one_year_share_jump_zeroes_a_modest_rate(monkeypatch, tmp_path, capsys):
    edgar_out = {"growth": {"years": 5, "diluted_shares_cagr": 0.07}, "annual": _shares(100e6, 100e6, 100e6, 100e6, 140e6)}  # an IPO year or a large issue: +40%
    monkeypatch.setattr(deep_prep.pack, "build", _build_with_edgar(edgar_out))
    rc, out = run_json(deep_prep, ["RIVN", "--case", str(tmp_path / "c")], capsys)
    sk = json.loads((tmp_path / "c" / "model.skeleton.json").read_text())
    assert sk["annual_dilution"] == 0 and "DILUTION_UNRELIABLE" in {f["code"] for f in out["flags"]}
    assert "0.07" in next(n for n in sk["_notes"] if n.startswith("annual_dilution")) and "2024" in next(n for n in sk["_notes"] if n.startswith("annual_dilution"))

    edgar_out = {"growth": {"years": 5, "diluted_shares_cagr": -0.05}, "annual": _shares(100e6, 100e6, 100e6, 70e6, 81e6)}  # a reverse split: -30%
    monkeypatch.setattr(deep_prep.pack, "build", _build_with_edgar(edgar_out))
    rc, out = run_json(deep_prep, ["GE", "--case", str(tmp_path / "d")], capsys)
    assert json.loads((tmp_path / "d" / "model.skeleton.json").read_text())["annual_dilution"] == 0


@pytest.mark.parametrize("rate, counts", [(-0.03, (100e6, 97e6, 94e6, 91e6, 88.5e6)), (0.10, (100e6, 110e6, 121e6, 133e6, 146e6)), (-0.1, (100e6, 90e6, 81e6, 73e6, 66e6)), (0.02, ())])
def test_steady_buybacks_and_issuance_keep_the_rate(monkeypatch, tmp_path, capsys, rate, counts):
    monkeypatch.setattr(deep_prep.pack, "build", _build_with_edgar({"growth": {"years": 4, "diluted_shares_cagr": rate}, "annual": _shares(*counts)}))
    rc, out = run_json(deep_prep, ["HPQ", "--case", str(tmp_path / "c")], capsys)
    assert json.loads((tmp_path / "c" / "model.skeleton.json").read_text())["annual_dilution"] == rate
    assert "DILUTION_UNRELIABLE" not in {f["code"] for f in out["flags"]}


def test_thin_edgar_history_is_flagged_with_its_message(monkeypatch, tmp_path, capsys):
    """XOM's successor registrant: the filing index alone passes the EDGAR stop check, so the flag has to say it."""
    inner = _fake_build(missing=("intrinsic.json",))

    def build(symbol, out_dir, level="card", workers=4):
        built = inner(symbol, out_dir, level, workers)
        (Path(out_dir) / "edgar.json").write_text(json.dumps({"filings": {"latest_10k": None}}))
        built["summary"]["flags"] = [*built["summary"]["flags"], "THIN_EDGAR_HISTORY"]
        built["summary"]["flag_notes"] = {"THIN_EDGAR_HISTORY": "edgar.json has no annual rows; the filings may sit under a predecessor registrant."}
        return built

    monkeypatch.setattr(deep_prep.pack, "build", build)
    rc, out = run_json(deep_prep, ["XOM", "--case", str(tmp_path / "c")], capsys)
    assert rc == 0, out
    flag = next(f for f in out["flags"] if f["code"] == "THIN_EDGAR_HISTORY")
    assert "predecessor registrant" in flag["message"]
    assert any("THIN_EDGAR_HISTORY" in n for n in json.loads((tmp_path / "c" / "model.skeleton.json").read_text())["_notes"])


def test_thin_edgar_history_is_found_without_the_pack_saying_so(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(deep_prep.pack, "build", _build_with_edgar({"company": "X Holdings", "filings": {"latest_10k": None}}))
    rc, out = run_json(deep_prep, ["XOM", "--case", str(tmp_path / "c")], capsys)
    assert rc == 0 and "predecessor" in next(f for f in out["flags"] if f["code"] == "THIN_EDGAR_HISTORY")["message"]


def test_dotted_ticker_is_prepared_as_the_dash_form(monkeypatch, tmp_path, capsys):
    seen = {}

    def build(symbol, out_dir, level="card", workers=4):
        seen["symbol"] = symbol
        return _fake_build()(symbol, out_dir, level, workers)

    monkeypatch.setattr(deep_prep.pack, "build", build)
    rc, out = run_json(deep_prep, ["brk.b", "--case", str(tmp_path / "c")], capsys)
    assert rc == 0, out
    assert seen["symbol"] == "BRK-B" and out["symbol"] == "BRK-B"
    assert json.loads((tmp_path / "c" / "model.skeleton.json").read_text())["symbol"] == "BRK-B"
