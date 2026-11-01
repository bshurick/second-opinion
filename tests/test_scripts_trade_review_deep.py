"""Trade-review deep review: decisions.py (pick and score), render_decisions.py (the page), decision_store.py (the later check)."""
from __future__ import annotations

import copy
import io
import json

import pytest
from page_dom import assert_page_help, render_and_audit, requires_chrome
from scripts_util import load_script, run_json

SCORE = "trade-review/scripts/decisions.py"
RENDER = "trade-review/scripts/render_decisions.py"
STORE = "trade-review/scripts/decision_store.py"
AS_OF = "2026-11-01"


def _trip(symbol, sell_date, proceeds, drift_vs, first_buy="2025-01-10", total_return=0.1, pnl=500.0) -> dict:
    return {"symbol": symbol, "sell_date": sell_date, "first_buy_date": first_buy, "proceeds": proceeds, "total_return": total_return, "total_pnl": pnl,
            "holding_days": 200, "drift": {"90": drift_vs}, "drift_vs_benchmark_90": drift_vs}


REVIEW = {
    "as_of": AS_OF,
    "round_trips": [_trip("AAA", "2026-03-02", 20000.0, -0.10), _trip("BBB", "2026-04-01", 10000.0, 0.12), _trip("CCC", "2026-05-01", 5000.0, 0.01), _trip("DDD", "2026-10-15", 30000.0, None)],
    "open_lots": [{"symbol": "EEE", "buy_date": "2026-01-05", "cost": 15000.0, "unrealized_return": -0.2, "holding_days": 300, "unrealized_pnl": -3000.0},
                  {"symbol": "FFF", "buy_date": "2026-10-20", "cost": 8000.0, "unrealized_return": 0.1, "holding_days": 12, "unrealized_pnl": 800.0}],
    "largest_buys": [{"symbol": "EEE", "date": "2026-01-05", "amount": -15000.0, "name": "EEE Inc"}, {"symbol": "FFF", "date": "2026-10-20", "amount": -8000.0},
                     {"symbol": "SPAXX", "date": "2026-02-01", "amount": -90000.0, "name": "Fidelity Government Money Market Fund"}],
}


def _claim(text="Earnings fell", date="2026-02-20", cut="for") -> dict:
    return {"claim": text, "cut": cut, "source": "10-Q Item 2", "date": date}


def _decision(symbol="AAA", action="sell", date="2026-03-02", quality="sound", **over) -> dict:
    row = {"id": f"{action}-{symbol}-{date}", "symbol": symbol, "action": action, "date": date, "catalyst": "earnings", "quality": quality, "grade_reason": "The reason held on the evidence",
           "known": [_claim(date=date[:8] + "01"), _claim("Guidance held", date=date[:8] + "01", cut="against")], "later": []}
    return {**row, **over}


def _params(*decisions, **over) -> dict:
    return {"as_of": AS_OF, "review": REVIEW, "decisions": list(decisions) or [_decision()], **over}


def _score(params: dict) -> dict:
    return load_script(SCORE).run_score(params)


def _flag(out: dict, code: str) -> str | None:
    return next((f["message"] for f in out["flags"] if f["code"] == code), None)


def test_pick_goes_by_money_and_shows_no_results() -> None:
    picks = load_script(SCORE).pick_decisions(REVIEW, 3)
    assert [(p["symbol"], p["action"]) for p in picks["decisions"]] == [("DDD", "sell"), ("AAA", "sell"), ("EEE", "buy")]
    text = json.dumps(picks["decisions"])
    assert "return" not in text and "pnl" not in text and "drift" not in text
    assert "SPAXX" not in text  # a money market fund is not a decision
    assert picks["decisions"][0]["id"] == "sell-DDD-2026-10-15"
    assert picks["total_decisions"] == 6 and picks["amount_covered"] == round(65000 / 88000, 4)


def test_several_lots_sold_on_one_day_are_one_decision() -> None:
    review = {**REVIEW, "round_trips": [_trip("AAA", "2026-03-02", 20000.0, -0.10), _trip("AAA", "2026-03-02", 10000.0, -0.04)], "open_lots": [], "largest_buys": []}
    picks = load_script(SCORE).pick_decisions(review, 5)["decisions"]
    assert len(picks) == 1 and picks[0]["amount"] == 30000.0
    out = _score(_params(_decision(), review=review))
    assert out["decisions"][0]["outcome"]["measure"] == -0.08  # weighted by proceeds


@pytest.mark.parametrize("symbol, action, date, quality, verdict, cell", [
    ("AAA", "sell", "2026-03-02", "sound", "good", "skill"),
    ("AAA", "sell", "2026-03-02", "weak", "good", "luck"),
    ("BBB", "sell", "2026-04-01", "sound", "bad", "bad_luck"),
    ("BBB", "sell", "2026-04-01", "weak", "bad", "mistake"),
    ("CCC", "sell", "2026-05-01", "sound", "flat", "unclear"),
    ("BBB", "sell", "2026-04-01", "mixed", "bad", "unclear"),
    ("DDD", "sell", "2026-10-15", "sound", "too_soon", "unclear"),
    ("EEE", "buy", "2026-01-05", "weak", "bad", "mistake"),
    ("FFF", "buy", "2026-10-20", "sound", "too_soon", "unclear"),
])
def test_grade_and_result_make_the_cell(symbol, action, date, quality, verdict, cell) -> None:
    row = _score(_params(_decision(symbol, action, date, quality)))["decisions"][0]
    assert row["outcome"]["verdict"] == verdict and row["cell"] == cell


def test_outcome_score_points_the_same_way_for_buys_and_sells() -> None:
    out = _score(_params(_decision(), _decision("EEE", "buy", "2026-01-05")))
    rows = {d["symbol"]: d for d in out["decisions"]}
    assert rows["AAA"]["outcome"]["score"] == 0.10 and rows["EEE"]["outcome"]["score"] == -0.2
    assert rows["AAA"]["outcome"]["basis"] == "against the benchmark, 90 days after the sale"
    assert "not benchmark-adjusted" in rows["EEE"]["outcome"]["basis"]


def test_patterns_group_results_and_mark_thin_ones() -> None:
    decisions = [_decision("AAA", quality="sound"), _decision("BBB", date="2026-04-01", quality="weak", catalyst="none"), _decision("EEE", "buy", "2026-01-05", quality="weak", catalyst="none")]
    out = _score(_params(*decisions))
    by_quality = {r["group"]: r for r in out["patterns"]["by_quality"]}
    assert by_quality["sound"]["n"] == 1 and by_quality["sound"]["avg_score"] == 0.10 and by_quality["sound"]["thin"] is True
    assert by_quality["weak"]["n"] == 2 and by_quality["weak"]["avg_score"] == round((-0.12 - 0.2) / 2, 4)
    assert out["patterns"]["process_gap"] is None
    assert {r["group"] for r in out["patterns"]["by_catalyst"]} == {"earnings", "none"}
    assert out["cells"] == {"skill": 1, "luck": 0, "bad_luck": 0, "mistake": 2, "unclear": 0}
    assert _flag(out, "SMALL_SAMPLE")


def test_process_gap_needs_three_on_each_side() -> None:
    review = {**REVIEW, "round_trips": [_trip(s, f"2026-0{i + 1}-02", 1000.0, d) for i, (s, d) in enumerate((("S1", -0.2), ("S2", -0.1), ("S3", 0.0), ("W1", 0.1), ("W2", 0.2), ("W3", 0.3)))], "open_lots": [], "largest_buys": []}
    rows = [_decision(s, "sell", f"2026-0{i + 1}-02", "sound" if s[0] == "S" else "weak") for i, s in enumerate(("S1", "S2", "S3", "W1", "W2", "W3"))]
    gap = _score(_params(*rows, review=review))["patterns"]["process_gap"]
    assert gap == round(0.1 - (-0.2), 4)


def test_flags_show_gaps_in_the_evidence() -> None:
    same_day = _decision(known=[_claim(date="2026-03-02")])
    out = _score(_params(same_day))
    assert "AAA" in _flag(out, "SAME_DAY_EVIDENCE")
    assert "AAA" in _flag(out, "ONE_SIDED_EVIDENCE")
    out = _score(_params(_decision("BBB", date="2026-04-01", quality="unknown", known=[], grade_reason="No public catalyst found")))
    assert "BBB" in _flag(out, "NO_PUBLIC_EVIDENCE")
    assert _flag(_score(_params(_decision("DDD", date="2026-10-15"))), "RESULTS_TOO_SOON")
    assert _flag(_score(_params()), "BUYS_NOT_ADJUSTED") is None
    assert _flag(_score(_params(_decision("EEE", "buy", "2026-01-05"))), "BUYS_NOT_ADJUSTED")


def test_a_buy_with_no_lot_left_has_no_result() -> None:
    review = {**REVIEW, "open_lots": [], "largest_buys": [{"symbol": "EEE", "date": "2026-01-05", "amount": -15000.0}]}
    out = _score(_params(_decision("EEE", "buy", "2026-01-05"), review=review))
    assert out["decisions"][0]["outcome"]["verdict"] == "unavailable" and out["decisions"][0]["cell"] == "unclear"
    assert _flag(out, "NO_RESULT")


def test_a_later_claim_stays_apart_from_what_was_known() -> None:
    row = _score(_params(_decision(later=[{"claim": "Fraud found", "source": "SEC", "date": "2026-06-01"}])))["decisions"][0]
    assert row["later"][0]["claim"] == "Fraud found" and all(k["date"] <= row["date"] for k in row["known"])


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["known"][0].update(date="2026-03-03"), "after the decision"),
    (lambda d: d["known"][0].pop("source"), "source"),
    (lambda d: d["known"][0].pop("date"), "date"),
    (lambda d: d["known"][0].update(cut="maybe"), "cut"),
    (lambda d: d.update(later=[{"claim": "x", "source": "y", "date": "2026-02-01"}]), "known"),
    (lambda d: d.update(quality="great"), "quality"),
    (lambda d: d.update(known=[]), "no evidence"),
    (lambda d: d.update(known=[_claim(cut="against", date="2026-03-01")]), "in favor"),
    (lambda d: d.update(action="hold"), "action"),
    (lambda d: d.update(date="2026-03-09"), "not in the review"),
    (lambda d: d.update(symbol="ZZZ"), "not in the review"),
    (lambda d: d.update(grade_reason=""), "grade_reason"),
    (lambda d: d.update(catalyst="vibes"), "catalyst"),
])
def test_hindsight_and_unsourced_grades_are_rejected(mutate, needle) -> None:
    row = copy.deepcopy(_decision())
    mutate(row)
    with pytest.raises(ValueError, match=needle):
        _score(_params(row))


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="twice"):
        _score(_params(_decision(), _decision()))


def test_the_cli_picks_and_scores(monkeypatch, capsys) -> None:
    mod = load_script(SCORE)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REVIEW)))
    assert mod.main(["--pick", "2"]) == 0
    assert len(json.loads(capsys.readouterr().out)["decisions"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"as_of": AS_OF})))
    assert mod.main([]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


def _page(**over) -> dict:
    return {"as_of": AS_OF, "headline": "Two of three large sales held up on what was known at the time.", "summary": "The evidence behind the sales was stronger than the buys.",
            "review": _score(_params(_decision(), _decision("EEE", "buy", "2026-01-05", "weak"))), "missing_roles": ["Red team"], "notes": [], **over}


def test_render_builds_the_page(tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0, res
    assert res["title"] == "Decision Review" and res["decisions"] == 2 and res["flags"] >= 2
    html = out.read_text()
    for section in ("Skill or luck", "Decisions", "Patterns", "Flags"):
        assert section in html


@requires_chrome
def test_every_card_on_the_page_has_help(tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    assert_page_help(render_and_audit(RENDER, ["--in", str(src)], tmp_path, capsys))


@pytest.mark.parametrize("over, needle", [
    ({"headline": "You should stop selling"}, "should"),
    ({"headline": " ".join(["word"] * 26)}, "25 words"),
    ({"headline": ""}, "headline"),
    ({"summary": "We advise holding longer"}, "advise"),
    ({"review": {}}, "review"),
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
    return tmp_path


def _write(tmp_path, review) -> str:
    path = tmp_path / "new-review.json"
    path.write_text(json.dumps(review))
    return str(path)


def test_list_shows_saved_reviews(saved, capsys) -> None:
    rc, res = run_json(load_script(STORE), ["list"], capsys)
    assert rc == 0 and res["reviews"][0]["as_of"] == AS_OF and res["reviews"][0]["decisions"] == 2


def test_check_keeps_grades_and_updates_results(saved, capsys) -> None:
    later = copy.deepcopy(REVIEW)
    later["open_lots"][0]["unrealized_return"] = 0.3
    rc, out = run_json(load_script(STORE), ["check", "--review", _write(saved, later), "--as-of", "2026-12-01"], capsys)
    assert rc == 0, out
    eee = next(d for d in out["decisions"] if d["symbol"] == "EEE")
    assert eee["quality"] == "weak" and eee["then"]["verdict"] == "bad" and eee["now"]["verdict"] == "good"
    assert eee["then_cell"] == "mistake" and eee["now_cell"] == "luck"
    assert out["review_age_days"] == 30 and out["rerun_due"] is False
    assert out["changed"] == ["buy-EEE-2026-01-05"]


def test_check_says_when_a_position_has_left_the_review(saved, capsys) -> None:
    later = copy.deepcopy(REVIEW)
    later["open_lots"] = later["open_lots"][1:]
    rc, out = run_json(load_script(STORE), ["check", "--review", _write(saved, later), "--as-of", "2026-12-01"], capsys)
    assert rc == 0
    assert next(d for d in out["decisions"] if d["symbol"] == "EEE")["now"]["verdict"] == "unavailable"


def test_check_is_due_when_old_or_large_new_decisions_appear(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", "--review", _write(saved, REVIEW), "--as-of", "2027-06-01"], capsys)
    assert rc == 0 and any("180 days" in r for r in out["rerun_reasons"])
    later = copy.deepcopy(REVIEW)
    later["round_trips"].append(_trip("NEW", "2026-11-20", 50000.0, None))
    rc, out = run_json(load_script(STORE), ["check", "--review", _write(saved, later), "--as-of", "2026-12-01"], capsys)
    assert rc == 0 and [d["id"] for d in out["new_large_decisions"]] == ["sell-NEW-2026-11-20"]
    assert any("sell-NEW-2026-11-20" in r for r in out["rerun_reasons"])


def test_check_with_nothing_saved_exits_2(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "empty"))
    rc, out = run_json(load_script(STORE), ["check", "--review", _write(tmp_path, REVIEW)], capsys)
    assert rc == 2 and "no saved review" in out["error"]
