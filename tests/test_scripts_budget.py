from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json

budget = load_script("valuation/scripts/budget.py")


@pytest.mark.parametrize("plan,total", [("valuation", 25), ("valuation-picker", 23), ("picker-3", 127), ("picker-4", 150), ("picker-5", 153)])
def test_init_totals(tmp_path, capsys, plan, total):
    rc, out = run_json(budget, [str(tmp_path), "init", "--plan", plan], capsys)
    assert rc == 0, out
    assert out["plan"] == plan and out["total"] == total == sum(out["caps"].values())
    assert out["remaining"] == total and out["flags"] == [] and sum(out["used"].values()) == 0
    assert json.loads((tmp_path / "budget.json").read_text())["plan"] == plan


def test_caps(tmp_path, capsys):
    _, out = run_json(budget, [str(tmp_path / "a"), "init", "--plan", "valuation"], capsys)
    assert out["caps"] == {"forensic": 1, "claims": 3, "industry": 6, "segments": 1, "threads": 8, "threads_round2": 4, "red_team": 2}
    _, out = run_json(budget, [str(tmp_path / "b"), "init", "--plan", "valuation-picker"], capsys)
    assert out["caps"]["industry"] == 4
    _, out = run_json(budget, [str(tmp_path / "c"), "init", "--plan", "picker-4"], capsys)
    assert out["caps"] == {"scanners": 18, "quick_reads": 40, "valuations": 92}


def test_add_flags_role_over_cap(tmp_path, capsys):
    run_json(budget, [str(tmp_path), "init", "--plan", "valuation"], capsys)
    rc, out = run_json(budget, [str(tmp_path), "add", "claims=2", "industry=7"], capsys)
    assert rc == 0
    assert out["remaining"] == 16 and out["used"]["claims"] == 2 and out["used"]["industry"] == 7
    assert [f["code"] for f in out["flags"]] == ["ROLE_OVER_CAP"] and "industry" in out["flags"][0]["message"]
    rc, status = run_json(budget, [str(tmp_path)], capsys)
    assert rc == 0 and status == out


def test_threads_allowed_stops_at_the_threads_cap(tmp_path, capsys):
    _, out = run_json(budget, [str(tmp_path), "init", "--plan", "valuation"], capsys)
    assert out["threads_allowed"] == 4 and out["round2_threads_allowed"] == 2
    _, out = run_json(budget, [str(tmp_path), "add", "threads=5"], capsys)
    assert out["remaining"] == 20 and out["threads_allowed"] == 1 and out["round2_threads_allowed"] == 2
    _, out = run_json(budget, [str(tmp_path), "add", "threads=3", "claims=3", "industry=6"], capsys)
    # 8 searches are left, but they belong to the second round and the red team
    assert out["remaining"] == 8 and out["threads_allowed"] == 0 and out["round2_threads_allowed"] == 2
    _, out = run_json(budget, [str(tmp_path), "add", "threads_round2=3"], capsys)
    assert out["remaining"] == 5 and out["threads_allowed"] == 0 and out["round2_threads_allowed"] == 0
    _, out = run_json(budget, [str(tmp_path), "add", "red_team=2", "forensic=1", "segments=1", "threads_round2=2"], capsys)
    assert out["remaining"] == -1 and out["threads_allowed"] == 0 and out["round2_threads_allowed"] == 0
    assert {f["code"] for f in out["flags"]} == {"ROLE_OVER_CAP", "OVER_BUDGET"}


def test_threads_allowed_falls_with_remaining(tmp_path, capsys):
    run_json(budget, [str(tmp_path), "init", "--plan", "valuation"], capsys)
    _, out = run_json(budget, [str(tmp_path), "add", "industry=12", "claims=8"], capsys)  # round 1 overspent: 5 left
    assert out["remaining"] == 5 and out["threads_allowed"] == 2 and out["round2_threads_allowed"] == 2
    _, out = run_json(budget, [str(tmp_path), "add", "industry=3"], capsys)
    assert out["remaining"] == 2 and out["threads_allowed"] == 1 and out["round2_threads_allowed"] == 1
    _, out = run_json(budget, [str(tmp_path), "add", "industry=5"], capsys)
    assert out["remaining"] == -3 and out["threads_allowed"] == 0 and out["round2_threads_allowed"] == 0


@pytest.mark.parametrize("plan", ["picker-3", "picker-4", "picker-5"])
def test_picker_plans_have_no_threads(tmp_path, capsys, plan):
    _, out = run_json(budget, [str(tmp_path), "init", "--plan", plan], capsys)
    assert out["threads_allowed"] == 0 and out["round2_threads_allowed"] == 0


def test_bad_input_exits_2(tmp_path, capsys):
    rc, out = run_json(budget, [str(tmp_path)], capsys)
    assert rc == 2 and "error" in out  # no budget.json yet
    rc, _ = run_json(budget, [str(tmp_path), "init", "--plan", "nope"], capsys)
    assert rc == 2
    run_json(budget, [str(tmp_path), "init", "--plan", "valuation"], capsys)
    rc, out = run_json(budget, [str(tmp_path), "add", "scanners=1"], capsys)
    assert rc == 2 and "scanners" in out["error"]
    for bad in ("claims", "claims=x", "claims=-1"):
        rc, _ = run_json(budget, [str(tmp_path), "add", bad], capsys)
        assert rc == 2, bad
    rc, _ = run_json(budget, [str(tmp_path), "add"], capsys)
    assert rc == 2
    _, status = run_json(budget, [str(tmp_path)], capsys)
    assert sum(status["used"].values()) == 0  # a rejected add writes nothing


def test_second_init_needs_force(tmp_path, capsys):
    run_json(budget, [str(tmp_path), "init", "--plan", "valuation"], capsys)
    run_json(budget, [str(tmp_path), "add", "claims=2"], capsys)
    rc, out = run_json(budget, [str(tmp_path), "init", "--plan", "valuation"], capsys)
    assert rc == 2 and "--force" in out["error"]
    rc, out = run_json(budget, [str(tmp_path), "init", "--plan", "valuation-picker", "--force"], capsys)
    assert rc == 0 and out["total"] == 23 and out["remaining"] == 23


def test_parallel_adds_lose_nothing(tmp_path, capsys):
    """Several coordinators share one picker budget: 24 `add valuations=1` at once recorded 19."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(budget.__file__)
    run_json(budget, [str(tmp_path), "init", "--plan", "picker-3"], capsys)
    procs = [subprocess.Popen([sys.executable, str(script), str(tmp_path), "add", "valuations=1", "quick_reads=2" if i % 2 else "scanners=1"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(24)]
    outs = [(p.communicate()[0], p.returncode) for p in procs]
    assert all(rc == 0 for _, rc in outs), outs
    rc, out = run_json(budget, [str(tmp_path)], capsys)
    assert out["used"] == {"scanners": 12, "quick_reads": 24, "valuations": 24} and out["used_total"] == 60
    assert max(json.loads(text)["used"]["valuations"] for text, _ in outs) == 24  # the last writer saw every earlier one
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith(".")) == ["budget.json"]  # no temp file left
    assert not list(tmp_path.glob(".*.tmp"))


def test_adds_from_threads_in_one_process_lose_nothing(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    budget.init(tmp_path, "picker-5")
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda _: budget.add(tmp_path, ["valuations=1"]), range(64)))
    assert budget.show(tmp_path)["used"]["valuations"] == 64
