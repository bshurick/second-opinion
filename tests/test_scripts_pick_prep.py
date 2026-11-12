from __future__ import annotations

import json
import time

import pytest

from scripts_util import load_script, run_json
from second_opinion.errors import ApiError

prep = load_script("stock-screener/scripts/pick_prep.py")

LATEST = {"DGS10": ("2026-11-06", 4.12), "DGS2": ("2026-11-06", 3.61), "FEDFUNDS": ("2026-10-01", 3.88),
          "BAMLC0A4CBBBEY": ("2026-11-06", 5.2), "MORTGAGE30US": ("2026-11-05", 6.3), "UNRATE": ("2026-09-01", 4.4),
          "DCOILWTICO": ("2026-11-03", 61.5), "DHHNGSP": ("2026-11-03", 3.4)}


def _monthly(last: float, year_ago: float) -> list[dict]:
    rows = [{"date": f"2025-{m:02d}-01", "value": year_ago} for m in range(8, 13)]
    rows += [{"date": f"2026-{m:02d}-01", "value": year_ago + 1} for m in range(1, 9)]
    rows.append({"date": "2026-09-01", "value": last})
    return rows


def _patch(monkeypatch, *, fail_series=(), fail_screens=(), calls=None, budget=None, running=None):
    def latest(series):
        if series in fail_series:
            raise ApiError("down", code="FRED_HTTP")
        d, v = LATEST[series]
        return {"series": series, "date": d, "value": v}

    def observations(series, n):
        if series in fail_series:
            raise ApiError("down", code="FRED_HTTP")
        return _monthly(330.0, 300.0)[-n:]

    def run_screen(name, args):
        if calls is not None:
            calls.append((name, list(args)))
        if running is not None:  # how many screens are in flight at once
            running["now"] += 1
            running["most"] = max(running["most"], running["now"])
            time.sleep(0.03)
            running["now"] -= 1
        if name in fail_screens:
            return 5, {"error": "EDGAR returned HTTP 503", "code": "EDGAR_HTTP"}
        return 0, {"preset": args[args.index("--preset") + 1], "flags": [{"code": "PRICE_LIMIT", "message": "x"}],
                   "survivors": [{"ticker": f"{name[:2].upper()}{i}", "name": "Co", "metrics": {}} for i in range(20)]}

    monkeypatch.setattr(prep.fred, "latest", latest)
    monkeypatch.setattr(prep.fred, "observations", observations)
    monkeypatch.setattr(prep, "run_screen", run_screen)
    if budget != "real":
        monkeypatch.setattr(prep, "run_budget", budget or (lambda run, args: (0, {"plan": args[-1], "total": 117, "remaining": 117})))
    monkeypatch.setattr(prep.edgar, "user_agent_is_default", lambda: False)


def test_value_profile_writes_macro_and_screens(monkeypatch, capsys, tmp_path):
    calls: list = []
    _patch(monkeypatch, calls=calls)
    run = tmp_path / "run"
    rc, out = run_json(prep, ["--run", str(run), "--profile", "value", "--held", "AAA,BBB"], capsys)
    assert rc == 0
    for sub in ("context", "screen", "industries", "cards"):
        assert (run / sub).is_dir()
    md = (run / "context" / "macro.md").read_text().splitlines()
    assert md[0].endswith(out["macro"]["as_of"]) and out["macro"]["as_of"][:2] == "20"
    line = next(x for x in md if "DGS10" in x)
    assert "2026-11-06" in line and "4.12" in line
    cpi = next(x for x in md if "CPIAUCSL" in x)
    assert "2026-09-01" in cpi and "10.0%" in cpi  # 330 against 300 a year earlier
    assert out["macro"]["missing"] == [] and len(out["macro"]["lines"]) == 11
    macro = json.loads((run / "context" / "macro.json").read_text())
    assert {s["series"] for s in macro["series"]} == set(prep.LATEST_SERIES) | set(prep.YOY_SERIES)
    assert sorted(p.name for p in (run / "screen").iterdir()) == ["quality.json", "smallcap.json", "value.json"]
    assert [c[0] for c in calls] == ["value", "quality", "smallcap"]  # in plan order, the first warming the frames cache
    small = dict(calls)["smallcap"]
    assert small[small.index("--preset") + 1] == "value"
    assert "min_revenue=1.5e8" in small and "min_market_cap=3e8" in small
    assert all("AAA,BBB" in args for _, args in calls)
    assert out["screens"]["quality"]["survivors"] == 20
    assert len(out["screens"]["quality"]["top"]) == 15 and out["screens"]["quality"]["top"][0] == "QU0"
    assert out["screens"]["quality"]["flags"] == ["PRICE_LIMIT"]
    assert json.loads((run / "screen" / "value.json").read_text())["survivors"][0]["ticker"] == "VA0"
    assert out["budget"]["plan"] == "picker-3" and out["flags"] == []
    assert out["run"] == str(run.resolve())


def test_growth_profile_and_finalists_plan(monkeypatch, capsys, tmp_path):
    calls: list = []
    _patch(monkeypatch, calls=calls)
    rc, out = run_json(prep, ["--run", str(tmp_path / "r"), "--profile", "growth", "--finalists", "5"], capsys)
    assert rc == 0
    assert [c[0] for c in calls] == ["garp", "smallcap"]
    assert calls[1][1][calls[1][1].index("--preset") + 1] == "garp"
    assert out["budget"]["plan"] == "picker-5"


def test_failed_series_is_flagged_and_absent(monkeypatch, capsys, tmp_path):
    _patch(monkeypatch, fail_series=("DGS2", "RSAFS"))
    run = tmp_path / "run"
    rc, out = run_json(prep, ["--run", str(run), "--profile", "value"], capsys)
    assert rc == 0
    text = (run / "context" / "macro.md").read_text()
    assert "DGS2" not in text and "RSAFS" not in text and "DGS10" in text
    assert out["macro"]["missing"] == ["DGS2", "RSAFS"]
    flag = next(f for f in out["flags"] if f["code"] == "MACRO_SERIES_UNAVAILABLE")
    assert "DGS2" in flag["message"] and "RSAFS" in flag["message"]


def test_one_failing_screen_keeps_the_others(monkeypatch, capsys, tmp_path):
    _patch(monkeypatch, fail_screens=("quality",))
    run = tmp_path / "run"
    rc, out = run_json(prep, ["--run", str(run), "--profile", "value"], capsys)
    assert rc == 0
    assert sorted(p.name for p in (run / "screen").iterdir()) == ["smallcap.json", "value.json"]
    assert [f["code"] for f in out["flags"]] == ["SCREEN_FAILED"]
    assert "quality" in out["flags"][0]["message"]
    assert out["screens"]["quality"]["survivors"] is None
    assert out["screens"]["value"]["survivors"] == 20


def test_budget_script_missing_is_flagged(monkeypatch, capsys, tmp_path):
    _patch(monkeypatch, budget="real")
    monkeypatch.setattr(prep, "BUDGET_SCRIPT", tmp_path / "nope.py")
    rc, out = run_json(prep, ["--run", str(tmp_path / "run"), "--profile", "value"], capsys)
    assert rc == 0
    assert out["budget"] is None
    assert [f["code"] for f in out["flags"]] == ["BUDGET_UNAVAILABLE"]


def test_existing_budget_is_kept(monkeypatch, capsys, tmp_path):
    seen: list = []

    def budget(run, args):
        seen.append(args)
        if "init" in args:
            return 2, {"error": "budget.json exists", "code": "INVALID_INPUT"}
        return 0, {"plan": "picker-3", "total": 117, "remaining": 100}

    _patch(monkeypatch, budget=budget)
    rc, out = run_json(prep, ["--run", str(tmp_path / "run"), "--profile", "value"], capsys)
    assert rc == 0 and out["budget"]["remaining"] == 100
    assert seen == [["init", "--plan", "picker-3"], []]
    assert [f["code"] for f in out["flags"]] == ["BUDGET_KEPT"]


def test_edgar_not_configured_is_exit_4(monkeypatch, capsys, tmp_path):
    _patch(monkeypatch)
    monkeypatch.setattr(prep.edgar, "user_agent_is_default", lambda: True)
    rc, out = run_json(prep, ["--run", str(tmp_path / "run"), "--profile", "value"], capsys)
    assert rc == 4 and "error" in out
    assert not (tmp_path / "run" / "screen").exists()


@pytest.mark.parametrize("argv", [["--profile", "value"], ["--run", "x", "--profile", "income"],
                                  ["--run", "x", "--profile", "value", "--finalists", "6"],
                                  ["--run", "x", "--profile", "value", "--held", "AAA,$$"]])
def test_bad_arguments(monkeypatch, capsys, tmp_path, argv):
    _patch(monkeypatch)
    monkeypatch.chdir(tmp_path)
    rc, out = run_json(prep, argv, capsys)
    assert rc == 2 and "error" in out


def test_yoy_skips_a_month_with_no_year_earlier_reading(monkeypatch):
    rows = [r for r in _monthly(330.0, 300.0) if r["date"] != "2025-10-01"] + [{"date": "2026-10-01", "value": 333.0}]
    monkeypatch.setattr(prep.fred, "observations", lambda series, n: rows[-n:])
    got = prep._yoy("CPIAUCSL")
    assert got["date"] == "2026-09-01" and got["year_ago_date"] == "2025-09-01" and got["value"] == 0.1
    assert got["skipped"] == ["2026-10-01"] and "2026-10-01 has no reading a year earlier" in got["line"]


def test_rate_limited_screen_is_flagged(monkeypatch, capsys, tmp_path):
    _patch(monkeypatch)
    monkeypatch.setattr(prep, "run_screen", lambda name, args: (0, {"survivors": [], "flags": [{"code": "PRICING_INCOMPLETE", "message": "x"}] if name == "quality" else []}))
    rc, out = run_json(prep, ["--run", str(tmp_path / "run"), "--profile", "value"], capsys)
    assert rc == 0 and [f["code"] for f in out["flags"]] == ["SCREEN_PRICING_INCOMPLETE"]
    assert "quality" in out["flags"][0]["message"] and (tmp_path / "run" / "screen" / "quality.json").is_file()


def test_screens_run_one_after_another(monkeypatch, capsys, tmp_path):
    """Two screens at once drew Yahoo rate limits (PRICING_INCOMPLETE), so no two ever overlap."""
    calls: list = []
    running = {"now": 0, "most": 0}
    _patch(monkeypatch, calls=calls, running=running)
    rc, out = run_json(prep, ["--run", str(tmp_path / "run"), "--profile", "value"], capsys)
    assert rc == 0 and [c[0] for c in calls] == ["value", "quality", "smallcap"]
    assert running["most"] == 1
    assert not hasattr(prep, "PARALLEL_SCREENS")
