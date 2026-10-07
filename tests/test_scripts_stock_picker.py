"""Deep picker: gate.py (the downside gate on deep valuations) and render_pick.py (the picks page)."""

from __future__ import annotations

import io
import json
import sys

import pytest
from page_dom import assert_page_help, render_and_audit, requires_chrome
from scripts_util import PLUGIN_ROOT, load_script, run_json

GATE = "stock-screener/scripts/gate.py"


def run_stdin(rel, payload, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script(rel).main()
    return json.loads(capsys.readouterr().out)


def run_stdin_error(rel, payload, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        load_script(rel).main()
    return exc.value.code, json.loads(capsys.readouterr().out)


def finalist(symbol, price, scen):
    """scen: [(name, value_per_share, irr)], first is central."""
    return {"symbol": symbol, "price": price, "page": f"https://example/{symbol}",
            "model": {"scenarios": [{"name": n, "value_per_share": v} for n, v, _ in scen], "implied": {"field": "margin_shift", "value": -0.01}},
            "returns": {"scenarios": [{"name": n, "irr": r} for n, _, r in scen]}}


def test_gate_verdicts_and_order(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [
        finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)]),
        finalist("SAFE", 50, [("Base", 62, 0.11), ("Bear", 45, 0.03)]),
        finalist("ABOVE", 50, [("Base", 70, 0.15), ("Bear", 55, 0.08)]),
        finalist("LOW", 50, [("Base", 52, 0.08), ("Bear", 47, 0.02)]),
    ]}, capsys, monkeypatch)
    assert [r["symbol"] for r in out["results"]] == ["SAFE", "ABOVE", "LOSS", "LOW"]
    by = {r["symbol"]: r for r in out["results"]}
    assert by["SAFE"]["verdict"] == "pass" and by["ABOVE"]["verdict"] == "pass_flagged"
    assert by["LOSS"]["verdict"] == "fail" and "loses 2.0% a year" in by["LOSS"]["reasons"][0]
    assert by["LOW"]["verdict"] == "fail" and "below the 10.0% hurdle" in by["LOW"]["reasons"][0]
    assert by["ABOVE"]["reasons"] == ["Every scenario is worth more than the price; a downside case may be missing."]
    assert by["SAFE"]["worst"] == {"name": "Bear", "irr": 0.03, "value_per_share": 45}
    assert out["counts"] == {"pass": 1, "pass_flagged": 1, "fail": 2}
    assert by["SAFE"]["implied"] == {"field": "margin_shift", "value": -0.01}


def test_gate_custom_hurdle_and_floor(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"hurdle": 0.07, "floor": -0.01, "finalists": [finalist("LOW", 50, [("Base", 52, 0.08), ("Bear", 47, -0.005)])]}, capsys, monkeypatch)
    assert out["results"][0]["verdict"] == "pass"


def test_gate_null_irr_fails(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [finalist("X", 50, [("Base", 60, 0.12), ("Bear", 45, None)])]}, capsys, monkeypatch)
    r = out["results"][0]
    assert r["verdict"] == "fail" and any("could not be computed" in s for s in r["reasons"])


def test_gate_unmatched_scenario_fails(capsys, monkeypatch) -> None:
    f = finalist("X", 50, [("Base", 60, 0.12), ("Bear", 45, 0.02)])
    f["returns"]["scenarios"] = [{"name": "Base", "irr": 0.12}]
    out = run_stdin(GATE, {"finalists": [f]}, capsys, monkeypatch)
    assert out["results"][0]["verdict"] == "fail" and "'Bear'" in out["results"][0]["reasons"][0]


def test_gate_total_loss_fails(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [finalist("X", 50, [("Base", 60, 0.12), ("Bust", 0, -1.0)])]}, capsys, monkeypatch)
    assert out["results"][0]["verdict"] == "fail" and "loses 100.0% a year" in out["results"][0]["reasons"][0]


@pytest.mark.parametrize("payload, needle", [
    ({"finalists": []}, "finalists"),
    ({"hurdle": "x", "finalists": [finalist("X", 50, [("B", 60, 0.1)])]}, "hurdle"),
    ({"finalists": [finalist("X", 0, [("B", 60, 0.1)])]}, "price"),
    ({"finalists": [{"symbol": "X", "price": 5}]}, "model"),
])
def test_gate_validation(payload, needle, capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(GATE, payload, capsys, monkeypatch)
    assert rc == 2 and needle in out["error"]


RENDER = "stock-screener/scripts/render_pick.py"
SAMPLE = PLUGIN_ROOT / "docs/samples/stock-picker.json"


def pick_input() -> dict:
    gate = load_script(GATE).run_gate({"finalists": [
        finalist("SAFE", 50, [("Base", 62, 0.11), ("Bear", 45, 0.03)]),
        finalist("ABOVE", 50, [("Base", 70, 0.15), ("Bear", 55, 0.08)]),
        finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)]),
    ]})
    ev = [{"claim": "Orders up 6%", "source": "10-Q Item 2", "date": "2026-08-01"}]
    return {
        "as_of": "2026-10-05", "profile": "value · years · moderate risk", "gate": json.loads(json.dumps(gate)),
        "funnel": [{"stage": "Industries scanned", "count": 40}, {"stage": "Merged pool", "count": 24}, {"stage": "Finalists", "count": 3}, {"stage": "Picks", "count": 2}],
        "industries": [
            {"sector": "Industrials", "industry": "Railroads", "verdict": "favored", "contrarian": False, "temperature": "Volumes recovering.",
             "growth": "Carloads +3% (AAR, 2026-09-30)", "sentiment": "Neutral.", "leaders": [{"ticker": "SAFE", "name": "Safe Rail", "trend": "gaining"}],
             "prospects": [{"ticker": "OTHER", "name": "OTHER Inc", "market_cap": 2.1e9, "why": "Revenue up 10 of 12 quarters; FCF 4 of 4 years; 3 analysts."}], "evidence": ev},
            {"sector": "Consumer Discretionary", "industry": "Homebuilders", "verdict": "unfavored", "contrarian": True, "temperature": "Rates bite.",
             "growth": "Starts -2% (Census, 2026-09-17)", "sentiment": "Gloomy.", "leaders": [{"ticker": "ABOVE", "name": "Above Homes", "trend": "steady"}], "evidence": ev},
        ],
        "candidates": [
            {"ticker": t, "name": f"{t} Inc", "industry": "Railroads", "origin": o, "held": t == "LOSS",
             "scores": {"quality": 4, "direction": 3, "tailwind": 4, "value": 3}, "reasons": {k: f"{k} reason" for k in ("quality", "direction", "tailwind", "value")},
             "missing": "Market misses X.", "bad_pick": "If Y.", "health": "passed", "finalist": t in ("SAFE", "ABOVE", "LOSS")}
            for t, o in (("SAFE", "both"), ("ABOVE", "industry"), ("LOSS", "screen"), ("OTHER", "screen"))
        ],
        "picks": {"SAFE": {"thesis": "Steady rail volumes at a fair price.", "bad_pick": "A freight recession."},
                  "ABOVE": {"thesis": "Cheap builder.", "bad_pick": "Rates to 8%."}},
        "missing_roles": [], "notes": ["Sample built from invented figures."],
    }


def _render(data, tmp_path, capsys):
    src = tmp_path / "pick.json"
    src.write_text(json.dumps(data))
    return run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)


def test_render_pick_every_section(tmp_path, capsys) -> None:
    rc, res = _render(pick_input(), tmp_path, capsys)
    assert rc == 0, res
    assert res["picks"] == ["SAFE", "ABOVE"] and res["near_misses"] == ["LOSS"] and res["industries"] == 2 and res["candidates"] == 4
    html = (tmp_path / "p.html").read_text()
    assert "SAFE" in html and "Revenue up 10 of 12 quarters" in html


def test_render_pick_no_passes(tmp_path, capsys) -> None:
    data = pick_input()
    data["gate"] = json.loads(json.dumps(load_script(GATE).run_gate({"finalists": [finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)])]})))
    data["picks"] = {}
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 0 and res["picks"] == [] and res["near_misses"] == ["LOSS"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.pop("gate"), "gate"),
    (lambda d: d["industries"][0].update(verdict="great"), "verdict"),
    (lambda d: d["candidates"][0]["scores"].update(quality=6), "score"),
    (lambda d: d["picks"].update(LOSS={"thesis": "x", "bad_pick": "y"}), "LOSS"),
])
def test_render_pick_validation(mutate, needle, tmp_path, capsys) -> None:
    data = pick_input()
    mutate(data)
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 2 and needle in res["error"]


def test_render_pick_rejects_undated_evidence(tmp_path, capsys) -> None:
    data = pick_input()
    del data["industries"][0]["evidence"][0]["date"]
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 2 and "Railroads" in res["error"] and "date" in res["error"]


def test_render_pick_sample_is_current() -> None:
    """docs/samples/stock-picker.json is pick_input() as committed; regenerate it when this fails."""
    assert json.loads(SAMPLE.read_text()) == pick_input()


def test_render_pick_body_intros() -> None:
    import re
    from second_opinion import page
    body = load_script(RENDER).BODY
    for m in re.finditer(r'<section([^>]*)>\s*<h2[^>]*>(.*?)</h2>\s*(<p class="sub)?', body, re.S):
        assert m.group(3), f"section {m.group(2)!r} has no intro line"
    assert page.FLAGS_INTRO in body


@requires_chrome
def test_render_pick_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit(RENDER, ["--in", str(SAMPLE)], tmp_path, capsys)
    assert_page_help(a)
    assert {"Picks", "Near misses", "Industry map", "Candidates"} <= {c["h2"] for c in a["cards"] if not c["hidden"]}


# --- final-review fixes -----------------------------------------------------------------------------


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.update(industries=["oops"]), "industries"),
    (lambda d: d["industries"][0].update(evidence="a string"), "evidence"),
    (lambda d: d.update(candidates=[7]), "candidates"),
    (lambda d: d.update(funnel=[{"stage": "Pool", "remaining": 24}]), "count"),
    (lambda d: d["industries"][0].update(prospects="OTHER"), "prospects"),
    (lambda d: d["industries"][0]["prospects"][0].pop("ticker"), "prospect has no ticker"),
    (lambda d: d["gate"]["results"][0].update(page="javascript:alert(1)"), "https"),
])
def test_render_pick_rejects_malformed_input_with_exit_2(mutate, needle, tmp_path, capsys) -> None:
    data = pick_input()
    mutate(data)
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 2 and needle in res["error"], res


# --- deferred minors -------------------------------------------------------------------------------


def test_gate_nan_irr_counts_as_not_computed(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"finalists": [{"symbol": "X", "price": 50, "model": {"scenarios": [{"name": "Base", "value_per_share": 60}, {"name": "Bear", "value_per_share": 45}]}, "returns": {"scenarios": [{"name": "Base", "irr": 0.12}, {"name": "Bear", "irr": NaN}]}}]}'))
    load_script(GATE).main()
    raw = capsys.readouterr().out
    assert "NaN" not in raw
    r = json.loads(raw)["results"][0]
    assert r["verdict"] == "fail" and any("'Bear' could not be computed" in s for s in r["reasons"])


@pytest.mark.parametrize("floor, irr, text", [
    (0.0, -0.02, "Worst scenario 'Bear' loses 2.0% a year, below the 0.0% floor."),
    (-0.05, -0.10, "Worst scenario 'Bear' loses 10.0% a year, below the -5.0% floor."),
    (0.03, 0.01, "Worst scenario 'Bear' earns 1.0% a year, below the 3.0% floor."),
])
def test_gate_floor_reason_always_names_the_floor(floor, irr, text, capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"floor": floor, "finalists": [finalist("X", 50, [("Base", 60, 0.12), ("Bear", 45, irr)])]}, capsys, monkeypatch)
    assert out["results"][0]["reasons"][0] == text


def test_gate_uses_the_price_the_returns_used(capsys, monkeypatch) -> None:
    f = finalist("X", 50, [("Base", 62, 0.11), ("Bear", 52, 0.03)])
    f["returns"]["price"] = 50.2
    out = run_stdin(GATE, {"finalists": [f]}, capsys, monkeypatch)
    assert out["results"][0]["price"] == 50.2
    f["returns"]["price"] = 60
    rc, err = run_stdin_error(GATE, {"finalists": [f]}, capsys, monkeypatch)
    assert rc == 2 and "price" in err["error"] and "returns" in err["error"]


def test_gate_reports_the_value_range(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [finalist("X", 50, [("Base", 62, 0.11), ("Bull", 80, 0.2), ("Bear", 45, 0.03)])]}, capsys, monkeypatch)
    assert out["results"][0]["value_range"] == [45, 80]


def _dom_text(data, tmp_path, capsys) -> str:
    """The page's visible text after its script runs (headless Chrome)."""
    import re
    import subprocess
    from page_dom import CHROME
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 0, res
    doc = tmp_path / "full.html"
    doc.write_text(f'<!doctype html><html><head><meta charset="utf-8"></head><body>{(tmp_path / "p.html").read_text()}</body></html>')
    out = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=2000", "--dump-dom", doc.as_uri()],
                         capture_output=True, text=True, timeout=90).stdout
    body = out[out.find("<body"):]
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


@requires_chrome
def test_render_pick_no_passes_shows_the_message_and_near_misses(tmp_path, capsys) -> None:
    data = pick_input()
    data["gate"] = json.loads(json.dumps(load_script(GATE).run_gate({"finalists": [finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)])]})))
    data["picks"] = {}
    text = _dom_text(data, tmp_path, capsys)
    assert "No finalist passed the downside gate." in text
    assert "LOSS" in text and "Worst scenario 'Bear' loses 2.0% a year" in text


@requires_chrome
def test_render_pick_card_shows_the_value_range(tmp_path, capsys) -> None:
    text = _dom_text(pick_input(), tmp_path, capsys)
    assert "value $45.00 – $62.00" in text


@requires_chrome
def test_render_pick_leads_with_the_central_value(tmp_path, capsys) -> None:
    text = _dom_text(pick_input(), tmp_path, capsys)
    assert "Central value $62.00 vs price $50.00 · +11.0% a year" in text
    assert text.index("Central value $62.00") < text.index("worst Bear")
    assert "central $60.00 · +12.0% a year · worst" in text  # near-miss row (LOSS)
    assert "first scenario of the deep valuation" in (tmp_path / "p.html").read_text() and "not averaged" in (tmp_path / "p.html").read_text()
