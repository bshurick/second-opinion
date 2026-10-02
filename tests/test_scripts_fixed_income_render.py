"""skills/fixed-income/scripts/render.py: what reaches the page, and that it always renders.

The page is drawn in the browser from ``view()``'s output, so these tests check that object: which
figures are on it, how they are converted and worded, and that nothing unnamed gets there. The
fixture is the README sample, generated from the real scripts (fund.py BND, horizon.py at 8 years,
rates.py), so every figure below is one those scripts produced.
"""

from __future__ import annotations

import copy
import itertools
import json
import re

import pytest

from scripts_util import PLUGIN_ROOT, load_script, run_json
from page_dom import assert_page_help, render_and_audit, requires_chrome

RENDER = load_script("fixed-income/scripts/render.py")
SAMPLE = json.loads((PLUGIN_ROOT / "docs" / "samples" / "fixed-income.json").read_text())

FORBIDDEN_VERBS = re.compile(r"\b(recommend\w*|advis\w*|should|suggest\w*)\b", re.I)
# The disclaimers name what the page is not; those negations are the one allowed use.
DISCLAIMERS = re.compile(r"not a recommendation|not financial, tax, or legal advice|No fair value", re.I)
VERDICT_WORDS = re.compile(r"\b(cheap|expensive|undervalued|overvalued|bargain|rich)\b", re.I)


def _view(payload: dict, symbol: str = "BND") -> dict:
    return RENDER.view(payload, symbol)[0]


def _page_strings(v: dict) -> list[str]:
    """Every string in the view except the disclosures, which are the scripts' own text."""
    out: list[str] = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for k, val in x.items():
                if k not in ("disclosures",):
                    walk(val)
        elif isinstance(x, list):
            for val in x:
                walk(val)

    walk(v)
    return out


# --- every combination of inputs renders ---


@pytest.mark.parametrize(
    "parts", [c for n in (1, 2, 3) for c in itertools.combinations(("horizon", "rates", "fund"), n)]
)
def test_every_combination_of_results_renders(parts, tmp_path, capsys) -> None:
    payload = {"symbol": "BND", **{k: SAMPLE[k] for k in parts}}
    path = tmp_path / "in.json"
    path.write_text(json.dumps(payload))
    rc, res = run_json(RENDER, ["--in", str(path), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0, res
    html = (tmp_path / "p.html").read_text()
    assert "NaN" not in html and "undefined" not in html.split("<script>window.DATA")[0]


def test_no_results_is_invalid_input(tmp_path, capsys) -> None:
    path = tmp_path / "in.json"
    path.write_text(json.dumps({"symbol": "BND"}))
    rc, res = run_json(RENDER, ["--in", str(path), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "at least one of" in res["error"]


def _mutations():
    """Each top-level key of each result deleted, set to null, or set to the wrong type."""
    for part in ("horizon", "rates", "fund"):
        for key in SAMPLE[part]:
            for bad in ("DELETE", None, "text", [1], {"x": 1}, True):
                yield part, key, bad


@pytest.mark.parametrize("part,key,bad", list(_mutations()))
def test_a_missing_or_malformed_field_never_breaks_the_page(part, key, bad) -> None:
    payload = copy.deepcopy(SAMPLE)
    if bad == "DELETE":
        del payload[part][key]
    else:
        payload[part][key] = bad
    html, _title, _sections = RENDER.build(payload)
    assert "window.DATA" in html
    json.dumps(_view(payload), allow_nan=False)  # every figure is finite JSON


def test_a_null_figure_is_left_out_never_drawn_as_zero() -> None:
    payload = copy.deepcopy(SAMPLE)
    payload["fund"]["characteristics"]["distribution_yield_pct"] = None
    payload["rates"]["benchmarks"]["bill_3m_pct"] = None
    v = _view(payload)
    dist = next(y for y in v["yields"] if y["label"] == "Distribution yield")
    assert dist["pct"] is None
    assert v["answer"]["vs_cash_pp"] is None and v["answer"]["cash_pct"] is None
    assert all(r["kind"] != "cash" for r in v["compare"])


# --- the figures, and their conversions ---


def test_every_compared_rate_is_an_effective_annual_rate() -> None:
    v = _view(SAMPLE)
    rows = {r["label"]: r["pct"] for r in v["compare"]}
    bill = SAMPLE["rates"]["benchmarks"]["bill_3m_pct"]
    ten = SAMPLE["rates"]["par_curve"]["10.0"]
    assert rows["Cash (3-month Treasury bill)"] == round(((1 + bill / 200) ** 2 - 1) * 100, 2)
    assert rows["10-year Treasury"] == round(((1 + ten / 200) ** 2 - 1) * 100, 2)
    # The horizon return is already effective, so it goes on the page unconverted.
    assert rows["BND, held 8 years"] == round(SAMPLE["horizon"]["locked_in_return_pct"], 2)


def test_the_short_answer_matches_the_scripts() -> None:
    a = _view(SAMPLE)["answer"]
    hor = SAMPLE["horizon"]
    up = next(r for r in hor["scenarios"] if r["delta_yield_bp"] == 100)
    assert a["return_pct"] == round(hor["locked_in_return_pct"], 1)
    assert a["up1_now_pct"] == round(up["immediate_price_change_pct"], 1)
    assert a["up1_held_pct"] == round(up["annualised_pct"], 1)
    assert a["sentence"].startswith("Held about 8 years, BND works out to roughly")
    assert "points more a year than cash" in a["sentence"]


def test_the_sentence_says_less_when_cash_pays_more() -> None:
    payload = copy.deepcopy(SAMPLE)
    payload["rates"]["benchmarks"]["bill_3m_pct"] = 9.0
    assert "points less a year than cash" in _view(payload)["answer"]["sentence"]


def test_the_paths_are_ten_thousand_dollars_and_cross_near_duration() -> None:
    a = _view(SAMPLE)["answer"]
    assert [p["bp"] for p in a["paths"]] == [-100, 0, 100]
    base = next(p for p in a["paths"] if p["bp"] == 0)
    assert base["points"][0] == [0, 10000.0]
    macaulay = SAMPLE["horizon"]["duration_years"]
    assert a["crossover_years"] is not None and abs(a["crossover_years"] - macaulay) < 1.0


def test_a_short_horizon_has_no_crossover() -> None:
    paths = [
        {"bp": 0, "points": [[0, 10000.0], [1, 10500.0]]},
        {"bp": 100, "points": [[0, 9300.0], [1, 9800.0]]},
    ]
    assert RENDER.crossover_years(paths) is None


@pytest.mark.parametrize(
    "rank,text",
    [
        (100, "At or near the highest on record since 2003"),
        (0, "At or near the lowest on record since 2003"),
        (52, "Higher than 52% of days since 2003"),
        (48, "Lower than 52% of days since 2003"),
    ],
)
def test_ranks_read_as_plain_words(rank, text) -> None:
    assert RENDER._rank_text(rank, "2003") == text


def test_history_splits_three_main_strips_from_two_deeper_ones() -> None:
    v = _view(SAMPLE)
    assert [h["key"] for h in v["history"]] == ["treasury_10y", "real_yield_10y", "credit_spread_baa"]
    assert [h["key"] for h in v["deeper"]["history"]] == ["breakeven_10y", "term_premium_10y"]


# --- what may and may not reach the page ---


def test_an_unnamed_key_never_reaches_the_page() -> None:
    payload = copy.deepcopy(SAMPLE)
    payload["fund"]["advice"] = "BUY THIS FUND NOW"
    payload["horizon"]["verdict"] = "BUY THIS FUND NOW"
    payload["rates"]["percentiles"]["treasury_10y"]["comment"] = "BUY THIS FUND NOW"
    html, _t, _s = RENDER.build(payload)
    assert "BUY THIS FUND NOW" not in html


def test_the_page_writes_no_advice_and_no_verdict() -> None:
    v = _view(SAMPLE)
    for text in _page_strings(v) + [RENDER.BODY, RENDER.SCRIPT]:
        text = DISCLAIMERS.sub("", text)
        assert not FORBIDDEN_VERBS.search(text), text
        assert not VERDICT_WORDS.search(text), text


def test_every_assumption_string_reaches_the_details_modal_verbatim() -> None:
    v = _view(SAMPLE)
    shown = {p["text"] for g in v["disclosures"] for p in g["prose"]}
    for part in ("horizon", "rates", "fund"):
        for value in SAMPLE[part]["assumptions"].values():
            if isinstance(value, str):
                assert value in shown
    for note in (SAMPLE["horizon"]["mismatch_cost_note"], SAMPLE["fund"]["circularity_note"], SAMPLE["rates"]["note"]):
        assert note in shown
    assert v["closing_note"] == RENDER.CLOSING_NOTE


def test_the_circularity_note_travels_with_the_calculated_yield() -> None:
    dec = _view(SAMPLE)["deeper"]["decomposition"]
    assert any(r["label"].startswith("Calculated yield") for r in dec["rows"])
    assert dec["circularity_note"] == SAMPLE["fund"]["circularity_note"]
    payload = copy.deepcopy(SAMPLE)
    payload["fund"]["yield_decomposition"]["calculated_ytm_pct"] = None
    dec = _view(payload)["deeper"]["decomposition"]
    assert not any(r["label"].startswith("Calculated yield") for r in dec["rows"])
    assert dec["circularity_note"] is None


def test_every_tour_step_points_at_a_section_on_the_page() -> None:
    ids = set(re.findall(r'id="([\w-]+)"', RENDER.BODY))
    for step in RENDER.TOUR:
        assert step["target"].lstrip("#") in ids


def test_a_hostile_symbol_is_escaped_in_the_title(tmp_path) -> None:
    payload = {**SAMPLE, "symbol": "X</title><script>alert(1)</script>"}
    html, _t, _s = RENDER.build(payload)
    assert "<script>alert(1)" not in html.split("<script>window.DATA")[0]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit("fixed-income/scripts/render.py", ["--in", str(PLUGIN_ROOT / "docs/samples/fixed-income.json")], tmp_path, capsys)
    assert_page_help(a)
    assert sum(1 for c in a["cards"] if c["help"] == "authored") >= 3
