"""Real-estate deep review: property_case.py (the math), render_case.py (the page), case_store.py (the later check)."""
from __future__ import annotations

import copy
import json

import pytest
from page_dom import assert_page_help, render_and_audit, requires_chrome
from scripts_util import load_script, run_json

CASE = "real-estate/scripts/property_case.py"
RENDER = "real-estate/scripts/render_case.py"
STORE = "real-estate/scripts/case_store.py"
CALC = "real-estate/scripts/realestate.py"
AS_OF = "2026-11-01"


def _in(value, basis: str = "local", source: str = "County assessor", date: str = "2026-09-01") -> dict:
    return {"value": value, "basis": basis, "source": source, "date": date}


def _stated(value) -> dict:
    return _in(value, "stated", "Stated by the person", AS_OF)


RENTAL_INPUTS = {
    "price": _in(400000, "document", "Sample listing"),
    "down_payment": _stated(100000),
    "rate": _in(0.065, "regional", "Freddie Mac PMMS"),
    "years": _stated(30),
    "closing_costs": _in(8000, "assumption", "Assumption: 2% of price", AS_OF),
    "rent": _in(2800),
    "vacancy_rate": _in(0.05),
    "property_tax_annual": _in(4800),
    "insurance_annual": _in(1800),
    "maintenance_rate": _in(0.08, "assumption", "Assumption: typical load", AS_OF),
    "hold_years": _stated(10),
    "rent_growth": _in(0.03, "regional", "BLS rent index"),
    "expense_growth": _in(0.03, "assumption", "Assumption: long-run inflation", AS_OF),
    "appreciation": _in(0.03, "assumption", "Assumption: long-run average", AS_OF),
    "sell_closing_rate": _in(0.06, "assumption", "Assumption: typical costs", AS_OF),
}

OWN_INPUTS = {
    "price": _in(500000, "document", "Sample listing"),
    "down_payment": _stated(100000),
    "rate": _in(0.065, "regional", "Freddie Mac PMMS"),
    "years": _stated(30),
    "horizon_years": _stated(7),
    "property_tax_rate": _in(0.012),
    "maintenance_rate": _in(0.01, "assumption", "Assumption: typical load", AS_OF),
    "insurance_annual": _in(1800),
    "buy_closing_rate": _in(0.02, "assumption", "Assumption: typical costs", AS_OF),
    "sell_closing_rate": _in(0.06, "assumption", "Assumption: typical costs", AS_OF),
    "appreciation": _in(0.03, "assumption", "Assumption: long-run average", AS_OF),
    "rent": _in(2800),
    "rent_growth": _in(0.03, "regional", "BLS rent index"),
    "investment_return": _in(0.06, "assumption", "Assumption: long-run average", AS_OF),
}


def _params(use: str = "rental", **over) -> dict:
    inputs = RENTAL_INPUTS if use == "rental" else OWN_INPUTS
    base = {
        "as_of": AS_OF,
        "subject": {"kind": "property", "name": "12 Sample Street, Exampleville", "use": use, "sqft": 1600},
        "inputs": copy.deepcopy(inputs),
        "scenarios": [
            {"name": "Central", "why": "The evidence as it stands", "changes": {}},
            {"name": "Soft rents", "why": "New supply", "one_time": "high",
             "changes": {"rent": _in(2500), "appreciation": _in(0.0, "assumption", "Assumption: flat prices", AS_OF)}},
            {"name": "Firm rents", "why": "Supply falls short", "one_time": "low", "changes": {"rent": _in(3000)}},
        ],
        "costs": [{"item": "Roof", "low": 10000, "high": 20000, "source": "Sample inspection report", "date": "2026-09-15"}],
        "comps": {
            "sales": [{"address": f"{n} Sample Ave", "price": p, "sqft": 1600, "date": "2026-08-01", "source": "County recorder"} for n, p in ((1, 380000), (2, 400000), (3, 420000))],
            "rents": [{"address": f"{n} Sample Ave", "rent": r, "sqft": 1600, "date": "2026-09-01", "source": "Rental listing"} for n, r in ((1, 2600), (2, 2800), (3, 3000))],
        },
        "documents": [{"kind": "listing", "status": "read", "source": "Sample listing"}, {"kind": "hoa", "status": "not_provided"}],
        "findings": [{"claim": "Vacancy is low", "side": "for", "source": "Census ACS", "date": "2026-03-01"},
                     {"claim": "Permits are rising", "side": "against", "source": "Census BPS", "date": "2026-09-01"}],
        "open_questions": [{"question": "Was the deck permitted?", "who": "The county building department"}],
        "watch": [{"what": "Rental listings nearby", "breaks_if": "Median rent falls under $2,500", "check_by": "2027-02-01"}],
    }
    return {**base, **over}


def _run(params: dict) -> dict:
    return load_script(CASE).run_case(params)


def _flag(out: dict, code: str) -> str | None:
    return next((f["message"] for f in out["flags"] if f["code"] == code), None)


def _calc(params: dict) -> dict:
    return load_script(CALC).run_realestate(params)


def _values(inputs: dict) -> dict:
    return {k: v["value"] for k, v in inputs.items()}


def test_rental_scenarios_match_the_calculator_with_costs_added() -> None:
    out = _run(_params())
    central, soft, firm = out["scenarios"]
    direct = _calc({"action": "rental", **_values(RENTAL_INPUTS), "closing_costs": 8000 + 15000})
    assert central["result"] == direct["projection"]["total_profit"]
    assert central["noi"] == direct["noi"] and central["dscr"] == direct["dscr"] and central["irr"] == direct["projection"]["irr"]
    hard = _calc({"action": "rental", **_values(RENTAL_INPUTS), "rent": 2500, "appreciation": 0.0, "closing_costs": 8000 + 20000})
    assert soft["result"] == hard["projection"]["total_profit"]
    assert soft["one_time_cost"] == 20000 and firm["one_time_cost"] == 10000 and central["one_time_cost"] == 15000


def test_home_scenarios_put_costs_in_the_closing_rate_and_add_the_mortgage() -> None:
    out = _run(_params("own", scenarios=[{"name": "Central", "why": "x", "changes": {}}, {"name": "Flat", "why": "y", "changes": {"appreciation": _in(0.0)}}]))
    central = out["scenarios"][0]
    params = {**_values(OWN_INPUTS), "buy_closing_rate": 0.02 + 15000 / 500000}
    direct = _calc({"action": "rent_vs_buy", **params})
    assert central["result"] == direct["by_year"][-1]["advantage_buy"]
    assert central["breakeven_year"] == direct["breakeven_year"]
    assert central["piti"] == _calc({"action": "mortgage", **params})["piti"]
    assert out["result_label"] == "advantage_buy"


def test_drivers_rank_changes_and_name_the_soft_spot() -> None:
    out = _run(_params())
    drivers = out["drivers"]
    assert {d["field"] for d in drivers} >= {"rent", "appreciation", "one_time_costs"}
    assert [abs(d["swing"]) for d in drivers] == sorted((abs(d["swing"]) for d in drivers), reverse=True)
    appreciation = next(d for d in drivers if d["field"] == "appreciation")
    rent = max((d for d in drivers if d["field"] == "rent"), key=lambda d: abs(d["swing"]))
    assert appreciation["soft"] is True and appreciation["basis"] == "assumption"
    assert rent["soft"] is False and rent["central_value"] == 2800
    only = _calc({"action": "rental", **_values(RENTAL_INPUTS), "appreciation": 0.0, "closing_costs": 23000})
    assert appreciation["swing"] == round(only["projection"]["total_profit"] - out["scenarios"][0]["result"], 2)
    assert out["soft_spot"]["field"] == next(d for d in drivers if d["soft"])["field"]


def test_old_local_evidence_counts_as_soft() -> None:
    params = _params()
    params["scenarios"][1]["changes"]["rent"] = _in(2500, "local", "Old survey", "2024-01-01")
    rent = next(d for d in _run(params)["drivers"] if d["field"] == "rent" and d["tested_value"] == 2500)
    assert rent["soft"] is True


def test_even_price_is_where_the_central_result_crosses_zero() -> None:
    own = _run(_params("own"))
    even = own["even_price"]
    params = {**_values(OWN_INPUTS), "price": even["price"], "buy_closing_rate": 0.02 + 15000 / even["price"]}
    assert abs(_calc({"action": "rent_vs_buy", **params})["by_year"][-1]["advantage_buy"]) < 50
    assert even["vs_price"] == round(even["price"] / 500000 - 1, 4)
    rental = _run(_params())["even_price"]
    direct = _calc({"action": "rental", **_values(RENTAL_INPUTS), "price": rental["price"]})
    assert abs(direct["cash_flow"]) < 50 and rental["measure"] == "first-year cash flow"


def test_comps_give_medians_and_the_gap_to_the_subject() -> None:
    c = _run(_params())["comps"]
    assert c["sales"]["recent"] == 3 and c["sales"]["median_price"] == 400000 and c["sales"]["median_per_sqft"] == 250.0
    assert c["sales"]["implied_value"] == 400000.0 and c["sales"]["gap"] == 0.0
    assert c["rents"]["median_rent"] == 2800 and c["rents"]["implied_rent"] == 2800.0 and c["rents"]["gap"] == 0.0


def test_few_or_old_comps_are_flagged_and_left_out_of_the_median() -> None:
    params = _params()
    params["comps"]["sales"][0]["date"] = "2024-01-01"
    out = _run(params)
    assert out["comps"]["sales"]["recent"] == 2 and out["comps"]["sales"]["median_price"] == 410000
    assert "sales" in _flag(out, "THIN_COMPS")
    assert "rents" not in _flag(out, "THIN_COMPS")
    assert _flag(_run(_params()), "THIN_COMPS") is None


def test_flags_show_the_gaps_in_the_evidence() -> None:
    out = _run(_params())
    assert "hoa" in _flag(out, "DOCUMENT_GAPS")
    assert "closing_costs" in _flag(out, "ASSUMED_INPUTS")
    assert "Was the deck permitted?" not in (_flag(out, "ASSUMED_INPUTS") or "")
    assert _flag(out, "OPEN_QUESTIONS") and _flag(out, "NOT_MODELLED")
    params = _params(findings=[{"claim": "Vacancy is low", "side": "for", "source": "ACS", "date": "2026-03-01"}])
    params["inputs"]["vacancy_rate"]["date"] = "2024-06-01"
    params["scenarios"] = params["scenarios"][:1] + [{"name": "Firm", "why": "x", "changes": {"rent": _in(3000)}}]
    out = _run(params)
    assert _flag(out, "NO_OPPOSING_EVIDENCE") and "vacancy_rate" in _flag(out, "STALE_INPUTS") and _flag(out, "NO_DOWNSIDE")


def test_a_market_review_needs_no_documents_or_comps() -> None:
    out = _run(_params(subject={"kind": "market", "name": "Exampleville", "use": "rental"}, documents=[], comps=None))
    assert _flag(out, "DOCUMENT_GAPS") is None and _flag(out, "THIN_COMPS") is None
    assert out["comps"] is None and out["scenarios"][0]["result"] is not None


@pytest.mark.parametrize("mutate, needle", [
    (lambda p: p["inputs"]["rent"].pop("source"), "source"),
    (lambda p: p["inputs"]["rent"].pop("date"), "date"),
    (lambda p: p["inputs"]["rent"].update(date="2027-06-01"), "after"),
    (lambda p: p["inputs"]["rent"].update(basis="hunch"), "basis"),
    (lambda p: p["inputs"].pop("rent"), "rent"),
    (lambda p: p["inputs"].update(rentt=_in(1)), "rentt"),
    (lambda p: p["scenarios"][1]["changes"].update(rentt=_in(1)), "rentt"),
    (lambda p: p["scenarios"][1].update(one_time="huge"), "one_time"),
    (lambda p: p["scenarios"].__delitem__(slice(1, 3)), "scenario"),
    (lambda p: p["scenarios"][1].update(name="Central"), "twice"),
    (lambda p: p["subject"].update(use="flip"), "use"),
    (lambda p: p["subject"].update(kind="planet"), "kind"),
    (lambda p: p["costs"][0].update(low=30000), "low"),
    (lambda p: p["costs"][0].pop("source"), "source"),
    (lambda p: p["comps"]["sales"][0].pop("date"), "date"),
    (lambda p: p["findings"][0].update(side="maybe"), "side"),
    (lambda p: p["findings"][0].pop("source"), "source"),
    (lambda p: p["watch"][0].pop("breaks_if"), "breaks_if"),
    (lambda p: p["documents"][0].update(status="skimmed"), "status"),
])
def test_unsourced_or_impossible_inputs_are_rejected(mutate, needle) -> None:
    params = _params()
    mutate(params)
    with pytest.raises(ValueError, match=needle):
        _run(params)


def test_the_cli_exits_2_with_an_error(monkeypatch, capsys) -> None:
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"as_of": AS_OF})))
    with pytest.raises(SystemExit) as exc:
        load_script(CASE).main()
    assert exc.value.code == 2 and "error" in json.loads(capsys.readouterr().out)


def _page(**over) -> dict:
    return {"as_of": AS_OF, "headline": "The result rests on rent, and the rent evidence is thin.", "summary": "Three recent rents back the central case.",
            "case": _run(_params()), "missing_roles": ["Red team"], "notes": [], **over}


@pytest.mark.parametrize("use", ["rental", "own"])
def test_render_builds_the_page(use, tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page(case=_run(_params(use)))))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0, res
    assert res["title"] == "Property Deep Review" and res["scenarios"] == 3 and res["flags"] >= 2
    html = out.read_text()
    assert "12 Sample Street" in html
    for section in ("Scenarios", "What moves the answer", "Inputs and evidence", "One-time costs", "Comparable", "Evidence on both sides", "Open questions", "What to watch", "Flags"):
        assert section in html


@requires_chrome
@pytest.mark.parametrize("use", ["rental", "own"])
def test_every_card_on_the_page_has_help(use, tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page(case=_run(_params(use)))))
    assert_page_help(render_and_audit(RENDER, ["--in", str(src)], tmp_path, capsys))


@pytest.mark.parametrize("over, needle", [
    ({"headline": "You should offer less"}, "should"),
    ({"headline": " ".join(["word"] * 26)}, "25 words"),
    ({"headline": ""}, "headline"),
    ({"summary": "We recommend passing"}, "recommend"),
    ({"notes": ["We advise waiting"]}, "advise"),
    ({"case": {}}, "case"),
])
def test_render_rejects(over, needle, tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page(**over)))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


@pytest.fixture
def saved(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    rc, res = run_json(load_script(STORE), ["save", "--in", str(src), "--source", "https://claude.ai/artifact/x"], capsys)
    assert rc == 0, res
    assert res["slug"] == "12-sample-street-exampleville"
    return res["slug"]


def test_list_shows_saved_cases(saved, capsys) -> None:
    rc, res = run_json(load_script(STORE), ["list"], capsys)
    assert rc == 0 and res["cases"] == [{"slug": saved, "name": "12 Sample Street, Exampleville", "use": "rental", "as_of": AS_OF, "headline": _page()["headline"], "source": "https://claude.ai/artifact/x"}]


def test_check_with_nothing_changed_matches_the_review(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", saved, "--as-of", "2026-11-15"], capsys)
    assert rc == 0, out
    assert out["scenarios"][0]["then"] == out["scenarios"][0]["now"] and out["updated"] == {}
    assert out["review_age_days"] == 14 and out["rerun_due"] is False and out["watch_due"] == []
    assert out["open_questions"] == _params()["open_questions"]


def test_check_reruns_with_updated_inputs(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", saved, "--set", "rate=0.05", "--as-of", "2026-11-15"], capsys)
    assert rc == 0, out
    direct = _calc({"action": "rental", **_values(RENTAL_INPUTS), "rate": 0.05, "closing_costs": 23000})
    assert out["scenarios"][0]["now"] == direct["projection"]["total_profit"]
    assert out["updated"] == {"rate": {"then": 0.065, "now": 0.05}}
    assert out["scenarios"][0]["moved"] == round(out["scenarios"][0]["now"] - out["scenarios"][0]["then"], 2)


def test_check_is_due_when_old_or_a_watch_item_arrives_or_the_sign_flips(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", saved, "--as-of", "2027-03-01"], capsys)
    assert rc == 0 and out["rerun_due"] is True
    assert any("90 days" in r for r in out["rerun_reasons"]) and any("watch" in r for r in out["rerun_reasons"])
    assert out["watch_due"][0]["what"] == "Rental listings nearby"
    rc, out = run_json(load_script(STORE), ["check", saved, "--set", "rent=1000", "--as-of", "2026-11-15"], capsys)
    assert rc == 0 and any("sign" in r for r in out["rerun_reasons"])


@pytest.mark.parametrize("args, needle", [
    (["check", "nowhere"], "no saved case"),
    (["check", "SLUG", "--set", "rentt=1"], "rentt"),
    (["check", "SLUG", "--set", "rent"], "FIELD=VALUE"),
    (["check", "SLUG", "--as-of", "2020-01-01"], "before"),
    (["check", "../../etc/passwd"], "no saved case"),
])
def test_check_rejects(args, needle, saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), [a.replace("SLUG", saved) for a in args], capsys)
    assert rc == 2 and needle in out["error"]
