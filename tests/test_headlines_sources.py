from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest
from second_opinion.headlines import sources as S


def _ctx(tmp_path: Path, **over) -> dict:
    base = {"today": date(2026, 9, 14), "now": "2026-09-14T13:05:00+00:00", "snapshot": {"positions": [], "profiles": {}, "events": None},
            "previous": {"as_of": None, "keys": [], "risk": {}}, "symbols": [], "partial": False,
            "data_dir": tmp_path, "plugin_root": tmp_path, "python": sys.executable}
    return {**base, **over}


def _stub_module(monkeypatch, name: str, fn):
    mod = types.ModuleType(f"second_opinion.headlines.{name}")
    mod.extract = fn
    monkeypatch.setitem(sys.modules, f"second_opinion.headlines.{name}", mod)


def _source(tmp_path, monkeypatch, *, name="stub", ready=None, commands=None, broker=False, extract=None):
    (tmp_path / "skills" / "stub-skill" / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "stub-skill" / "scripts" / "x.py").write_text("")
    _stub_module(monkeypatch, name, extract or (lambda results, ctx: [S.H.make("stub-skill", "HIT", "alert", results["main"]["title"])]))
    return S.Source(name=name, skill="stub-skill", module=name, ready=ready or (lambda ctx: None), hint="set it up",
                    broker=broker, commands=commands or (lambda ctx: [("main", "scripts/x.py", ["--go"])]))


def test_registry_lists_twelve_sources_in_brief_order() -> None:
    assert [s.skill for s in S.SOURCES] == [
        "watchlist", "market-analysis", "portfolio-snapshot", "fundamental-research", "rebalancing", "tax-aware",
        "dividend-income", "risk-analysis", "trade-journal", "debt-tracker", "spending", "statement-import"]
    assert S.SOURCE_ORDER == [s.skill for s in S.SOURCES]


def test_run_all_extracts_headlines_and_reports_coverage(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch)
    seen: list[list[str]] = []

    def runner(argv, timeout):
        seen.append(argv)
        return 0, json.dumps({"title": "hello"}), ""

    hs, cov = S.run_all(_ctx(tmp_path), runner=runner, sources=[src])
    assert [h["title"] for h in hs] == ["hello"] and hs[0]["status"] == "new"
    assert seen == [[sys.executable, str(tmp_path / "skills" / "stub-skill" / "scripts" / "x.py"), "--go"]]
    row = cov[0]
    assert row["skill"] == "stub-skill" and row["status"] == "ok" and row["headlines"] == 1 and row["seconds"] >= 0
    assert row["script"] == "scripts/x.py"


def test_missing_skill_directory_is_skipped_without_running(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch)
    src = S.Source(**{**src.__dict__, "skill": "absent-skill"})
    calls = []
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: calls.append(a) or (0, "{}", ""), sources=[src])
    assert hs == [] and calls == []
    assert cov[0]["status"] == "skipped" and cov[0]["reason"] == "skill not installed" and cov[0]["hint"] == "install it with the setup skill"


def test_not_ready_source_is_skipped_with_its_hint(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch, ready=lambda ctx: "no targets.json")
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert hs == [] and cov[0] == {"skill": "stub-skill", "script": "scripts/x.py", "status": "skipped", "reason": "no targets.json",
                                    "hint": "set it up", "seconds": 0.0, "headlines": 0}


def test_nonzero_exit_uses_the_scripts_error_message(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch)
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (2, json.dumps({"error": "the ledger is empty", "code": "INVALID_INPUT"}), ""), sources=[src])
    assert hs == [] and cov[0]["status"] == "failed" and cov[0]["reason"] == "the ledger is empty"


def test_unparsable_stdout_and_stderr_become_failed(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch)
    _, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (1, "not json", "Traceback\nValueError: boom"), sources=[src])
    assert cov[0]["status"] == "failed" and cov[0]["reason"] == "ValueError: boom"


def test_timeout_becomes_failed(tmp_path, monkeypatch) -> None:
    import subprocess
    src = _source(tmp_path, monkeypatch)

    def slow(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    _, cov = S.run_all(_ctx(tmp_path), runner=slow, timeout=0.5, sources=[src])
    assert cov[0]["status"] == "failed" and cov[0]["reason"] == "timed out after 1s"


def test_extractor_exception_becomes_failed(tmp_path, monkeypatch) -> None:
    def boom(results, ctx):
        raise KeyError("positions")

    src = _source(tmp_path, monkeypatch, extract=boom)
    _, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert cov[0]["status"] == "failed" and "KeyError" in cov[0]["reason"]


def test_partial_is_appended_only_for_broker_sources(tmp_path, monkeypatch) -> None:
    seen = []
    src = _source(tmp_path, monkeypatch, broker=True)
    S.run_all(_ctx(tmp_path, partial=True), runner=lambda a, t: seen.append(a) or (0, json.dumps({"title": "x"}), ""), sources=[src])
    assert seen[0][-2:] == ["--go", "--partial"]
    seen.clear()
    S.run_all(_ctx(tmp_path, partial=False), runner=lambda a, t: seen.append(a) or (0, json.dumps({"title": "x"}), ""), sources=[src])
    assert seen[0][-1] == "--go"


def test_multi_command_source_keeps_successful_results_but_reports_failed(tmp_path, monkeypatch) -> None:
    def extract(results, ctx):
        return [S.H.make("stub-skill", "GOT", "notice", ",".join(sorted(results)))]

    src = _source(tmp_path, monkeypatch, extract=extract,
                  commands=lambda ctx: [("a", "scripts/x.py", ["a"]), ("b", "scripts/x.py", ["b"])])

    def runner(argv, timeout):
        return (0, "{}", "") if argv[-1] == "a" else (5, json.dumps({"error": "yahoo down"}), "")

    hs, cov = S.run_all(_ctx(tmp_path), runner=runner, sources=[src])
    assert hs[0]["title"] == "a" and cov[0]["status"] == "failed" and cov[0]["reason"] == "b: yahoo down" and cov[0]["headlines"] == 1


def test_no_command_source_extracts_from_ctx(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch, commands=lambda ctx: [],
                  extract=lambda results, ctx: [S.H.make("stub-skill", "EV", "alert", str(ctx["today"]))] if results == {} else [])
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert hs[0]["title"] == "2026-09-14" and cov[0]["status"] == "ok" and cov[0]["script"] == ""


def test_per_source_cap_applies(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch, extract=lambda r, c: [S.H.make("stub-skill", f"C{i}", "notice", str(i)) for i in range(5)])
    hs, _ = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert len(hs) == 3


def test_headlines_are_marked_still_from_previous_keys(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch)
    prev = {"as_of": "2026-09-13", "keys": ["stub-skill:HIT:-:"], "risk": {}}
    hs, _ = S.run_all(_ctx(tmp_path, previous=prev), runner=lambda a, t: (0, json.dumps({"title": "t"}), ""), sources=[src])
    assert hs[0]["status"] == "still"


def test_subprocess_runner_runs_a_real_command(tmp_path) -> None:
    rc, out, err = S.subprocess_runner([sys.executable, "-c", "import json; print(json.dumps({'ok': 1}))"], timeout=30)
    assert rc == 0 and json.loads(out) == {"ok": 1} and err == ""


def test_ready_helpers(tmp_path) -> None:
    ctx = {"data_dir": tmp_path}
    assert S.needs_file("targets.json", "no targets.json")(ctx) == "no targets.json"
    (tmp_path / "targets.json").write_text("{}")
    assert S.needs_file("targets.json", "no targets.json")(ctx) is None
    assert S.needs_entries("ledger.json", "transactions", "the ledger is empty")(ctx) == "the ledger is empty"
    (tmp_path / "ledger.json").write_text(json.dumps({"transactions": [{"a": 1}]}))
    assert S.needs_entries("ledger.json", "transactions", "the ledger is empty")(ctx) is None
    (tmp_path / "ledger.json").write_text("{bad")
    assert S.needs_entries("ledger.json", "transactions", "the ledger is empty")(ctx) == "ledger.json is not valid JSON"


def test_commands_raising_becomes_failed_and_never_raises(tmp_path, monkeypatch) -> None:
    def raise_commands(ctx):
        raise RuntimeError("boom-commands")

    src = _source(tmp_path, monkeypatch, commands=raise_commands)
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert hs == [] and cov[0]["status"] == "failed" and "boom-commands" in cov[0]["reason"]


def test_ready_raising_becomes_failed_and_never_raises(tmp_path, monkeypatch) -> None:
    def raise_ready(ctx):
        raise RuntimeError("boom-ready")

    src = _source(tmp_path, monkeypatch, ready=raise_ready)
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert hs == [] and cov[0]["status"] == "failed" and "boom-ready" in cov[0]["reason"]


def test_malformed_headline_is_dropped_but_valid_one_survives(tmp_path, monkeypatch) -> None:
    def extract(results, ctx):
        good = S.H.make("stub-skill", "OK", "notice", "fine")
        bad = {"severity": "alert", "title": "no key"}  # missing "key"
        return [good, bad]

    src = _source(tmp_path, monkeypatch, extract=extract)
    hs, cov = S.run_all(_ctx(tmp_path), runner=lambda a, t: (0, "{}", ""), sources=[src])
    assert [h["title"] for h in hs] == ["fine"]
    assert cov[0]["status"] == "failed" and "malformed" in cov[0]["reason"]


def test_needs_env(monkeypatch) -> None:
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    assert S.needs_env("EDGAR_USER_AGENT", "EDGAR_USER_AGENT is not set")({}) == "EDGAR_USER_AGENT is not set"
    monkeypatch.setenv("EDGAR_USER_AGENT", "app me@x")
    assert S.needs_env("EDGAR_USER_AGENT", "EDGAR_USER_AGENT is not set")({}) is None


def test_source_deadline_skips_remaining_commands_without_rerunning(tmp_path, monkeypatch) -> None:
    import subprocess

    clock = iter([0.0, 0.1, 0.6, 0.6])
    monkeypatch.setattr(S.time, "monotonic", lambda: next(clock))

    calls: list[tuple[list[str], float]] = []

    def runner(argv, timeout):
        calls.append((argv, timeout))
        raise subprocess.TimeoutExpired(argv, timeout)

    src = _source(tmp_path, monkeypatch, commands=lambda ctx: [("a", "scripts/x.py", ["a"]), ("b", "scripts/x.py", ["b"])])
    hs, cov = S.run_all(_ctx(tmp_path), runner=runner, timeout=0.5, sources=[src])
    assert hs == []
    assert len(calls) == 1 and calls[0][0][-1] == "a"
    assert cov[0]["status"] == "failed"
    assert "a: timed out after 1s" in cov[0]["reason"]
    assert "b: skipped: source deadline of 0.5s reached" in cov[0]["reason"]


def test_edgar_caps_symbol_fanout_and_reports_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDGAR_USER_AGENT", "app me@x")
    (tmp_path / "skills" / "fundamental-research").mkdir(parents=True)
    symbols = [f"SYM{i}" for i in range(13)]
    seen: list[list[str]] = []

    def runner(argv, timeout):
        seen.append(argv)
        return 0, "{}", ""

    src = next(s for s in S.SOURCES if s.name == "edgar")
    hs, cov = S.run_all(_ctx(tmp_path, symbols=symbols), runner=runner, sources=[src])
    assert len(seen) == S.EDGAR_MAX_SYMBOLS == 12
    row = cov[0]
    assert row["skill"] == "fundamental-research" and row["status"] == "ok"
    assert row["reason"] == "only the 12 largest single stocks were checked"


@pytest.mark.parametrize("source", S.SOURCES, ids=[s.name for s in S.SOURCES])
def test_every_source_script_exists_and_module_skill_matches(source) -> None:
    ctx = {"symbols": ["AAPL", "MSFT"]}
    for _label, script, _args in source.commands(ctx):
        path = Path(S.__file__).resolve().parents[3] / "skills" / source.skill / script
        assert path.is_file(), f"{source.name}: missing {path}"
    mod = importlib.import_module(f"second_opinion.headlines.{source.module}")
    assert mod.SKILL == source.skill


def test_run_all_stores_raw_results_per_source_under_ctx_results(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path, monkeypatch)
    ctx = _ctx(tmp_path)
    S.run_all(ctx, runner=lambda a, t: (0, json.dumps({"title": "hello"}), ""), sources=[src])
    assert ctx["results"] == {src.name: {"main": {"title": "hello"}}}


def _ex_dividend_headline(sym: str = "KO") -> dict:
    return S.H.make("portfolio-snapshot", "EX_DIVIDEND", "alert", f"{sym} goes ex-dividend on 2026-09-18",
                    symbol=sym, discriminator="2026-09-18", as_of="2026-09-14", answer="")


def _earnings_headline(sym: str = "KO") -> dict:
    return S.H.make("portfolio-snapshot", "EARNINGS", "alert", f"{sym} reports earnings on 2026-09-18",
                    symbol=sym, discriminator="2026-09-18", as_of="2026-09-14", answer="")


def _filing_headline(sym: str = "KO", form: str = "10-Q") -> dict:
    return S.H.make("fundamental-research", "FILING", "alert", f"{sym} filed a {form} on 2026-09-01",
                    symbol=sym, discriminator=f"{form}:2026-09-01", as_of="2026-09-01",
                    answer="Filed 2026-09-01; risk-factor comparison pending")


def test_enrich_fills_ex_dividend_from_dividends_results_without_calling_runner(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    ctx["results"] = {"dividends": {"main": {"positions": [
        {"symbol": "KO", "units": 100, "next_ex_amount_est": 12.5, "last_dividend": 0.125}]}}}
    calls = []
    hs = S.enrich([_ex_dividend_headline()], ctx, runner=lambda a, t: calls.append(a) or (0, "{}", ""))
    assert calls == []
    assert hs[0]["answer"] == "About $12.50 for your 100 shares (last $0.1250 per share)"


def test_enrich_leaves_ex_dividend_empty_when_row_missing(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    ctx["results"] = {"dividends": {"main": {"positions": []}}}
    hs = S.enrich([_ex_dividend_headline()], ctx, runner=lambda a, t: (0, "{}", ""))
    assert hs[0]["answer"] == ""


def test_enrich_leaves_ex_dividend_empty_when_amount_missing(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    ctx["results"] = {"dividends": {"main": {"positions": [{"symbol": "KO", "units": 100, "last_dividend": 0.125}]}}}
    hs = S.enrich([_ex_dividend_headline()], ctx, runner=lambda a, t: (0, "{}", ""))
    assert hs[0]["answer"] == ""


def test_enrich_earnings_calls_chain_and_fills_expected_move(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    seen = []

    def runner(argv, timeout):
        seen.append((argv, timeout))
        return 0, json.dumps({"expected_move_1sd": 4.32, "expected_move_pct": 0.0612, "expiry": "2026-09-19",
                              "atm_iv": 0.412, "spot": 70.0}), ""

    hs = S.enrich([_earnings_headline()], ctx, runner=runner, timeout=42.0)
    assert hs[0]["answer"] == "Options price a ±$4.32 (±6.1%) move by 2026-09-19 (ATM IV 41%)"
    [(argv, timeout)] = seen
    assert argv == [ctx["python"], str(tmp_path / "skills" / "options" / "scripts" / "chain.py"), "KO", "--no-history"]
    assert timeout == pytest.approx(42.0, abs=1.0)


def test_enrich_earnings_exit_2_gets_no_options_wording(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    hs = S.enrich([_earnings_headline()], ctx, runner=lambda a, t: (2, json.dumps({"error": "No listed options for KO", "code": "INVALID_INPUT"}), ""))
    assert hs[0]["answer"] == "No listed options to price the move"


def test_enrich_earnings_exit_2_other_message_leaves_answer_untouched(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    hs = S.enrich([_earnings_headline()], ctx, runner=lambda a, t: (2, json.dumps({"error": "unknown ticker KO", "code": "INVALID_INPUT"}), ""))
    assert hs[0]["answer"] == ""


def test_enrich_earnings_other_failure_leaves_answer_empty(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    hs = S.enrich([_earnings_headline()], ctx, runner=lambda a, t: (5, "", "boom"))
    assert hs[0]["answer"] == ""


def test_enrich_earnings_skips_call_when_options_skill_missing(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    calls = []
    hs = S.enrich([_earnings_headline()], ctx, runner=lambda a, t: calls.append(a) or (0, "{}", ""))
    assert calls == [] and hs[0]["answer"] == ""


def test_enrich_filing_10q_calls_filing_and_fills_diff_summary(tmp_path) -> None:
    (tmp_path / "skills" / "fundamental-research" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    seen = []

    def runner(argv, timeout):
        seen.append(argv)
        return 0, json.dumps({"added_count": 3, "removed_count": 1, "similarity": 0.87,
                              "previous": {"filing_date": "2026-06-01", "url": "https://x"}}), ""

    hs = S.enrich([_filing_headline(form="10-Q")], ctx, runner=runner)
    assert hs[0]["answer"] == "Risk factors vs the prior 10-Q: 3 sentences added, 1 removed, similarity 87%"
    [argv] = seen
    assert argv == [ctx["python"], str(tmp_path / "skills" / "fundamental-research" / "scripts" / "filing.py"),
                    "KO", "--form", "10-Q", "--item", "1A", "--diff"]


def test_enrich_filing_10k_uses_10k_in_args_and_answer(tmp_path) -> None:
    (tmp_path / "skills" / "fundamental-research" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    seen = []

    def runner(argv, timeout):
        seen.append(argv)
        return 0, json.dumps({"added_count": 0, "removed_count": 2, "similarity": 0.5}), ""

    hs = S.enrich([_filing_headline(form="10-K")], ctx, runner=runner)
    assert "--form" in seen[0] and seen[0][seen[0].index("--form") + 1] == "10-K"
    assert hs[0]["answer"] == "Risk factors vs the prior 10-K: 0 sentences added, 2 removed, similarity 50%"


def test_enrich_filing_exit_2_gets_first_filing_wording(tmp_path) -> None:
    (tmp_path / "skills" / "fundamental-research" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    hs = S.enrich([_filing_headline(form="10-Q")], ctx, runner=lambda a, t: (2, json.dumps({"error": "no prior filing", "code": "INVALID_INPUT"}), ""))
    assert hs[0]["answer"] == "No prior 10-Q risk factors to compare"


def test_enrich_filing_other_failure_keeps_task3_fallback_answer(tmp_path) -> None:
    (tmp_path / "skills" / "fundamental-research" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    hs = S.enrich([_filing_headline(form="10-Q")], ctx, runner=lambda a, t: (5, "", "EDGAR down"))
    assert hs[0]["answer"] == "Filed 2026-09-01; risk-factor comparison pending"


def test_enrich_filing_skips_8k_and_skips_when_skill_missing(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        return 0, "{}", ""

    hs = S.enrich([_filing_headline(form="8-K")], ctx, runner=runner)
    assert calls == [] and hs[0]["answer"] == "Filed 2026-09-01; risk-factor comparison pending"
    (tmp_path / "skills" / "fundamental-research" / "scripts").mkdir(parents=True)
    ctx2 = _ctx(tmp_path)
    del ctx2["plugin_root"]
    ctx2["plugin_root"] = tmp_path.parent / "no-such-root"
    hs2 = S.enrich([_filing_headline(form="10-Q")], ctx2, runner=runner)
    assert calls == [] and hs2[0]["answer"] == "Filed 2026-09-01; risk-factor comparison pending"


def test_enrich_respects_max_calls_across_headline_types(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    (tmp_path / "skills" / "fundamental-research" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    seen = []

    def runner(argv, timeout):
        seen.append(argv)
        return 0, json.dumps({"expected_move_1sd": 1.0, "expected_move_pct": 0.01, "expiry": "2026-09-19",
                              "atm_iv": 0.3, "added_count": 1, "removed_count": 0, "similarity": 0.9}), ""

    headlines = [_earnings_headline("A"), _earnings_headline("B"), _filing_headline("C", "10-Q"),
                 _filing_headline("D", "10-K"), _earnings_headline("E")]
    hs = S.enrich(headlines, ctx, runner=runner, max_calls=2)
    assert len(seen) == 2
    assert hs[0]["answer"] != "" and hs[1]["answer"] != ""
    # budget exhausted by the two earnings calls: the filing headlines keep their Task-3 fallback,
    # and the third earnings headline keeps its empty answer.
    assert hs[2]["answer"] == "Filed 2026-09-01; risk-factor comparison pending"
    assert hs[3]["answer"] == "Filed 2026-09-01; risk-factor comparison pending"
    assert hs[4]["answer"] == ""


def test_enrich_runner_exception_leaves_answer_untouched(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)

    def boom(argv, timeout):
        raise RuntimeError("subprocess exploded")

    hs = S.enrich([_earnings_headline()], ctx, runner=boom)
    assert hs[0]["answer"] == ""


def test_enrich_respects_a_single_phase_deadline_across_calls(tmp_path, monkeypatch) -> None:
    import subprocess

    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    clock = iter([0.0, 0.0, 0.6])
    monkeypatch.setattr(S.time, "monotonic", lambda: next(clock))
    calls: list[list[str]] = []

    def runner(argv, timeout):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, timeout)

    headlines = [_earnings_headline("A"), _earnings_headline("B")]
    hs = S.enrich(headlines, ctx, runner=runner, timeout=0.5)
    assert len(calls) == 1 and calls[0][-2] == "A"
    assert hs[0]["answer"] == "" and hs[1]["answer"] == ""


def test_enrich_earnings_handles_none_stdout_without_raising(tmp_path) -> None:
    (tmp_path / "skills" / "options" / "scripts").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    hs = S.enrich([_earnings_headline()], ctx, runner=lambda a, t: (0, None, ""))
    assert hs[0]["answer"] == ""


def test_enrich_returns_same_list_object_it_was_given(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    headlines = [_earnings_headline()]
    assert S.enrich(headlines, ctx, runner=lambda a, t: (0, "{}", "")) is headlines
