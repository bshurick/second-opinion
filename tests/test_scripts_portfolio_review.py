"""Portfolio deep review: exposure.py (the math), render_review.py (the page), review_store.py (the later check)."""
from __future__ import annotations

import copy
import json

import pytest
from scripts_util import load_script, run_json

EXPOSURE = "portfolio-analysis/scripts/exposure.py"
RENDER = "portfolio-analysis/scripts/render_review.py"
STORE = "portfolio-analysis/scripts/review_store.py"
AS_OF = "2026-11-01"


def _book(**values) -> dict:
    values = values or {"AAA": 40000.0, "BBB": 30000.0, "FUND": 20000.0, "SPAXX": 10000.0}
    total = sum(values.values())
    return {
        "totals": {"total_value": total},
        "positions": [
            {"symbol": s, "name": "Fidelity Government Money Market Fund" if s == "SPAXX" else f"{s} Inc", "market_value": v, "weight": v / total}
            for s, v in values.items()
        ],
    }


RISK = {"correlation": {"symbols": ["AAA", "BBB", "FUND"], "matrix": [[1.0, 0.8, 0.5], [0.8, 1.0, 0.2], [0.5, 0.2, 1.0]]}}


def _link(symbol: str, share: float = 0.5, shock: float = -0.4) -> dict:
    return {"symbol": symbol, "share": share, "shock": shock, "why": f"{symbol} sells to the same buyer", "source": "10-K Item 1", "date": "2026-02-20"}


def _claim(text: str = "Orders rose") -> dict:
    return {"claim": text, "source": "Reuters", "date": "2026-10-01"}


def _bet(id_: str = "rates", **over) -> dict:
    bet = {
        "id": id_,
        "name": "Rates stay low",
        "belief": "Short rates stay under 4% through next year",
        "verdict": "contested",
        "links": [_link("AAA"), _link("BBB", 0.2, -0.5)],
        "for": [_claim()],
        "against": [_claim("Inflation rose")],
        "watch": [{"what": "Fed projections", "breaks_if": "The median rate rises above 4%", "check_by": "2027-01-15"}],
    }
    return {**bet, **over}


def _params(*bets, **over) -> dict:
    return {"as_of": AS_OF, "book": _book(), "risk": RISK, "bets": list(bets) or [_bet()], **over}


def _measure(params: dict) -> dict:
    return load_script(EXPOSURE).run_exposure(params)


def _flag(out: dict, code: str) -> str | None:
    return next((f["message"] for f in out["flags"] if f["code"] == code), None)


def test_bet_dollars_come_from_share_and_shock() -> None:
    bet = _measure(_params())["bets"][0]
    assert bet["exposed_value"] == 26000.0  # 40000 x .5 + 30000 x .2
    assert bet["exposed_pct"] == 0.26
    assert bet["loss_if_wrong"] == -11000.0  # 20000 x -.4 + 6000 x -.5
    assert bet["loss_pct"] == -0.11
    assert bet["holdings"] == 2 and bet["at_stake"] == 11000.0
    assert bet["links"][0]["exposed_value"] == 20000.0 and bet["links"][0]["loss_if_wrong"] == -8000.0


def test_income_counts_one_year_and_ranks_the_bets() -> None:
    bets = [
        _bet("small", links=[_link("AAA", 0.1, -0.1), _link("BBB", 0.1, -0.1)]),
        _bet("job", links=[_link("AAA", 0.1, -0.1)], income_links=[{"income": "pay", "share": 1.0, "shock": -0.5, "why": "Same employer", "source": "person", "date": AS_OF}]),
    ]
    out = _measure(_params(*bets, income=[{"id": "pay", "name": "Paycheck", "annual": 100000.0}]))
    assert [b["id"] for b in out["bets"]] == ["job", "small"]
    assert out["bets"][0]["income_at_risk"] == 50000.0 and out["bets"][0]["at_stake"] == 50400.0
    assert out["largest"] == "job"
    assert out["totals"]["income_included"] is True


def test_bets_overlap_so_losses_are_never_summed() -> None:
    out = _measure(_params(_bet("a", links=[_link("AAA", 0.5), _link("BBB", 0.5)]), _bet("b", links=[_link("AAA", 0.75), _link("FUND", 0.5)])))
    assert out["overlaps"] == [{"a": "a", "b": "b", "shared_value": 20000.0, "symbols": ["AAA"]}]
    assert "total_loss" not in out["totals"]
    assert out["totals"]["mapped_value"] == 55000.0  # AAA 30000 (the larger link), BBB 15000, FUND 10000


def test_coverage_names_unmapped_holdings_and_leaves_out_cash() -> None:
    out = _measure(_params())
    assert [u["symbol"] for u in out["unmapped"]] == ["FUND"]
    assert "FUND" in _flag(out, "UNMAPPED_HOLDINGS") and "SPAXX" not in _flag(out, "UNMAPPED_HOLDINGS")
    assert out["totals"]["cash_like_value"] == 10000.0 and out["totals"]["total_value"] == 100000.0
    assert out["totals"]["coverage"] == round(26000.0 / 90000.0, 4)


def test_small_uncovered_holdings_are_counted_not_listed() -> None:
    out = _measure(_params(book=_book(AAA=40000.0, BBB=30000.0, FUND=20000.0, SPAXX=9500.0, TINY=500.0)))
    assert "TINY" not in [u["symbol"] for u in out["unmapped"]]
    assert out["small_unmapped"] == {"count": 1, "value": 500.0}


def test_strongest_pairs_alone_give_no_history() -> None:
    out = _measure(_params(risk={"correlation": {"pairs": [{"a": "AAA", "b": "BBB", "correlation": 0.8}]}}))
    assert out["bets"][0]["history"] is None and _flag(out, "NO_RISK_DATA")


def test_stress_gives_the_whole_matrix_when_asked() -> None:
    risk = load_script("risk-analysis/scripts/risk.py")
    syms = [f"S{i:02d}" for i in range(16)]
    prices = {s: [{"date": f"2026-01-{d + 1:02d}", "close": 100.0 + (d * (i + 1)) % 7 + d} for d in range(28)] for i, s in enumerate(syms)}
    base = {"positions": [{"symbol": s, "value": 100.0} for s in syms], "prices": prices}
    assert "pairs" in risk.run_risk(base)["correlation"]
    full = risk.run_risk({**base, "full_correlation": True})["correlation"]
    assert sorted(full["symbols"]) == syms and len(full["matrix"]) == 16


def test_history_says_when_correlations_would_hide_a_bet() -> None:
    visible = _measure(_params())["bets"][0]["history"]
    assert visible == {"avg_correlation": 0.8, "portfolio_avg_correlation": 0.5, "pairs": 1, "reading": "moves_together"}
    out = _measure(_params(_bet(links=[_link("BBB"), _link("FUND")])))
    assert out["bets"][0]["history"]["reading"] == "not_visible_in_prices"
    assert "Rates stay low" in _flag(out, "NOT_IN_PRICES")
    assert _measure(_params(risk=None))["bets"][0]["history"] is None


def test_flags_for_one_sided_thin_and_old_evidence() -> None:
    out = _measure(_params(_bet("oneside", against=[]), _bet("single", links=[_link("AAA")]), _bet("old", against=[{"claim": "Old", "source": "FT", "date": "2024-01-01"}])))
    assert "Rates stay low" in _flag(out, "NO_OPPOSING_EVIDENCE")
    assert _flag(out, "SINGLE_HOLDING") and _flag(out, "STALE_EVIDENCE")


@pytest.mark.parametrize("mutate, needle", [
    (lambda b: b["links"][0].pop("source"), "source"),
    (lambda b: b["links"][0].pop("date"), "date"),
    (lambda b: b["links"][0].update(date="2027-06-01"), "after"),
    (lambda b: b["links"][0].update(symbol="NOPE"), "not held"),
    (lambda b: b["links"][0].update(share=1.5), "share"),
    (lambda b: b["links"][0].update(shock=-1.5), "shock"),
    (lambda b: b["for"][0].pop("source"), "source"),
    (lambda b: b.update(verdict="sure"), "verdict"),
    (lambda b: b.update(links=[]), "link"),
    (lambda b: b.update(belief=""), "belief"),
    (lambda b: b["links"].append(copy.deepcopy(b["links"][0])), "twice"),
])
def test_unsourced_or_impossible_inputs_are_rejected(mutate, needle) -> None:
    bet = _bet()
    mutate(bet)
    with pytest.raises(ValueError, match=needle):
        _measure(_params(bet))


def test_duplicate_bet_ids_and_unknown_income_are_rejected() -> None:
    with pytest.raises(ValueError, match="id"):
        _measure(_params(_bet("a"), _bet("a")))
    with pytest.raises(ValueError, match="income"):
        _measure(_params(_bet(income_links=[{"income": "nope", "share": 1, "shock": -1, "why": "x", "source": "person", "date": AS_OF}])))


def _page(**over) -> dict:
    return {"as_of": AS_OF, "headline": "One rate path carries 26% of the portfolio.", "summary": "AAA and BBB rest on the same rate path.", "exposure": _measure(_params()), "missing_roles": ["Red team"], "notes": [], **over}


def test_render_builds_the_page(tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0, res
    assert res["title"] == "Portfolio Deep Review" and res["bets"] == 1 and res["flags"] >= 2
    html = out.read_text()
    assert "window.DATA = " in html and "Rates stay low" in html
    for section in ("Shared bets", "Overlaps", "Not yet mapped", "What to watch", "Flags"):
        assert section in html


@pytest.mark.parametrize("over, needle", [
    ({"headline": "You should sell AAA"}, "should"),
    ({"headline": " ".join(["word"] * 26)}, "25 words"),
    ({"headline": ""}, "headline"),
    ({"summary": "We recommend trimming"}, "recommend"),
    ({"exposure": {}}, "exposure"),
])
def test_render_rejects(over, needle, tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page(**over)))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


@pytest.fixture
def saved(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    review = {"as_of": AS_OF, "headline": "h", "summary": "s", "exposure": _measure(_params())}
    src = tmp_path / "page.json"
    src.write_text(json.dumps(review))
    rc, res = run_json(load_script(STORE), ["save", "--in", str(src), "--source", "https://claude.ai/artifact/x"], capsys)
    assert rc == 0, res
    return tmp_path


def _write_book(tmp_path, **values) -> str:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_book(**values)))
    return str(path)


def test_save_keeps_the_review_outside_the_session(saved, capsys) -> None:
    rc, res = run_json(load_script(STORE), ["list"], capsys)
    assert rc == 0 and res["reviews"] == [{"as_of": AS_OF, "headline": "h", "source": "https://claude.ai/artifact/x", "bets": 1}]


def test_check_remeasures_the_bets_against_todays_holdings(saved, capsys) -> None:
    book = _write_book(saved, AAA=80000.0, BBB=30000.0, FUND=20000.0, SPAXX=10000.0)
    rc, out = run_json(load_script(STORE), ["check", "--book", book, "--as-of", "2026-12-01"], capsys)
    assert rc == 0, out
    bet = out["bets"][0]
    assert bet["then"]["exposed_value"] == 26000.0 and bet["now"]["exposed_value"] == 46000.0
    assert bet["now"]["loss_if_wrong"] == -19000.0 and bet["now"]["exposed_pct"] == round(46000 / 140000, 4)
    assert bet["moved"] == round(46000 / 26000 - 1, 4)
    assert out["review_age_days"] == 30 and out["watch_due"] == []
    assert "exposure of Rates stay low moved 76.9%" in out["rerun_reasons"][0] and out["rerun_due"] is True


def test_check_lists_watch_items_due_and_sold_holdings(saved, capsys) -> None:
    book = _write_book(saved, BBB=30000.0, FUND=20000.0, SPAXX=10000.0)
    rc, out = run_json(load_script(STORE), ["check", "--book", book, "--as-of", "2027-02-01"], capsys)
    assert rc == 0, out
    assert out["bets"][0]["gone"] == ["AAA"] and out["bets"][0]["now"]["exposed_value"] == 6000.0
    assert out["watch_due"] == [{"bet": "rates", "name": "Rates stay low", "what": "Fed projections", "breaks_if": "The median rate rises above 4%", "check_by": "2027-01-15"}]


def test_check_is_due_when_old(saved, capsys) -> None:
    book = _write_book(saved, AAA=40000.0, BBB=30000.0, FUND=20000.0, SPAXX=10000.0)
    rc, out = run_json(load_script(STORE), ["check", "--book", book, "--as-of", "2027-06-01"], capsys)
    assert rc == 0 and out["rerun_due"] is True
    assert len(out["rerun_reasons"]) == 1 and "180 days" in out["rerun_reasons"][0]


def test_check_is_not_due_when_nothing_changed(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", "--book", _write_book(saved), "--as-of", "2026-11-15"], capsys)
    assert rc == 0 and out["rerun_due"] is False and out["rerun_reasons"] == [] and out["new_uncovered"] == []


def test_check_is_due_when_new_holdings_are_uncovered(saved, capsys) -> None:
    # FUND was uncovered at the review, so only NEWCO, bought since, counts
    book = _write_book(saved, AAA=40000.0, BBB=30000.0, FUND=20000.0, SPAXX=10000.0, NEWCO=20000.0)
    rc, out = run_json(load_script(STORE), ["check", "--book", book, "--as-of", "2026-11-15"], capsys)
    assert rc == 0 and [u["symbol"] for u in out["new_uncovered"]] == ["NEWCO"]
    assert any("NEWCO" in r and "FUND" not in r for r in out["rerun_reasons"])


def test_a_net_gain_puts_nothing_at_stake() -> None:
    bet = _measure(_params(_bet(links=[_link("AAA", 0.5, 0.2), _link("BBB", 0.5, 0.2)])))["bets"][0]
    assert bet["loss_if_wrong"] == 7000.0 and bet["at_stake"] == 0.0


def test_check_with_nothing_saved_exits_2(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "empty"))
    rc, out = run_json(load_script(STORE), ["check", "--book", _write_book(tmp_path)], capsys)
    assert rc == 2 and "no saved review" in out["error"]
