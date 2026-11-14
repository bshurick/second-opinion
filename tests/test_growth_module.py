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
