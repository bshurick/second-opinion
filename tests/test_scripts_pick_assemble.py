"""pick_assemble.py: the gate, pick.json and the picks page from a run folder and the finalists'
deep-valuation folders. Pure file work; every figure is invented."""

from __future__ import annotations

import json
import shlex

import pytest
from scripts_util import load_script, run_json

assemble = load_script("stock-screener/scripts/pick_assemble.py")
GATE = load_script("stock-screener/scripts/gate.py")

THESIS = 'Steady rail volumes; a $100M buyback at 9x "owner earnings" — it\'s cheap & dull <b>.'
URLS = {s: f"https://claude.ai/artifact/{s.lower()}-0001" for s in ("SAFE", "ABOVE", "LOSS")}
SCEN = {"SAFE": [("Base", 62, 0.11), ("Bear", 45, 0.03)], "ABOVE": [("Base", 70, 0.15), ("Bear", 55, 0.08)], "LOSS": [("Base", 60, 0.12), ("Bear", 40, -0.02)]}


def write_case(cases, symbol, scen, price=50.0, used=None):
    case = cases / f"deep-{symbol}"
    case.mkdir(parents=True, exist_ok=True)
    model = {"symbol": symbol, "price": price, "scenarios": [{"name": n, "value_per_share": v, "summary": "s"} for n, v, _ in scen],
             "implied": {"field": "margin_shift", "value": -0.01}, "flags": []}
    returns = {"mode": "paths", "price": price, "horizon": 5, "hurdle": 0.10, "scenarios": [{"name": n, "irr": r} for n, _, r in scen], "flags": []}
    (case / "model.out.json").write_text(json.dumps(model))
    (case / "returns.out.json").write_text(json.dumps(returns))
    (case / "page.json").write_text("{}")
    if used is not None:
        caps = {"forensic": 1, "claims": 3, "industry": 4, "segments": 1, "threads": 8, "threads_round2": 4, "red_team": 2}
        (case / "budget.json").write_text(json.dumps({"plan": "valuation-picker", "caps": caps, "used": {**{k: 0 for k in caps}, "threads": used}}))
    return case


def card(ticker, **over) -> dict:
    c = {"ticker": ticker, "name": f"{ticker} Inc", "industry": "Railroads", "origin": "industry",
         "scores": {"quality": 4, "direction": 3, "tailwind": 4, "value": 3}, "reasons": {k: f"{k}: a $2.9B backlog" for k in ("quality", "direction", "tailwind", "value")},
         "missing": "Market misses X.", "bad_pick": "If Y.", "health": "passed", "quick_value": {"fair_value": 60.0, "irr_5y": 0.1}, "red_flags": [],
         "evidence": [{"claim": "c", "source": "10-K Item 7", "date": "2026-02-20"}]}
    c.update(over)
    return c


def industry(name, verdict="favored") -> dict:
    return {"sector": "Industrials", "industry": name, "verdict": verdict, "contrarian": False, "temperature": "t", "growth": "g", "sentiment": "s",
            "leaders": [{"ticker": "UNP", "name": "Union Pacific", "trend": "gaining"}],
            "prospects": [{"ticker": "SAFE", "name": "Safe Rail", "market_cap": 2.1e9, "why": "P/E 11; a $300M market value floor"}],
            "evidence": [{"claim": "Carloads +3%", "source": "AAR", "date": "2026-09-30"}]}


def make_run(tmp_path, symbols=("SAFE", "ABOVE", "LOSS"), notes=True, budget=True, case_used=None):
    run = tmp_path / "pick-2026-11-10"
    for sub in ("industries", "cards", "screen", "context"):
        (run / sub).mkdir(parents=True)
    (run / "industries" / "group2.json").write_text(json.dumps([industry("Banks", "neutral")]))
    (run / "industries" / "group3.json").write_text(json.dumps([industry("Railroads"), industry("Steel", "unfavored")]))
    (run / "industries" / "group3.md").write_text("notes")
    for t in ("SAFE", "ABOVE", "LOSS", "OTHER"):
        (run / "cards" / f"{t}.json").write_text(json.dumps(card(t)))
        (run / "cards" / f"{t}.data.json").write_text(json.dumps({"ticker": t, "value_hint": 3}))
        (run / "cards" / f"{t}.md").write_text("notes")
        (run / "cards" / t).mkdir()
    names = [{"ticker": t, "held": t == "LOSS", "origin": "both", "industry": "Railroads"} for t in ("SAFE", "ABOVE", "LOSS", "OTHER", "UNREAD")]
    (run / "pool.json").write_text(json.dumps({"names": names, "dropped": [{"ticker": "BAD"}], "batches": [],
                                               "counts": {"industries": 3, "prospects": 9, "screen_survivors": 61, "candidates": 66, "trimmed": 26, "merged": 40, "kept": 37, "dropped": 3,
                                                          "health": {"passed": 30, "judge_in_quick_read": 2, "financial": 3, "incomplete": 2, "failed": 3}}}))
    if budget:
        (run / "budget.json").write_text(json.dumps({"plan": "picker-3", "caps": {"scanners": 18, "quick_reads": 30, "valuations": 69},
                                                     "used": {"scanners": 14, "quick_reads": 22, "valuations": 0}}))
    if notes:
        (run / "picks-notes.json").write_text(json.dumps({
            "picks": {"SAFE": {"thesis": THESIS, "bad_pick": "A freight recession that cuts $100M of volume."}, "ABOVE": {"thesis": "Cheap builder.", "bad_pick": "Rates to 8%."}},
            "missing_roles": ["ABOVE Red team"], "notes": ["Quick reads were capped at 1 search each."], "profile": "value · years · moderate risk"}, ensure_ascii=False))
    for s in symbols:
        write_case(tmp_path, s, SCEN[s], used=(case_used or {}).get(s))
    return run


def finalists_arg(symbols=("SAFE", "ABOVE", "LOSS"), urls=URLS) -> str:
    return ",".join(f"{s}={urls[s]}" for s in symbols)


def test_three_finalists_make_the_gate_the_pick_and_the_page(tmp_path, capsys) -> None:
    run = make_run(tmp_path, case_used={"SAFE": 8, "ABOVE": 6, "LOSS": 7})
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg(), "--as-of", "2026-11-10"], capsys)
    assert rc == 0, out
    gate_in = json.loads((run / "gate.json").read_text())
    assert [f["symbol"] for f in gate_in["finalists"]] == ["SAFE", "ABOVE", "LOSS"]
    assert gate_in["finalists"][0]["page"] == URLS["SAFE"] and gate_in["finalists"][0]["price"] == 50.0
    assert gate_in["finalists"][0]["model"] == json.loads((tmp_path / "deep-SAFE" / "model.out.json").read_text())
    direct = json.loads(json.dumps(GATE.run_gate(gate_in)))  # the same verdicts as gate.py run on gate.json
    assert json.loads((run / "gate.out.json").read_text()) == direct
    assert {r["symbol"]: r["verdict"] for r in direct["results"]} == {"SAFE": "pass", "ABOVE": "pass_flagged", "LOSS": "fail"}
    assert out["gate"] == {"pass": 1, "pass_flagged": 1, "fail": 1} and out["picks"] == ["SAFE", "ABOVE"] and out["near_misses"] == ["LOSS"]
    assert out["out"] == str(run / "page.html") and out["pick"] == str(run / "pick.json")

    raw = (run / "pick.json").read_text(encoding="utf-8")
    assert THESIS in json.loads(raw)["picks"]["SAFE"]["thesis"] and json.loads(raw)["picks"]["SAFE"]["thesis"] == THESIS
    assert "a $100M buyback at 9x" in raw and "A freight recession that cuts $100M of volume." in raw and "a $2.9B backlog" in raw
    pick = json.loads(raw)
    assert pick["gate"] == direct and pick["as_of"] == "2026-11-10" and pick["profile"] == "value · years · moderate risk"
    assert pick["funnel"] == [{"stage": "Industries scanned", "count": 3}, {"stage": "Screen survivors", "count": 61}, {"stage": "Merged pool", "count": 40},
                              {"stage": "Health check passed", "count": 30}, {"stage": "Kept for quick read", "count": 37}, {"stage": "Quick reads", "count": 4}, {"stage": "Finalists", "count": 3}, {"stage": "Picks", "count": 2}]
    assert [i["industry"] for i in pick["industries"]] == ["Banks", "Railroads", "Steel"]
    assert pick["industries"][1]["prospects"][0]["why"] == "P/E 11; a $300M market value floor"
    cands = {c["ticker"]: c for c in pick["candidates"]}
    assert set(cands) == {"SAFE", "ABOVE", "LOSS", "OTHER"}  # the .data.json files are not cards
    assert cands["LOSS"]["held"] is True and cands["SAFE"]["held"] is False
    assert cands["SAFE"]["finalist"] is True and cands["OTHER"]["finalist"] is False
    assert cands["SAFE"]["reasons"]["quality"] == "quality: a $2.9B backlog" and cands["SAFE"]["quick_value"] == {"fair_value": 60.0, "irr_5y": 0.1}
    assert set(pick["picks"]) == {"SAFE", "ABOVE"} and pick["missing_roles"] == ["ABOVE Red team"]
    assert pick["notes"][0] == "Quick reads were capped at 1 search each."
    searches = next(n for n in pick["notes"] if n.startswith("Searches"))
    assert "57 used of 117 planned" in searches and "scanners 14 of 18" in searches and "quick reads 22 of 30" in searches and "valuations 21 of 69" in searches

    html = (run / "page.html").read_text(encoding="utf-8")
    assert "a $100M buyback at 9x" in html and "Deep picks" in html and URLS["SAFE"] in html

    assert len(out["save_commands"]) == 2
    words = shlex.split(out["save_commands"][0])
    assert words[1].endswith("picks.py") and words[2:4] == ["save-deep", "SAFE"]
    assert words[words.index("--case") + 1] == str(tmp_path / "deep-SAFE")
    assert words[words.index("--thesis") + 1] == THESIS and words[words.index("--source") + 1] == URLS["SAFE"]
    assert shlex.split(out["save_commands"][1])[3] == "ABOVE"
    assert out["flags"] == []


def test_missing_model_output_is_exit_2_and_nothing_is_written(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    (tmp_path / "deep-ABOVE" / "model.out.json").unlink()
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg()], capsys)
    assert rc == 2 and "ABOVE" in out["error"] and "model.out.json" in out["error"]
    for name in ("gate.json", "gate.out.json", "pick.json", "page.html"):
        assert not (run / name).exists()
    (tmp_path / "deep-ABOVE" / "model.out.json").write_text("{half")
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg()], capsys)
    assert rc == 2 and "ABOVE" in out["error"] and not (run / "gate.json").exists()
    (tmp_path / "deep-SAFE" / "returns.out.json").unlink()
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", "SAFE=" + URLS["SAFE"]], capsys)
    assert rc == 2 and "SAFE" in out["error"] and "returns.out.json" in out["error"] and not (run / "gate.json").exists()


@pytest.mark.parametrize("finalists", [
    "SAFE=http://claude.ai/artifact/x", "SAFE=javascript:alert(1)", "SAFE", "SAFE=", "=https://x.example/a",
    f"SAFE={URLS['SAFE']},SAFE={URLS['SAFE']}", "not a ticker!=https://x.example/a",
])
def test_bad_finalists_are_exit_2_before_anything_is_written(finalists, tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists], capsys)
    assert rc == 2 and "error" in out
    assert not (run / "gate.json").exists() and not (run / "pick.json").exists() and not (run / "page.html").exists()


def test_http_link_names_https(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", f"SAFE={URLS['SAFE']},LOSS=http://claude.ai/artifact/loss"], capsys)
    assert rc == 2 and "https" in out["error"] and "LOSS" in out["error"]


def test_thesis_for_a_gate_failure_is_dropped_with_a_note(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    notes = json.loads((run / "picks-notes.json").read_text())
    notes["picks"]["LOSS"] = {"thesis": "It was cheap.", "bad_pick": "It stays cheap."}
    notes["picks"]["GHOST"] = {"thesis": "Never valued.", "bad_pick": "n/a"}
    del notes["picks"]["ABOVE"]
    custom = tmp_path / "my-notes.json"
    custom.write_text(json.dumps(notes))
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg(), "--notes", str(custom)], capsys)
    assert rc == 0, out
    pick = json.loads((run / "pick.json").read_text())
    assert set(pick["picks"]) == {"SAFE"}
    assert any("LOSS" in n and "did not pass the gate" in n for n in pick["notes"])
    assert any("GHOST" in n and "not a finalist" in n for n in pick["notes"])
    assert "It was cheap." not in (run / "pick.json").read_text()
    codes = {f["code"] for f in out["flags"]}
    assert codes == {"PICK_NOTE_DROPPED", "THESIS_MISSING"}
    assert len(out["save_commands"]) == 2 and "--thesis" not in out["save_commands"][1]  # ABOVE passed without a thesis


def test_invalid_card_fails_validation_and_writes_nothing(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    (run / "cards" / "OTHER.json").write_text(json.dumps(card("OTHER", scores={"quality": 6, "direction": 3, "tailwind": 4, "value": 3})))
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg()], capsys)
    assert rc == 2 and "OTHER" in out["error"] and "score" in out["error"]
    for name in ("gate.json", "gate.out.json", "pick.json", "page.html"):
        assert not (run / name).exists()


def test_hurdle_floor_cases_and_missing_extras(tmp_path, capsys) -> None:
    run = make_run(tmp_path, symbols=(), notes=False, budget=False)
    cases = tmp_path / "elsewhere"
    write_case(cases, "LOSS", SCEN["LOSS"])
    (cases / "deep-LOSS" / "page.json").unlink()
    (run / "pool.json").unlink()
    (run / "cards" / "ABOVE.json").write_text("{half")
    (run / "industries" / "scan3-scratch.json").write_text(json.dumps({"not": "a list"}))
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", "loss=" + URLS["LOSS"], "--cases", str(cases), "--hurdle", "0.07", "--floor", "-0.03"], capsys)
    assert rc == 0, out
    gate_in = json.loads((run / "gate.json").read_text())
    assert gate_in["hurdle"] == 0.07 and gate_in["floor"] == -0.03
    assert out["picks"] == ["LOSS"] and out["gate"]["pass"] == 1
    pick = json.loads((run / "pick.json").read_text())
    assert [s["stage"] for s in pick["funnel"]] == ["Industries scanned", "Quick reads", "Finalists", "Picks"]
    assert pick["picks"] == {} and pick["missing_roles"] == [] and len(pick["as_of"]) == 10
    assert {c["ticker"] for c in pick["candidates"]} == {"SAFE", "LOSS", "OTHER"} and all(c["held"] is False for c in pick["candidates"])
    assert {f["code"] for f in out["flags"]} == {"POOL_MISSING", "BUDGET_UNAVAILABLE", "CARD_SKIPPED", "INDUSTRY_FILE_SKIPPED", "THESIS_MISSING", "CASE_PAGE_MISSING"}
    assert str(cases / "deep-LOSS") in out["save_commands"][0]


def test_bad_notes_file_and_run_folder_are_exit_2(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg(), "--notes", str(tmp_path / "nope.json")], capsys)
    assert rc == 2 and "nope.json" in out["error"]
    (run / "picks-notes.json").write_text(json.dumps({"picks": ["SAFE"]}))
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg()], capsys)
    assert rc == 2 and "picks" in out["error"]
    rc, out = run_json(assemble, ["--run", str(tmp_path / "nope"), "--finalists", finalists_arg()], capsys)
    assert rc == 2 and "error" in out
    assert not (run / "gate.json").exists()


def test_run_budget_counts_valuations_itself_without_case_budgets(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    (run / "budget.json").write_text(json.dumps({"plan": "picker-3", "caps": {"scanners": 18, "quick_reads": 30, "valuations": 69},
                                                 "used": {"scanners": 10, "quick_reads": 20, "valuations": 40}}))
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg()], capsys)
    assert rc == 0
    searches = next(n for n in json.loads((run / "pick.json").read_text())["notes"] if n.startswith("Searches"))
    assert "70 used of 117 planned" in searches and "valuations 40 of 69" in searches


def _set_pool(run, counts, names=None):
    pool = json.loads((run / "pool.json").read_text())
    pool["counts"] = counts
    if names is not None:
        pool["names"] = names
    (run / "pool.json").write_text(json.dumps(pool))


def _funnel(run, tmp_path, capsys):
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg(), "--as-of", "2026-11-10"], capsys)
    assert rc == 0, out
    return {s["stage"]: s["count"] for s in json.loads((run / "pick.json").read_text())["funnel"]}, out


def test_health_stage_counts_only_passed_names(tmp_path, capsys) -> None:
    """kept includes financial, incomplete, not-found and judge-in-quick-read names: they did not pass."""
    run = make_run(tmp_path)
    _set_pool(run, {"screen_survivors": 20, "merged": 12, "kept": 10, "dropped": 2,
                    "health": {"passed": 4, "judge_in_quick_read": 1, "financial": 2, "not_found": 1, "incomplete": 2, "failed": 2}})
    funnel, out = _funnel(run, tmp_path, capsys)
    assert funnel["Health check passed"] == 4 and funnel["Kept for quick read"] == 10
    assert list(funnel) == ["Industries scanned", "Screen survivors", "Merged pool", "Health check passed", "Kept for quick read", "Quick reads", "Finalists", "Picks"]
    assert "HEALTH_NOT_CHECKED" not in {f["code"] for f in out["flags"]}


def test_health_check_that_did_not_run_shows_no_name_as_passed(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    _set_pool(run, {"screen_survivors": 20, "merged": 12, "kept": 12, "dropped": 0, "health": {"unchecked": 12}})
    funnel, out = _funnel(run, tmp_path, capsys)
    assert "Health check passed" not in funnel and funnel["Kept for quick read"] == 12
    assert "HEALTH_NOT_CHECKED" in {f["code"] for f in out["flags"]}
    assert any("health check did not run" in n for n in json.loads((run / "pick.json").read_text())["notes"])


def test_health_stage_from_the_pool_rows_when_counts_has_no_health(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    rows = [{"ticker": t, "held": False, "health": h} for t, h in (("SAFE", "passed"), ("ABOVE", "passed"), ("LOSS", "financial"), ("OTHER", "incomplete"))]
    _set_pool(run, {"screen_survivors": 20, "merged": 5, "kept": 4, "dropped": 1}, names=rows)
    funnel, _ = _funnel(run, tmp_path, capsys)
    assert funnel["Health check passed"] == 2 and funnel["Kept for quick read"] == 4

    _set_pool(run, {"screen_survivors": 20, "merged": 5, "kept": 4, "dropped": 1}, names=[{"ticker": "SAFE", "held": False}])  # nothing says who passed
    funnel, _ = _funnel(run, tmp_path, capsys)
    assert "Health check passed" not in funnel and funnel["Kept for quick read"] == 4


def test_a_card_written_with_a_dotted_ticker_finds_its_pool_row(tmp_path, capsys) -> None:
    run = make_run(tmp_path)
    (run / "cards" / "BRK.B.json").write_text(json.dumps(card("BRK.B")))
    pool = json.loads((run / "pool.json").read_text())
    pool["names"].append({"ticker": "BRK-B", "held": True})
    (run / "pool.json").write_text(json.dumps(pool))
    rc, out = run_json(assemble, ["--run", str(run), "--finalists", finalists_arg(), "--as-of", "2026-11-10"], capsys)
    assert rc == 0, out
    assert {c["ticker"]: c["held"] for c in json.loads((run / "pick.json").read_text())["candidates"]}["BRK.B"] is True
