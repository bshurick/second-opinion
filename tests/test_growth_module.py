from __future__ import annotations

import json

import pytest

from scripts_util import load_script
from second_opinion.errors import InvalidInput

growth = load_script("stock-screener/scripts/growth.py")


def test_run_profile_defaults_to_value(tmp_path):
    assert growth.run_profile(tmp_path) == "value"


def test_run_profile_rejects_unknown(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps({"profile": "momentum"}))
    with pytest.raises(InvalidInput):
        growth.run_profile(tmp_path)


def test_write_profile_round_trips_and_overwrites(tmp_path):
    path = growth.write_profile(tmp_path, "growth")
    assert path == tmp_path / "run.json" and json.loads(path.read_text()) == {"profile": "growth"}
    assert growth.run_profile(tmp_path) == "growth"
    growth.write_profile(tmp_path, "value")
    assert growth.run_profile(tmp_path) == "value"


def test_write_profile_rejects_unknown(tmp_path):
    with pytest.raises(InvalidInput):
        growth.write_profile(tmp_path, "momentum")


def test_best_irr_needed():
    assert growth.MIN_UPSIDE_DEFAULT == 2.0 and growth.PROFILES == ("value", "growth")
    assert round(growth.best_irr_needed(2.0, 5), 4) == 0.1487


@pytest.mark.parametrize("upside,horizon", [(1.0, 5), (0.5, 5), (2.0, 0)])
def test_best_irr_needed_rejects_bad_input(upside, horizon):
    with pytest.raises(ValueError):
        growth.best_irr_needed(upside, horizon)


@pytest.mark.parametrize("bull,base,hint", [(220, 120, 5), (160, 110, 4), (160, 90, 3), (120, 90, 2), (90, 90, 1)])
def test_upside_hint_rungs(bull, base, hint):
    assert growth.upside_hint({"basis": "dcf", "bull": bull, "base": base}, 100, 10) == hint


@pytest.mark.parametrize("quick,price,fcf", [
    ({"basis": None, "bull": 220, "base": 120}, 100, 10),
    ({"basis": "dcf", "bull": 220, "base": 120}, 100, -5),
    ({"basis": "dcf", "bull": 220, "base": 120}, None, 10),
    ({"basis": "dcf", "base": 120}, 100, 10),
])
def test_upside_hint_is_null_without_a_return(quick, price, fcf):
    assert growth.upside_hint(quick, price, fcf) is None


def test_yardstick_solves_the_growth_the_price_and_a_double_need():
    y = growth.yardstick(1000.0, 0.0, 100.0, 0.30, None, None, 0.40, consensus_growth=0.35)
    assert y["margin"] == round(0.30 * 0.79, 4) and y["benchmark"] == 0.35
    assert y["implied_growth"] < y["growth_for_upside"]
    # the solved growth reproduces the enterprise value at each rate
    assert abs(growth._yardstick_value(100.0, y["margin"], y["implied_growth"], growth.PRICE_RATE) - 1000.0) < 1.0
    assert abs(growth._yardstick_value(100.0, y["margin"], y["growth_for_upside"], y["rate_for_upside"]) - 1000.0) < 1.0
    assert y["rate_for_upside"] == round(2 ** 0.2 - 1, 4)


@pytest.mark.parametrize("bench, hint", [(1.0, 5), (0.5, 3), (0.40, 2), (0.10, 1)])
def test_yardstick_hint_measures_need_against_the_benchmark(bench, hint):
    need = growth.yardstick(1000.0, 0.0, 100.0, 0.30, None, None, 2.0)["growth_for_upside"]
    y = growth.yardstick(1000.0, 0.0, 100.0, 0.30, None, None, 2.0, consensus_growth=bench)
    ratio = need / bench
    expected = 5 if ratio <= 0.6 else 4 if ratio <= 0.8 else 3 if ratio <= 1 else 2 if ratio <= 1.3 else 1
    assert y["hint"] == expected == hint


def test_yardstick_never_benchmarks_above_trailing_growth():
    assert growth.yardstick(1000.0, 0.0, 100.0, 0.30, None, None, 0.20, consensus_growth=0.60)["benchmark"] == 0.20


def test_yardstick_leaves_out_cash_that_outruns_profit():
    """A lender's or marketplace's free cash flow counts customer money; DAVE's ran 24 points above its net margin."""
    y = growth.yardstick(1000.0, 0.0, 100.0, None, 0.28, 0.52, 0.40)
    assert y["flags"] == ["CASH_OUTRUNS_PROFIT"] and y["margin"] == 0.28


def test_yardstick_takes_the_larger_cash_margin_when_both_are_sound():
    assert growth.yardstick(1000.0, 0.0, 100.0, 0.20, None, 0.25, 0.40)["margin"] == 0.25


@pytest.mark.parametrize("args", [
    (None, 0.0, 100.0, 0.3, None, None, 0.4),    # no market value
    (1000.0, 0.0, None, 0.3, None, None, 0.4),   # no revenue
    (1000.0, 0.0, 100.0, -0.1, None, None, 0.4),  # losing money
    (1000.0, 0.0, 100.0, 0.3, None, None, None),  # no growth figure
])
def test_yardstick_without_a_reading_has_no_hint(args):
    y = growth.yardstick(*args)
    assert y["hint"] is None and y["why"]
