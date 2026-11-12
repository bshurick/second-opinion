"""deep_run.py: one model.py + returns.py pass over a case folder, with the move against the
previous run. Pure arithmetic; every figure is invented."""

from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json
from second_opinion import edgar, market

RUN = load_script("valuation/scripts/deep_run.py")
MODEL = load_script("valuation/scripts/model.py")
RETURNS = load_script("valuation/scripts/returns.py")


def model_input(**over) -> dict:
    p = {
        "symbol": "ACME", "price": 20.0, "shares_outstanding": 100.0, "years": 10, "horizon": 5,
        "base_discount_rate": 0.09, "tax_rate": 0.25, "cost_of_debt": 0.05,
        "claims": {"debt": 300.0, "cash": 100.0}, "payout": 0.5,
        "segments": [{"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.05,
                      "margin": 0.15, "sales_to_capital": 2.0,
                      "terminal": {"method": "gordon", "growth": 0.02}}],
        "scenarios": [{"name": "Base", "summary": "Steady.", "must_be_true": ["Margin holds"]},
                      {"name": "Squeeze", "summary": "Pricing gives.", "must_be_true": ["Rivals cut price"],
                       "overrides": {"Core": {"margin": 0.10}}}],
    }
    p.update(over)
    return p


def write_case(tmp_path, payload: dict):
    case = tmp_path / "deep-ACME"
    case.mkdir(exist_ok=True)
    (case / "model.json").write_text(json.dumps(payload))
    return case


def run(case, capsys, *extra: str):
    return run_json(RUN, ["--case", str(case), *extra], capsys)


def test_first_run_writes_outputs_and_has_no_move(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    rc, out = run(case, capsys, "--label", "first model")
    assert rc == 0, out
    assert out["run"] == 1 and out["label"] == "first model" and out["price"] == 20.0
    assert out["max_move"] is None and out["round2_due"] is False and out["compared_to"] is None
    expected = json.loads(json.dumps(MODEL.run_model(model_input())))
    assert json.loads((case / "model.out.json").read_text()) == expected
    rets = json.loads((case / "returns.out.json").read_text())
    assert rets == json.loads(json.dumps(RETURNS.run_returns(expected["returns_input"])))
    assert [s["name"] for s in out["scenarios"]] == ["Base", "Squeeze"]
    base = out["scenarios"][0]
    assert set(base) == {"name", "value_per_share", "value_ex_premiums", "upside", "irr", "change_vs_prev", "stress"}
    assert base["value_per_share"] == expected["scenarios"][0]["value_per_share"]
    assert base["upside"] == expected["scenarios"][0]["upside"] and base["irr"] == rets["scenarios"][0]["irr"]
    assert base["change_vs_prev"] is None
    assert out["implied"] == expected["implied"]
    runs = json.loads((case / "runs.json").read_text())
    assert len(runs) == 1 and runs[0]["run"] == 1 and runs[0]["scenarios"][0]["value_per_share"] == base["value_per_share"]


def test_second_run_reports_the_move_and_round_two(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    first = run(case, capsys)[1]
    p = model_input()
    p["segments"][0]["margin"] = 0.30  # 15 points up; Squeeze overrides the margin, so it does not move
    p["scenarios"].append({"name": "Boom", "overrides": {"Core": {"growth": 0.08}}})
    write_case(tmp_path, p)
    rc, out = run(case, capsys, "--label", "after threads")
    assert rc == 0 and out["run"] == 2 and out["compared_to"] == 1
    by = {s["name"]: s for s in out["scenarios"]}
    v0 = first["scenarios"][0]["value_per_share"]
    assert by["Base"]["change_vs_prev"] == pytest.approx(by["Base"]["value_per_share"] / v0 - 1, abs=1e-4)
    assert by["Squeeze"]["change_vs_prev"] == 0 and by["Boom"]["change_vs_prev"] is None
    assert out["max_move"] == by["Base"]["change_vs_prev"] > 0.10 and out["round2_due"] is True
    assert [r["run"] for r in json.loads((case / "runs.json").read_text())] == [1, 2]


def test_a_small_move_does_not_call_round_two(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    run(case, capsys)
    p = model_input()
    p["segments"][0]["margin"] = 0.152
    write_case(tmp_path, p)
    out = run(case, capsys)[1]
    assert 0 < out["max_move"] <= 0.10 and out["round2_due"] is False


def test_underscore_keys_are_dropped(tmp_path, capsys) -> None:
    (tmp_path / "a").mkdir()
    plain = run(write_case(tmp_path / "a", model_input()), capsys)
    noted = model_input(_notes=["price from the quote", "fill segments"], _source={"wacc": "inputs.py"})
    (tmp_path / "b").mkdir()
    case = write_case(tmp_path / "b", noted)
    rc, out = run(case, capsys)
    assert rc == 0 and out["scenarios"] == plain[1]["scenarios"]
    assert "_notes" not in json.loads((case / "model.out.json").read_text())
    assert json.loads((case / "model.json").read_text())["_notes"] == noted["_notes"]  # the input is left alone


def test_invalid_model_is_exit_2_and_writes_nothing(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input(segments=[]))
    rc, out = run(case, capsys)
    assert rc == 2 and "segments" in out["error"]
    assert sorted(p.name for p in case.iterdir()) == ["model.json"]


def test_invalid_model_after_a_good_run_keeps_the_last_outputs(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    run(case, capsys)
    before = (case / "model.out.json").read_text()
    write_case(tmp_path, model_input(payout=1.5))
    rc, out = run(case, capsys)
    assert rc == 2 and "payout" in out["error"]
    assert (case / "model.out.json").read_text() == before and len(json.loads((case / "runs.json").read_text())) == 1


def test_missing_or_unreadable_model_json_is_exit_2(tmp_path, capsys) -> None:
    rc, out = run(tmp_path, capsys)
    assert rc == 2 and "model.json" in out["error"]
    (tmp_path / "model.json").write_text("{not json")
    rc, out = run(tmp_path, capsys)
    assert rc == 2 and "model.json" in out["error"]


def test_a_model_without_a_price_is_exit_2(tmp_path, capsys) -> None:
    p = model_input()
    del p["price"]
    case = write_case(tmp_path, p)
    rc, out = run(case, capsys)
    assert rc == 2 and "price" in out["error"] and not (case / "model.out.json").exists()


@pytest.mark.parametrize("price, position", [(1.0, "all_above_price"), (500.0, "all_below_price"), (12.0, "brackets_price")])
def test_position_against_the_price(price, position, tmp_path, capsys) -> None:
    out = run(write_case(tmp_path, model_input(price=price)), capsys)[1]
    values = [s["value_per_share"] for s in out["scenarios"]]
    assert min(values) < 12.0 < max(values) and out["position"] == position


def test_flags_come_from_the_model_and_the_returns(tmp_path, capsys) -> None:
    p = model_input(claims={"debt": 50000.0}, history={"Core": {"max_margin": 0.12}})
    out = run(write_case(tmp_path, p), capsys)[1]
    codes = {f["code"] for f in out["flags"]}
    assert {"NEGATIVE_EQUITY", "MARGIN_ABOVE_HISTORY"} <= codes  # model.py
    assert codes & {"EXIT_FLOORED", "TOTAL_LOSS"}  # returns.py


def test_case_folder_feeds_render_and_save_deep(tmp_path, capsys, monkeypatch) -> None:
    """deep_run -> render_deep --case -> picks.py save-deep --case, with ``_notes`` still in model.json."""
    case = write_case(tmp_path, model_input(_notes=["price from the quote"]))
    assert run(case, capsys)[0] == 0
    (case / "ledger.json").write_text(json.dumps([{"id": "B1", "belief": "Pricing holds", "verdict": "supported", "headline": "Pricing"}]))
    (case / "blocks.json").write_text(json.dumps({"blocks": [{"type": "ledger"}], "as_of": "2026-03-01"}))
    rc, res = run_json(load_script("valuation/scripts/render_deep.py"), ["--case", str(case)], capsys)
    assert rc == 0, res
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(edgar, "cik_for", lambda s: (1234, "Acme Corp"))
    monkeypatch.setattr(edgar, "company_facts", lambda cik: {"facts": {"us-gaap": {}}})
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: [{"symbol": s.upper(), "price": 20.0} for s in symbols])
    monkeypatch.setattr(market, "next_events", lambda s, today=None: {"next_earnings": None, "next_ex_dividend": None})
    rc, out = run_json(load_script("stock-screener/scripts/picks.py"), ["save-deep", "ACME", "--case", str(case)], capsys)
    assert rc == 0, out
    base = json.loads((tmp_path / "data" / out["pick"]["baseline"]).read_text())
    assert base["model"] == json.loads((case / "model.out.json").read_text()) and base["as_of"] == "2026-03-01"
    assert base["returns"] == json.loads((case / "returns.out.json").read_text()) and base["ledger"][0]["id"] == "B1"
    assert base["model_input"]["_notes"] == ["price from the quote"]


def test_compare_to_measures_the_round_against_the_run_before_it(tmp_path, capsys) -> None:
    """Two reruns inside one thread round, 7% then 7%: against run 1 the round moved the value over 10%."""
    case = write_case(tmp_path, model_input())
    first = run(case, capsys, "--label", "baseline")[1]
    v0 = first["scenarios"][0]["value_per_share"]
    values = {}
    for n, margin in ((2, 0.158), (3, 0.166)):
        p = model_input()
        p["segments"][0]["margin"] = margin
        write_case(tmp_path, p)
        rc, out = run(case, capsys, *(("--compare-to", "1") if n == 3 else ()))
        assert rc == 0 and out["run"] == n, out
        values[n] = out["scenarios"][0]["value_per_share"]
        if n == 2:
            assert out["compared_to"] == 1 and out["round2_due"] is False
    assert abs(values[3] / values[2] - 1) < 0.10 < values[3] / v0 - 1  # hidden against run 2, plain against run 1
    assert out["compared_to"] == 1 and out["round2_due"] is True
    assert out["scenarios"][0]["change_vs_prev"] == pytest.approx(values[3] / v0 - 1, abs=1e-4) == out["max_move"]
    runs = json.loads((case / "runs.json").read_text())
    assert [r["run"] for r in runs] == [1, 2, 3] and [r["compared_to"] for r in runs] == [None, 1, 1]
    again = run(case, capsys)[1]  # the default is still the previous run
    assert again["compared_to"] == 3 and again["max_move"] == 0


@pytest.mark.parametrize("n", ["2", "0", "7", "x"])
def test_unknown_compare_to_is_exit_2_and_writes_nothing(n, tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    run(case, capsys)
    before = (case / "runs.json").read_text()
    rc, out = run(case, capsys, "--compare-to", n)
    assert rc == 2 and "compare-to" in out["error"]
    assert (case / "runs.json").read_text() == before
    rc, out = run(case, capsys, "--compare-to", "1")
    assert rc == 0 and out["compared_to"] == 1


def test_compare_to_on_the_first_run_is_exit_2(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    rc, out = run(case, capsys, "--compare-to", "1")
    assert rc == 2 and "compare-to" in out["error"] and not (case / "runs.json").exists()


def _renamed(margin: float) -> dict:
    p = model_input()
    p["segments"][0]["margin"] = margin
    p["scenarios"][0]["name"] = "Base case"
    return p


def test_a_renamed_central_scenario_does_not_hide_its_move(tmp_path, capsys) -> None:
    """ "Base" at 50 became "Base case" at 80: no name matched, so max_move was null and round 2 was skipped."""
    case = write_case(tmp_path, model_input())
    first = run(case, capsys)[1]
    assert first["unmatched"] == [] and "SCENARIOS_CHANGED" not in {f["code"] for f in first["flags"]}
    write_case(tmp_path, _renamed(0.30))
    rc, out = run(case, capsys)
    assert rc == 0, out
    by = {s["name"]: s for s in out["scenarios"]}
    assert by["Base case"]["change_vs_prev"] is None and by["Squeeze"]["change_vs_prev"] == 0  # by name, as before
    move = by["Base case"]["value_per_share"] / first["scenarios"][0]["value_per_share"] - 1
    assert out["max_move"] == pytest.approx(move, abs=1e-4) and move > 0.10 and out["round2_due"] is True
    assert out["unmatched"] == [{"name": "Base case", "run": 2, "value_per_share": by["Base case"]["value_per_share"]},
                                {"name": "Base", "run": 1, "value_per_share": first["scenarios"][0]["value_per_share"]}]
    flag = next(f for f in out["flags"] if f["code"] == "SCENARIOS_CHANGED")
    assert "Base case" in flag["message"] and "'Base'" in flag["message"] and "first" in flag["message"]
    assert json.loads((case / "runs.json").read_text())[-1]["unmatched"] == out["unmatched"]


def test_a_renamed_central_scenario_that_barely_moved_is_flagged_without_round_two(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    run(case, capsys)
    write_case(tmp_path, _renamed(0.152))
    out = run(case, capsys)[1]
    assert 0 < out["max_move"] <= 0.10 and out["round2_due"] is False
    assert "SCENARIOS_CHANGED" in {f["code"] for f in out["flags"]} and len(out["unmatched"]) == 2


def test_added_and_dropped_scenarios_are_listed_when_the_central_one_matches(tmp_path, capsys) -> None:
    case = write_case(tmp_path, model_input())
    first = run(case, capsys)[1]
    p = model_input()
    p["scenarios"] = [p["scenarios"][0], {"name": "Boom", "overrides": {"Core": {"growth": 0.08}}}]  # Squeeze dropped, Boom added
    write_case(tmp_path, p)
    out = run(case, capsys)[1]
    assert [(u["name"], u["run"]) for u in out["unmatched"]] == [("Boom", 2), ("Squeeze", 1)]
    assert out["max_move"] == 0 and out["round2_due"] is False  # Base matched by name and did not move
    assert "SCENARIOS_CHANGED" in {f["code"] for f in out["flags"]}
    # against run 1 again with --compare-to, from a third run
    out3 = run(case, capsys, "--compare-to", "1")[1]
    assert [(u["name"], u["run"]) for u in out3["unmatched"]] == [("Boom", 3), ("Squeeze", 1)]
