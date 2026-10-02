from __future__ import annotations

import json
from datetime import date

import pytest
from second_opinion.errors import ConfigError
from second_opinion.headlines import sources as S
from scripts_util import load_script, run_json

SNAP = {"as_of": "2026-09-14T13:05:00+00:00", "sources": {"holdings": "snaptrade", "quotes": "yahoo"}, "totals": {"total_value": 100.0},
        "accounts": [], "positions": [{"symbol": "KO"}, {"symbol": "VTI"}], "top_holdings": [], "concentration": {}, "sector_weights": {},
        "movers": {"up": [], "down": []}, "events": [{"symbol": "KO", "type": "earnings", "date": "2026-09-18"}], "flags": [],
        "profiles": {"KO": {"quote_type": "EQUITY"}, "VTI": {"quote_type": "ETF"}}}


@pytest.fixture
def brief(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    mod = load_script("portfolio-snapshot/scripts/brief.py")
    calls: list[list[str]] = []

    def build(args):
        calls.append(list(args))
        return json.loads(json.dumps(SNAP))

    monkeypatch.setattr(mod.snapshot, "build", build)
    mod.calls = calls
    mod.tmp_path = tmp_path
    return mod


def test_snapshot_build_is_a_module_function() -> None:
    snap = load_script("portfolio-snapshot/scripts/snapshot.py")
    assert callable(snap.build)


def test_single_stock_symbols_sorts_by_market_value_descending() -> None:
    mod = load_script("portfolio-snapshot/scripts/brief.py")
    snap = {"positions": [{"symbol": "AAA", "market_value": 100.0}, {"symbol": "BBB", "market_value": 500.0},
                          {"symbol": "CCC", "market_value": 500.0}, {"symbol": "DDD"}, {"symbol": "ETF1"}],
            "profiles": {"AAA": {"quote_type": "EQUITY"}, "BBB": {"quote_type": "EQUITY"}, "CCC": {"quote_type": "EQUITY"},
                        "DDD": {"quote_type": "EQUITY"}, "ETF1": {"quote_type": "ETF"}}}
    assert mod._single_stock_symbols(snap) == ["BBB", "CCC", "AAA", "DDD"]


def test_brief_runs_snapshot_with_events_then_sources_and_writes_last(brief, monkeypatch, capsys) -> None:
    seen = {}

    def run_all(ctx, *, runner=None, timeout=90.0, workers=6, sources=None):
        seen.update(ctx=ctx, timeout=timeout, workers=workers)
        return ([{"key": "a:B:-:", "code": "B", "skill": "a", "severity": "alert", "symbol": None, "title": "t", "detail": "", "as_of": "2026-09-14", "status": "new", "ask": "q"}],
                [{"skill": "a", "script": "s.py", "status": "ok", "reason": "", "hint": "", "seconds": 1.2, "headlines": 1}])

    monkeypatch.setattr(S, "run_all", run_all)
    rc, out = run_json(brief, ["--account", "x", "--timeout", "12", "--workers", "2"], capsys)
    assert rc == 0, out
    assert brief.calls == [["--account", "x", "--events"]]
    assert seen["timeout"] == 12.0 and seen["workers"] == 2
    ctx = seen["ctx"]
    assert ctx["symbols"] == ["KO"] and ctx["partial"] is False and isinstance(ctx["today"], date) and ctx["snapshot"]["totals"] == {"total_value": 100.0}
    assert out["headlines"][0]["key"] == "a:B:-:" and out["coverage"][0]["skill"] == "a" and out["totals"] == {"total_value": 100.0}
    assert out["brief_as_of"] and out["brief_seconds"] >= 0
    last = json.loads((brief.tmp_path / "brief-last.json").read_text())
    assert last["keys"] == ["a:B:-:"]


def test_brief_calls_enrich_after_run_all_before_save_last(brief, monkeypatch, capsys) -> None:
    found = [{"key": "a:B:-:", "code": "B", "skill": "a", "severity": "alert", "symbol": None, "title": "t",
              "detail": "", "as_of": "2026-09-14", "status": "new", "ask": "q", "answer": ""}]
    monkeypatch.setattr(S, "run_all", lambda ctx, **kw: (list(found), [{"skill": "a", "script": "s.py", "status": "ok",
                                                                        "reason": "", "hint": "", "seconds": 0.1, "headlines": 1}]))
    seen = {}

    def enrich(headlines, ctx, *, runner=None, timeout=90.0, max_calls=6):
        seen.update(headlines=headlines, ctx=ctx, timeout=timeout)
        headlines[0]["answer"] = "enriched"
        return headlines

    monkeypatch.setattr(S, "enrich", enrich)
    rc, out = run_json(brief, ["--timeout", "17"], capsys)
    assert rc == 0, out
    assert seen["headlines"] == found and seen["timeout"] == 17.0
    assert out["headlines"][0]["answer"] == "enriched"
    last = json.loads((brief.tmp_path / "brief-last.json").read_text())
    assert last["keys"] == ["a:B:-:"]


def test_brief_passes_partial_and_previous_risk(brief, monkeypatch, capsys) -> None:
    (brief.tmp_path / "brief-last.json").write_text(json.dumps({"as_of": "2026-09-13", "keys": ["k"], "risk": {"max_drawdown": -0.2}}))
    seen = {}
    monkeypatch.setattr(S, "run_all", lambda ctx, **kw: seen.update(ctx=ctx) or ([], []))
    rc, _ = run_json(brief, ["--partial"], capsys)
    assert rc == 0 and brief.calls == [["--partial", "--events"]]
    assert seen["ctx"]["partial"] is True and seen["ctx"]["previous"]["risk"] == {"max_drawdown": -0.2}


def test_brief_records_risk_for_the_next_run(brief, monkeypatch, capsys) -> None:
    def run_all(ctx, **kw):
        ctx["risk_results"]["main"] = {"portfolio": {"max_drawdown": -0.31}}
        return [], []

    monkeypatch.setattr(S, "run_all", run_all)
    rc, _ = run_json(brief, [], capsys)
    assert rc == 0 and json.loads((brief.tmp_path / "brief-last.json").read_text())["risk"] == {"max_drawdown": -0.31}


def test_brief_keeps_a_failed_sources_memory_between_runs(brief, monkeypatch, capsys) -> None:
    (brief.tmp_path / "brief-last.json").write_text(json.dumps({
        "as_of": "2026-09-13", "keys": ["risk-analysis:HIGH_BETA:-:", "debt-tracker:PAST_DUE:-:amex:2026-09-12"],
        "risk": {"max_drawdown": -0.2},
    }))

    def run_all(ctx, **kw):
        return (
            [{"key": "debt-tracker:PAST_DUE:-:amex:2026-09-14", "code": "PAST_DUE", "skill": "debt-tracker",
              "severity": "alert", "symbol": None, "title": "t", "detail": "", "as_of": "2026-09-14", "status": "new", "ask": "q"}],
            [{"skill": "risk-analysis", "script": "stress.py", "status": "failed", "reason": "timed out", "hint": "", "seconds": 90.0, "headlines": 0},
             {"skill": "debt-tracker", "script": "debts.py", "status": "ok", "reason": "", "hint": "", "seconds": 0.5, "headlines": 1}],
        )

    monkeypatch.setattr(S, "run_all", run_all)
    rc, _ = run_json(brief, [], capsys)
    assert rc == 0
    last = json.loads((brief.tmp_path / "brief-last.json").read_text())
    assert last["risk"] == {"max_drawdown": -0.2}
    assert "risk-analysis:HIGH_BETA:-:" in last["keys"]
    assert "debt-tracker:PAST_DUE:-:amex:2026-09-12" not in last["keys"]
    assert "debt-tracker:PAST_DUE:-:amex:2026-09-14" in last["keys"]


def test_no_headlines_skips_sources_and_writes_nothing(brief, monkeypatch, capsys) -> None:
    monkeypatch.setattr(S, "run_all", lambda ctx, **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    rc, out = run_json(brief, ["--no-headlines"], capsys)
    assert rc == 0 and "headlines" not in out and brief.calls == [[]]
    assert not (brief.tmp_path / "brief-last.json").exists()


def test_snapshot_errors_propagate_unchanged(brief, monkeypatch, capsys) -> None:
    def build(args):
        raise ConfigError("E*Trade login needed", code="ETRADE_REAUTH", url="https://x", partial="--partial")

    monkeypatch.setattr(brief.snapshot, "build", build)
    rc, out = run_json(brief, [], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH" and out["url"] == "https://x"


def test_bad_flag_is_invalid_input(brief, capsys) -> None:
    rc, out = run_json(brief, ["--timeout", "abc"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_save_last_failure_becomes_a_flag_not_a_crash(brief, monkeypatch, capsys) -> None:
    monkeypatch.setattr(S, "run_all", lambda ctx, **kw: ([], []))

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(brief.headlines, "save_last", boom)
    rc, out = run_json(brief, [], capsys)
    assert rc == 0
    assert any(f.get("code") == "BRIEF_MEMORY_UNAVAILABLE" for f in out["flags"])
    assert "disk full" in next(f["message"] for f in out["flags"] if f["code"] == "BRIEF_MEMORY_UNAVAILABLE")
