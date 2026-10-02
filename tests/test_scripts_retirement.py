from __future__ import annotations

import json

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client
from second_opinion.brokers import router
from page_dom import assert_page_help, render_and_audit, requires_chrome

ARGS = ["--age", "40", "--retirement-age", "65", "--end-age", "95", "--contribution", "20000", "--spending", "80000", "--seed", "7", "--simulations", "100"]


@pytest.fixture
def sdk(monkeypatch):
    accounts = [dict(ACCOUNTS[0], balance={"total": {"amount": 150000.0, "currency": "USD"}}), dict(ACCOUNTS[1], balance={"total": {"amount": 50000.0, "currency": "USD"}})]
    fake = FakeSdk(list_user_accounts=accounts, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_retire_script_from_accounts_sums_balances(sdk, capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--from-accounts", *ARGS], capsys)
    assert rc == 0, out
    assert out["inputs"]["savings"] == 200000.0 and out["sources"] == {"savings": "snaptrade", "accounts": ["acc-1", "acc-2"]}
    assert out["deterministic"]["balance_at_retirement"] > 200000 and out["monte_carlo"]["simulations"] == 100


def test_retire_script_explicit_savings_no_broker_call(monkeypatch, capsys) -> None:
    monkeypatch.setattr(client, "get_client", lambda settings=None: pytest.fail("broker called"))
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "300000", *ARGS], capsys)
    assert rc == 0 and out["inputs"]["savings"] == 300000.0 and out["sources"] == {"savings": "user", "accounts": []}


def test_retire_script_requires_savings_or_accounts(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ARGS, capsys)
    assert rc == 2 and "--savings" in out["error"]


def test_retire_script_goal_and_withdrawal_modes(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--goal", "1000000", "--years", "30", "--savings", "100000", "--return", "0.07"], capsys)
    assert rc == 0 and out["monthly_contribution_needed"] == 154.39
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--withdrawal", "--savings", "1000000", "--years", "30", "--seed", "1", "--simulations", "50"], capsys)
    assert rc == 0 and [r["rate"] for r in out["table"]][:2] == [0.03, 0.035]


def test_retire_script_ss_claim_mode(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "1000000", "--retirement-age", "65", "--end-age", "95", "--ss-benefit", "30000", "--spending", "60000", "--return", "0.05", "--simulations", "100", "--seed", "11"], capsys)
    assert rc == 0, out
    assert out["action"] == "ss_claim"
    assert [c["age"] for c in out["claiming"]] == [62, 67, 70]
    assert out["claiming"][0]["factor"] == 0.7 and out["claiming"][0]["first_year_benefit"] == 21000.0
    assert out["break_even"]["62_vs_67"] == 78
    assert out["inputs"]["benefit_at_fra"] == 30000.0


def test_retire_script_ss_claim_custom_claim_ages(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "1000000", "--retirement-age", "65", "--ss-benefit", "30000", "--fra-age", "66", "--claim-age", "62", "--claim-age", "70", "--simulations", "50"], capsys)
    assert rc == 0, out
    assert [c["age"] for c in out["claiming"]] == [62, 70]
    assert out["break_even"] == {"62_vs_70": out["break_even"]["62_vs_70"]}


def test_retire_script_ss_claim_requires_retirement_age(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "1000000", "--ss-benefit", "30000"], capsys)
    assert rc == 2 and "retirement-age" in out["error"]


def test_retire_script_guardrail_and_glide_flags(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "300000", *ARGS, "--guardrail-cut", "0.10", "--guardrail-trigger", "0.20", "--ret-return", "0.03", "--ret-vol", "0.08"], capsys)
    assert rc == 0, out
    gr = out["monte_carlo"]["guardrails"]
    assert gr["guardrail_success_probability"] >= gr["constant_success_probability"]
    assert gr["success_probability_gain"] == round(gr["guardrail_success_probability"] - gr["constant_success_probability"], 4)
    assert "guardrail_path" in out["deterministic"]
    assert out["assumptions"]["ret_return"] == 0.03 and out["assumptions"]["ret_vol"] == 0.08


def test_retire_script_guardrail_flags_need_both(capsys) -> None:
    rc, out = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "300000", *ARGS, "--guardrail-cut", "0.10"], capsys)
    assert rc == 2 and "guardrail-trigger" in out["error"]


def test_retirement_math_script_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "goal", "target": 1_000_000, "years": 30, "current": 100_000, "return": 0.07})))
    load_script("retirement/scripts/retirement.py").main()
    assert json.loads(capsys.readouterr().out)["monthly_contribution_needed"] == 154.39


def test_ss_claim_early_claim_factor_is_capped_at_60_months(capsys, monkeypatch) -> None:
    import io
    import sys

    # fra 70 / claim 62 is 96 months early, reachable via input; capped at 60
    # months early -> same factor as exactly 60 months early (0.70)
    payload = {
        "action": "ss_claim",
        "benefit_at_fra": 30000,
        "fra_age": 70,
        "claim_ages": [62],
        "savings": 1_000_000,
        "retirement_age": 65,
        "end_age": 95,
        "return": 0.05,
        "spending": 60000,
        "simulations": 50,
        "seed": 11,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("retirement/scripts/retirement.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["claiming"][0]["factor"] == 0.70


def test_project_outputs_per_year_monte_carlo_percentiles(capsys, monkeypatch) -> None:
    import io

    params = {"action": "project", "age": 40, "retirement_age": 65, "end_age": 95, "savings": 200000, "annual_contribution": 20000, "return": 0.06, "volatility": 0.12, "inflation": 0.025, "spending": 80000, "simulations": 50, "seed": 7}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(params)))
    load_script("retirement/scripts/retirement.py").main()
    out = json.loads(capsys.readouterr().out)
    pp = out["monte_carlo"]["percentile_path"]
    assert [r["age"] for r in pp] == list(range(40, 96)) and set(pp[0]) == {"age", "p10", "p25", "p50", "p75", "p90"}
    assert pp[0]["p10"] == pp[0]["p90"] == 200000.0  # today's balance is certain
    at_ret = next(r for r in pp if r["age"] == 65)
    assert (at_ret["p10"], at_ret["p50"], at_ret["p90"]) == tuple(out["monte_carlo"]["balance_at_retirement"][k] for k in ("p10", "p50", "p90"))
    assert all(r["p10"] <= r["p25"] <= r["p50"] <= r["p75"] <= r["p90"] for r in pp)


def test_render_builds_a_projection_page(capsys, tmp_path) -> None:
    rc, result = run_json(load_script("retirement/scripts/retire.py"), ["--savings", "200000", *ARGS, "--guardrail-cut", "0.1", "--guardrail-trigger", "0.2"], capsys)
    assert rc == 0, result
    result["flags"] = [{"code": "BROKER_UNAVAILABLE", "message": "etrade: <b>login</b> required"}]
    src = tmp_path / "retire.json"
    src.write_text(json.dumps(result))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("retirement/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Retirement Plan", "action": "project", "flags": 1}
    html = out.read_text()
    assert html.startswith("<title>Retirement Plan</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"percentile_path"' in html and '"guardrails"' in html and "const FA" in html
    assert "</b> required" not in html and "<\\/b> required" in html  # data is embedded as JSON, closing tags stay escaped
    for section in ("Projected balance", "Gap at retirement", "Monte Carlo", "Sustainable withdrawal", "Flags", "Not modelled"):
        assert section in html
    assert "Success odds" in html and "Nest egg required" in html and "Contribution to close the gap" in html
    assert f"Success odds {result['monte_carlo']['success_probability'] * 100:.0f}%" in html  # static headline without JS
    # glossary sweep: the explain box and term markers (built by JS at runtime, so assert the toolkit + the SCRIPT calls)
    assert '<div id="explain"></div>' in html and 'class="explain"' in html and "data-term=" in html
    script = html.split("const FA")[1]
    assert "FA.explain(" in script and "FA.term(" in script and "Object.assign(FA.glossary" in script
    for term in ("success odds", "nest egg", "monte carlo", "percentile", "today's dollars", "4% rule", "full retirement age"):
        assert f"T('{term}'" in script or f'T("{term}"' in script, term
    assert "http" not in html.split("window.DATA")[0].replace("http://www.w3.org/2000/svg", "")  # nothing fetched at runtime


def test_render_handles_goal_and_withdrawal_and_bare_math_output(capsys, tmp_path) -> None:
    rc, goal = run_json(load_script("retirement/scripts/retire.py"), ["--goal", "1000000", "--years", "30", "--savings", "100000", "--return", "0.07"], capsys)
    assert rc == 0
    (tmp_path / "goal.json").write_text(json.dumps(goal))
    rc, res = run_json(load_script("retirement/scripts/render.py"), ["--in", str(tmp_path / "goal.json"), "--out", str(tmp_path / "goal.html")], capsys)
    assert rc == 0 and res["action"] == "goal" and "154.39" in (tmp_path / "goal.html").read_text()
    rc, wd = run_json(load_script("retirement/scripts/retire.py"), ["--withdrawal", "--savings", "1000000", "--years", "30", "--seed", "1", "--simulations", "50"], capsys)
    assert rc == 0
    bare = {k: v for k, v in wd.items() if k not in ("action", "inputs", "sources")}  # a raw retirement.py result
    (tmp_path / "wd.json").write_text(json.dumps(bare))
    rc, res = run_json(load_script("retirement/scripts/render.py"), ["--in", str(tmp_path / "wd.json"), "--out", str(tmp_path / "wd.html")], capsys)
    assert rc == 0 and res["action"] == "withdrawal" and "Nest egg $1,000,000 over 30 years" in (tmp_path / "wd.html").read_text()


def test_render_rejects_non_retirement_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"totals": {"total_value": 1}}')
    rc, res = run_json(load_script("retirement/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "retire.py result" in res["error"]
    src.write_text("not json")
    rc, res = run_json(load_script("retirement/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
@pytest.mark.parametrize("mode", ["project", "goal", "withdrawal", "ss_claim"])
def test_every_card_explains_itself(mode, tmp_path, capsys) -> None:
    import json

    argv = {"project": ["--savings", "200000", *ARGS, "--guardrail-cut", "0.1", "--guardrail-trigger", "0.2"],
            "goal": ["--goal", "1000000", "--years", "30", "--savings", "100000", "--return", "0.07"],
            "withdrawal": ["--withdrawal", "--savings", "1000000", "--years", "30", "--seed", "1", "--simulations", "50"],
            "ss_claim": ["--savings", "200000", *ARGS, "--ss-benefit", "30000"]}[mode]
    rc, result = run_json(load_script("retirement/scripts/retire.py"), argv, capsys)
    assert rc == 0, result
    src = tmp_path / "r.json"
    src.write_text(json.dumps(result))
    assert_page_help(render_and_audit("retirement/scripts/render.py", ["--in", str(src)], tmp_path, capsys))
