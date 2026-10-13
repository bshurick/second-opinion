"""picks.py: the pick store, saving deep and light baselines, EDGAR actuals, check, due and the
hook summary. EDGAR and Yahoo are stubbed; every figure is invented."""

from __future__ import annotations

import json
from datetime import date

import pytest
from scripts_util import PLUGIN_ROOT, load_script, run_json
from second_opinion import edgar, market

PICKS = load_script("stock-screener/scripts/picks.py")
MODEL = load_script("valuation/scripts/model.py")

QUARTERS = [  # (start, end, fy, fp, form, filed, revenue, operating income, net income)
    ("2024-07-01", "2024-09-30", 2024, "Q3", "10-Q", "2024-11-01", 235.0, 30.0, 19.0),
    ("2024-10-01", "2024-12-31", 2024, "Q4", "10-K", "2025-02-20", 245.0, 31.0, 20.0),
    ("2025-01-01", "2025-03-31", 2025, "Q1", "10-Q", "2025-05-01", 240.0, 31.0, 20.0),
    ("2025-04-01", "2025-06-30", 2025, "Q2", "10-Q", "2025-08-01", 250.0, 32.0, 21.0),
    ("2025-07-01", "2025-09-30", 2025, "Q3", "10-Q", "2025-11-01", 250.0, 33.0, 22.0),
    ("2025-10-01", "2025-12-31", 2025, "Q4", "10-K", "2026-02-20", 260.0, 34.0, 23.0),
    ("2026-01-01", "2026-03-31", 2026, "Q1", "10-Q", "2026-05-01", 252.0, 33.0, 22.0),
    ("2026-04-01", "2026-06-30", 2026, "Q2", "10-Q", "2026-08-01", 263.0, 34.0, 23.0),
]
ANNUAL = [  # (start, end, fy, filed, revenue, operating income, net income)
    ("2024-01-01", "2024-12-31", 2024, "2025-02-20", 950.0, 120.0, 80.0),
    ("2025-01-01", "2025-12-31", 2025, "2026-02-20", 1000.0, 130.0, 86.0),
]
EQUITY = [("2024-12-31", 2024, "10-K", "2025-02-20", 600.0), ("2025-06-30", 2025, "10-Q", "2025-08-01", 620.0),
          ("2025-12-31", 2025, "10-K", "2026-02-20", 640.0), ("2026-06-30", 2026, "10-Q", "2026-08-01", 660.0)]


def companyfacts() -> dict:
    def dur(i: int) -> list[dict]:
        rows = [{"start": s, "end": e, "fy": fy, "fp": fp, "form": form, "filed": filed, "val": vals[i]}
                for s, e, fy, fp, form, filed, *vals in QUARTERS]
        rows += [{"start": s, "end": e, "fy": fy, "fp": "FY", "form": "10-K", "filed": filed, "val": vals[i]}
                 for s, e, fy, filed, *vals in ANNUAL]
        return rows

    eq = [{"end": e, "fy": fy, "fp": "FY" if form == "10-K" else "Q2", "form": form, "filed": filed, "val": v} for e, fy, form, filed, v in EQUITY]
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": dur(0)}},
        "OperatingIncomeLoss": {"units": {"USD": dur(1)}},
        "NetIncomeLoss": {"units": {"USD": dur(2)}},
        "StockholdersEquity": {"units": {"USD": eq}},
    }}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    state = {"price": 20.0, "next_earnings": "2026-11-05"}
    monkeypatch.setattr(edgar, "cik_for", lambda s: (1234, "Acme Corp"))
    monkeypatch.setattr(edgar, "company_facts", lambda cik: companyfacts())
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: [{"symbol": s.upper(), "price": state["price"]} for s in symbols])
    monkeypatch.setattr(market, "next_events", lambda s, today=None: {"next_earnings": state["next_earnings"], "next_ex_dividend": None})
    state["dir"] = tmp_path
    return state


def run(args: list[str], capsys):
    return run_json(PICKS, args, capsys)


def model_input() -> dict:
    return {
        "symbol": "ACME", "price": 20.0, "shares_outstanding": 100.0, "years": 10, "horizon": 5,
        "base_discount_rate": 0.09, "tax_rate": 0.25, "cost_of_debt": 0.05, "claims": {"debt": 300.0, "cash": 100.0},
        "segments": [{"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.05, "margin": 0.13,
                      "sales_to_capital": 2.0, "terminal": {"method": "gordon", "growth": 0.02}}],
        "scenarios": [{"name": "Steady", "summary": "Holds.", "must_be_true": ["Margin 13%"]},
                      {"name": "Slump", "summary": "Falls.", "must_be_true": ["Orders fall"], "overrides": {"Core": {"growth": -0.10, "margin": 0.08}}}],
    }


def case_folder(tmp_path, *, with_model: bool = True):
    case = tmp_path / "deep-ACME"
    case.mkdir()
    page = {"symbol": "ACME", "price": 20.0, "as_of": "2026-03-01", "model": MODEL.run_model(model_input()),
            "ledger": [{"id": "L1", "belief": "Pricing holds", "stakes": "high", "verdict": "supported", "headline": "Pricing"}], "blocks": []}
    (case / "page.json").write_text(json.dumps(page))
    if with_model:
        (case / "model.json").write_text(json.dumps(model_input()))
    return case, page


# --- actuals -------------------------------------------------------------------------------


def test_edgar_actuals_base_year_ttm_and_light_metrics(env) -> None:
    a = PICKS.edgar_actuals("ACME", "2026-03-01")
    assert a["base"]["period_end"] == "2025-12-31" and a["base"]["revenue"] == 1000.0 and a["base"]["operating_income"] == 130.0
    assert a["base"]["roe"] == pytest.approx(86.0 / 600.0)
    assert a["ttm"]["period_end"] == "2026-06-30" and a["ttm"]["revenue"] == 1025.0 and a["ttm"]["operating_income"] == 134.0
    assert a["ttm"]["equity_start"] == 620.0
    assert a["light"]["revenue_growth"] == pytest.approx(1025.0 / 970.0 - 1)
    assert a["light"]["operating_margin"] == pytest.approx(134.0 / 1025.0)
    assert a["latest_filed"] == "2026-08-01"


def test_base_year_is_the_one_filed_by_the_valuation_date(env) -> None:
    assert PICKS.edgar_actuals("ACME", "2026-02-01")["base"]["period_end"] == "2024-12-31"


# --- saves ---------------------------------------------------------------------------------


def test_save_deep_from_a_case_folder_keeps_page_and_model(env, capsys, tmp_path) -> None:
    case, page = case_folder(tmp_path)
    rc, out = run(["save-deep", "ACME", "--case", str(case), "--thesis", "steady compounder"], capsys)
    assert rc == 0 and out["pick"]["kind"] == "deep" and out["pick"]["added_price"] == 20.0
    assert out["pick"]["next_earnings"] == "2026-11-05" and out["pick"]["baseline_as_of"] == "2026-03-01"
    base = json.loads((env["dir"] / out["pick"]["baseline"]).read_text())
    assert base["model_input"]["segments"][0]["revenue0"] == 1000.0 and base["model"] == page["model"]


def test_save_deep_from_page_html_recovers_window_data(env, capsys, tmp_path) -> None:
    _, page = case_folder(tmp_path)
    page["notes"] = ["a string with </script> inside"]
    html = f"<html><script>window.DATA = {json.dumps(page)};</script><script>const x = 1;</script></html>"
    (tmp_path / "page.html").write_text(html)
    rc, out = run(["save-deep", "ACME", "--page", str(tmp_path / "page.html")], capsys)
    assert rc == 0
    base = json.loads((env["dir"] / out["pick"]["baseline"]).read_text())
    assert base["model"] == page["model"] and base["model_input"] is None


def test_page_without_data_is_bad_input(env, capsys, tmp_path) -> None:
    (tmp_path / "x.html").write_text("<html><body>nothing</body></html>")
    rc, out = run(["save-deep", "ACME", "--page", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "window.DATA" in out["error"]


def test_page_for_another_symbol_is_bad_input(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    rc, out = run(["save-deep", "OTHR", "--case", str(case)], capsys)
    assert rc == 2 and "ACME" in out["error"]


def test_saving_again_keeps_checks_and_list_remove(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    run(["check", "ACME", "--record"], capsys)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    rc, out = run(["list"], capsys)
    assert rc == 0 and len(out["picks"]) == 1 and len(out["picks"][0]["checks"]) == 1
    rc, out = run(["remove", "ACME"], capsys)
    assert rc == 0 and out["count"] == 0
    rc, out = run(["check", "ACME"], capsys)
    assert rc == 2 and "not a saved pick" in out["error"]


def test_save_light_measures_metrics_at_pick(env, capsys, tmp_path) -> None:
    spec = tmp_path / "light.json"
    spec.write_text(json.dumps({"thesis": "cheap compounder", "preset": "value", "fair_values": {"bear": 15, "base": 24, "bull": 30}}))
    rc, out = run(["save-light", "ACME", "--in", str(spec), "--date", "2026-09-01"], capsys)
    assert rc == 0 and out["pick"]["kind"] == "light" and out["pick"]["added_price"] == 20.0
    base = json.loads((env["dir"] / out["pick"]["baseline"]).read_text())
    assert base["metrics_at_pick"]["period_end"] == "2026-06-30" and base["fair_values"]["base"] == 24.0


def test_save_light_needs_fair_values(env, capsys, tmp_path) -> None:
    spec = tmp_path / "light.json"
    spec.write_text(json.dumps({"thesis": "x"}))
    rc, out = run(["save-light", "ACME", "--in", str(spec)], capsys)
    assert rc == 2 and "fair_values" in out["error"]


# --- check ---------------------------------------------------------------------------------


def test_check_deep_records_and_moves_next_earnings(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    env["price"], env["next_earnings"] = 22.0, "2027-02-10"
    rc, out = run(["check", "ACME", "--record"], capsys)
    assert rc == 0 and out["kind"] == "deep" and out["since_added"] == pytest.approx(0.1)
    res = out["result"]
    assert res["status"] in ("on_track", "shifting") and res["nearest"] == "Steady" and res["elapsed_years"] == pytest.approx(0.5, abs=0.01)
    assert out["recorded"]["period_end"] == "2026-06-30"
    pick = run(["list"], capsys)[1]["picks"][0]
    assert pick["next_earnings"] == "2027-02-10" and "awaiting_filing" not in pick


def test_check_with_evidence_file(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps([{"belief": "L1", "finding": "contradicts", "claim": "Price cuts", "source": "10-Q", "date": "2026-08-01"}]))
    rc, out = run(["check", "ACME", "--evidence", str(ev)], capsys)
    assert rc == 0 and out["result"]["rerun_deep"] is True and out["recorded"] is None


def test_earnings_out_but_quarter_not_filed_stays_due(env, capsys, tmp_path, monkeypatch) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    book = json.loads((env["dir"] / "picks.json").read_text())
    book["picks"][0]["next_earnings"] = "2026-10-20"  # reports Q3; EDGAR still ends at Q2
    (env["dir"] / "picks.json").write_text(json.dumps(book))
    monkeypatch.setattr(PICKS, "date", type("D", (date,), {"today": classmethod(lambda cls: date(2026, 10, 22))}))
    run(["check", "ACME", "--record"], capsys)
    pick = run(["list"], capsys)[1]["picks"][0]
    assert pick["awaiting_filing"] is True and pick["next_earnings"] == "2026-10-20"
    assert any("10-Q not in EDGAR" in line for line in PICKS.summary_lines(date(2026, 10, 23)))


def test_check_light(env, capsys, tmp_path) -> None:
    spec = tmp_path / "light.json"
    spec.write_text(json.dumps({"thesis": "t", "fair_values": {"bear": 15, "base": 24, "bull": 30}}))
    run(["save-light", "ACME", "--in", str(spec)], capsys)
    rc, out = run(["check", "ACME"], capsys)
    assert rc == 0 and out["result"]["mode"] == "light" and out["result"]["status"] == "no_new_data"
    assert out["result"]["price"]["position"] == "bear_base"


# --- due and summary -----------------------------------------------------------------------


def test_due_on_a_new_filing_and_on_a_price_move(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)  # added 2026-03-01; a 10-Q was filed 2026-08-01
    rc, out = run(["due"], capsys)
    assert rc == 0 and [d["symbol"] for d in out["due"]] == ["ACME"]
    assert [r["code"] for r in out["due"][0]["reasons"]] == ["NEW_FILING"]
    run(["check", "ACME", "--record"], capsys)
    assert run(["due"], capsys)[1]["due"] == []
    env["price"] = 24.0
    out = run(["due"], capsys)[1]
    assert [r["code"] for r in out["due"][0]["reasons"]] == ["PRICE_MOVE"]


def test_summary_is_silent_without_picks(env) -> None:
    assert PICKS.summary_lines() == []


def test_summary_marks_earnings_and_price_moves(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case), "--date", "2026-09-01"], capsys)
    lines = PICKS.summary_lines(date(2026, 10, 1))
    assert lines == ["Pick re-check: 1 picks tracked, none due; next earnings ACME 2026-11-05."]
    assert "reported 2026-11-05" in PICKS.summary_lines(date(2026, 11, 6))[1]
    (env["dir"] / "watchlist-last-check.json").write_text(json.dumps({"watchlist": [{"symbol": "ACME", "price": 25.0}]}))
    assert "price +25.0%" in PICKS.summary_lines(date(2026, 10, 1))[1]


def test_summary_command_prints_text_and_exits_zero_on_a_corrupt_store(env, capsys) -> None:
    (env["dir"] / "picks.json").write_text("{not json")
    assert PICKS.main(["summary"]) == 0
    assert "could not be read" in capsys.readouterr().out


def test_hook_is_registered() -> None:
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    cmds = [a for h in hooks["hooks"]["SessionStart"][0]["hooks"] for a in h.get("args", [])]
    assert any(c.endswith("hooks/picks-summary.sh") for c in cmds)
    assert (PLUGIN_ROOT / "hooks" / "picks-summary.sh").is_file()


def test_a_52_week_year_ending_in_january_is_kept_by_period_end(env, monkeypatch) -> None:
    facts = companyfacts()
    rev = facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    # FY2025 of a 52/53-week filer ends 2026-01-02 but SEC tags it fy=2025; its prior year ends 2025-01-03
    rev.append({"start": "2025-01-04", "end": "2026-01-02", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-17", "val": 1010.0})
    rev.append({"start": "2024-01-01", "end": "2025-01-03", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-17", "val": 960.0})
    monkeypatch.setattr(edgar, "company_facts", lambda cik: facts)
    a = PICKS.edgar_actuals("ACME", "2026-03-01")
    assert a["base"]["period_end"] == "2026-01-02" and a["base"]["revenue"] == 1010.0
    assert "2025-01-03" in [y["period_end"] for y in a["annual"]]


def test_known_at_baseline_is_the_latest_quarter_filed_by_the_valuation_date(env) -> None:
    assert PICKS.edgar_actuals("ACME", "2026-06-01")["known_at_baseline"] == "2026-03-31"
    assert PICKS.edgar_actuals("ACME", "2026-09-01")["known_at_baseline"] == "2026-06-30"


def test_an_exclusion_recorded_once_applies_to_later_checks(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    rc, out = run(["check", "ACME", "--exclude", "Core", "--record"], capsys)
    assert rc == 2  # excluding the only operating segment leaves nothing to compare
    rc, out = run(["check", "ACME", "--exclude", "Nope", "--record"], capsys)
    assert rc == 0 and run(["list"], capsys)[1]["picks"][0]["exclude_segments"] == ["Nope"]
    rc, out = run(["check", "ACME"], capsys)
    assert "SEGMENTS_EXCLUDED" in {f["code"] for f in out["result"]["flags"]}
    run(["check", "ACME", "--exclude", "", "--record"], capsys)
    assert run(["list"], capsys)[1]["picks"][0]["exclude_segments"] == []


def test_actuals_carry_the_ttm_known_at_the_valuation(env) -> None:
    a = PICKS.edgar_actuals("ACME", "2026-06-01")
    assert a["ttm_at_baseline"]["period_end"] == "2026-03-31" and a["ttm_at_baseline"]["revenue"] == 1012.0


def test_first_filed_is_the_earliest_under_any_concept(env, monkeypatch) -> None:
    facts = companyfacts()
    # the preferred concept reports FY2025 only as a comparative in a later 10-K; another concept filed it on time
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [r for r in facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"] if r["end"] != "2025-12-31" or r["fp"] != "FY"]
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append({"start": "2025-01-01", "end": "2025-12-31", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2027-02-20", "val": 1000.0})
    facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-12-31", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-20", "val": 1000.0}]}}
    monkeypatch.setattr(edgar, "company_facts", lambda cik: facts)
    assert PICKS.edgar_actuals("ACME", "2026-03-01")["base"]["period_end"] == "2025-12-31"


def test_ttm_skips_a_window_with_a_missing_quarter() -> None:
    series = {e: {"val": 1.0} for e in ("2025-03-31", "2025-06-30", "2025-12-31", "2026-03-31", "2026-06-30")}
    assert PICKS._ttm(series) is None  # 2025-09-30 is missing, so no four consecutive quarters exist
    series["2025-09-30"] = {"val": 1.0}
    assert PICKS._ttm(series)[0] == "2026-06-30"


def test_save_light_refuses_without_a_year_earlier_ttm(env, capsys, tmp_path, monkeypatch) -> None:
    facts = companyfacts()
    for c in facts["facts"]["us-gaap"].values():
        c["units"]["USD"] = [r for r in c["units"]["USD"] if r["end"] >= "2025-03-31" or r.get("fp") == "FY"]
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [r for r in facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"] if r["end"] > "2025-01-01"]
    monkeypatch.setattr(edgar, "company_facts", lambda cik: facts)
    spec = tmp_path / "light.json"
    spec.write_text(json.dumps({"thesis": "t", "fair_values": {"bear": 1, "base": 2, "bull": 3}}))
    rc, out = run(["save-light", "ACME", "--in", str(spec)], capsys)
    assert rc == 2 and "year-earlier" in out["error"]


def test_a_corrupt_baseline_is_bad_input_not_a_crash(env, capsys, tmp_path) -> None:
    case, _ = case_folder(tmp_path)
    out = run(["save-deep", "ACME", "--case", str(case)], capsys)[1]
    (env["dir"] / out["pick"]["baseline"]).write_text("{oops")
    rc, out = run(["check", "ACME"], capsys)
    assert rc == 2 and "baseline" in out["error"]


def test_due_with_edgar_down_flags_it_and_still_checks_price(env, capsys, tmp_path, monkeypatch) -> None:
    case, _ = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case)], capsys)
    from second_opinion.errors import ApiError

    def down(cik):
        raise ApiError("EDGAR 503", code="EDGAR_HTTP")
    monkeypatch.setattr(edgar, "company_facts", down)
    env["price"] = 30.0
    rc, out = run(["due"], capsys)
    assert rc == 0 and out["flags"][0]["code"] == "EDGAR_UNAVAILABLE"
    assert [r["code"] for r in out["due"][0]["reasons"]] == ["PRICE_MOVE"]


# --- price levels in summary and due -------------------------------------------------------


def _levels(env, tmp_path, capsys):
    case, page = case_folder(tmp_path)
    run(["save-deep", "ACME", "--case", str(case), "--date", "2026-09-01", "--added-price", "5"], capsys)  # a normal level
    lv = PICKS.pick_levels(page)
    return lv["hurdle"], lv["central"]


def test_summary_flags_a_price_above_every_scenario(env, capsys, tmp_path) -> None:
    hurdle, central = _levels(env, tmp_path, capsys)  # in this model the central scenario is also the best
    (env["dir"] / "watchlist-last-check.json").write_text(json.dumps({"watchlist": [{"symbol": "ACME", "price": central * 1.05}]}))
    lines = PICKS.summary_lines(date(2026, 10, 1))
    assert any("above every scenario" in line for line in lines)


def test_summary_flags_the_hurdle_price(env, capsys, tmp_path) -> None:
    hurdle, central = _levels(env, tmp_path, capsys)
    (env["dir"] / "watchlist-last-check.json").write_text(json.dumps({"watchlist": [{"symbol": "ACME", "price": (hurdle + central) / 2}]}))
    assert any("stops earning the hurdle" in line for line in PICKS.summary_lines(date(2026, 10, 1)))


def test_summary_flags_the_central_value_for_a_light_pick(env, capsys, tmp_path) -> None:
    spec = tmp_path / "light.json"
    spec.write_text(json.dumps({"thesis": "t", "fair_values": {"bear": 15, "base": 24, "bull": 30}}))
    run(["save-light", "ACME", "--in", str(spec)], capsys)  # added at 20: between bear and base
    (env["dir"] / "watchlist-last-check.json").write_text(json.dumps({"watchlist": [{"symbol": "ACME", "price": 26.0}]}))
    assert any("above the central value (24.00)" in line for line in PICKS.summary_lines())


def test_a_level_already_recorded_is_not_flagged_again(env, capsys, tmp_path) -> None:
    hurdle, best = _levels(env, tmp_path, capsys)
    env["price"] = best * 1.05
    run(["check", "ACME", "--record"], capsys)
    book = json.loads((env["dir"] / "picks.json").read_text())
    assert book["picks"][0]["checks"][-1]["price_level"] == "above_all"
    (env["dir"] / "watchlist-last-check.json").write_text(json.dumps({"watchlist": [{"symbol": "ACME", "price": best * 1.06}]}))
    assert not any("above every scenario" in line for line in PICKS.summary_lines(date.today()))


def test_due_flags_a_price_level_crossing(env, capsys, tmp_path) -> None:
    hurdle, central = _levels(env, tmp_path, capsys)
    env["price"] = 5.0
    run(["check", "ACME", "--record"], capsys)  # recorded at the normal level
    env["price"] = central * 1.02
    out = run(["due", "--move", "0.99"], capsys)[1]
    codes = [r["code"] for d in out["due"] for r in d["reasons"]]
    assert "PRICE_LEVEL" in codes
