import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BOND = PLUGIN_ROOT / "skills" / "fixed-income" / "scripts" / "bond.py"


def run_bond(payload: dict) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(BOND)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, json.loads(proc.stdout)


def test_par_bond_from_yield():
    code, out = run_bond({"coupon_rate": 0.05, "years": 10, "ytm": 0.05})
    assert code == 0
    assert out["price"] == pytest.approx(100.0, abs=1e-6)
    assert out["modified_duration"] < 10


def test_yield_solves_from_price():
    code, out = run_bond({"coupon_rate": 0.04, "years": 5, "price": 95.0})
    assert code == 0
    assert out["ytm"] > 0.04  # a discount bond yields more than its coupon


def test_price_map_is_monotonically_decreasing_in_yield():
    code, out = run_bond({"coupon_rate": 0.04, "years": 10, "ytm": 0.05})
    prices = [row["price"] for row in out["price_map"]]
    assert prices == sorted(prices, reverse=True)


def test_missing_both_price_and_ytm_is_invalid_input():
    code, out = run_bond({"coupon_rate": 0.05, "years": 10})
    assert code == 2
    # Assert the SPECIFIC rejection. `code == 2` alone is satisfied by any
    # failure: with the mutual-exclusion guard deleted this payload still exits 2,
    # because params["price"] raises KeyError and main reports {"error": "'price'"}.
    assert "exactly one" in out["error"]


def test_both_price_and_ytm_is_invalid_input():
    code, out = run_bond({"coupon_rate": 0.05, "years": 10, "price": 99, "ytm": 0.05})
    assert code == 2
    assert "exactly one" in out["error"]


# F51: bond.py's docstring is the contract SKILL.md sends a reader to, and its example block was
# written by hand and wrong in every figure (convexity 78.4 against an actual 74.74, a price_map
# row at a yield that is not on the emitted grid). Regenerated from a real run; this is what keeps
# it regenerated. Each figure is read out of the docstring, not restated here.
DOCSTRING_INPUT = {"coupon_rate": 0.045, "years": 10, "ytm": 0.0531, "freq": 2, "face": 100.0}
DOCSTRING_FIGURES = (
    ('"price": ', "price"),
    ('"macaulay_duration": ', "macaulay_duration"),
    ('"modified_duration": ', "modified_duration"),
    ('"convexity": ', "convexity"),
    ('"cashflow_count": ', "cashflow_count"),
    ('"total_coupons": ', "total_coupons"),
)


def _docstring_figure(docstring: str, marker: str) -> float:
    after = docstring.split(marker, 1)[1]
    return float(after.split(",", 1)[0].split("\n", 1)[0].strip())


def test_the_docstrings_example_output_is_what_the_script_actually_prints():
    # The OUTPUT block only: the input contract above it carries a "price" key of its own.
    docstring = BOND.read_text().split('"""')[1].split("Output JSON contract", 1)[1]
    code, out = run_bond(DOCSTRING_INPUT)
    assert code == 0
    for marker, key in DOCSTRING_FIGURES:
        assert _docstring_figure(docstring, marker) == out[key], marker
    # The two price_map rows the docstring shows, and the claim it makes about the grid.
    assert '{"ytm": 0.0281, "price": 114.6443}' in docstring
    assert '{"ytm": 0.0306, "price": 112.3249}' in docstring
    assert out["price_map"][0] == {"ytm": 0.0281, "price": 114.6443}
    assert out["price_map"][1] == {"ytm": 0.0306, "price": 112.3249}
    assert len(out["price_map"]) == 21
    assert 0.03 not in [row["ytm"] for row in out["price_map"]]
    # The assumptions block the docstring now shows, and the claim about it that horizon.py's
    # exit-2 message depends on: both parameters are echoed, one level down.
    assert out["assumptions"] == {
        "coupon_rate": 0.045,
        "years": 10.0,
        "freq": 2,
        "face": 100.0,
        "solved_for": "price",
        "note": (
            "Flat-yield pricing. A real bond also carries a credit spread and, "
            "if callable, an option cost."
        ),
    }
    assert "coupon_rate" not in out and "years" not in out


def _raw_bond(payload: dict) -> tuple[int, str]:
    """The same call as ``run_bond``, but without parsing -- these cases used not to parse."""
    proc = subprocess.run(
        [sys.executable, str(BOND)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout


def _strict_loads(raw: str):
    """json.loads that rejects NaN/Infinity, which the default parser accepts but JSON does not."""

    def reject(token: str):
        raise ValueError(f"non-finite token in output: {token}")

    return json.loads(raw, parse_constant=reject)


def test_a_yield_too_large_to_price_exits_two_with_json():
    # bond.py's docstring promises exit 0 or exit 2 with {"error": ...}. An uncaught OverflowError
    # broke that on a ONE-YEAR bond -- two coupon periods, nothing to do with the resource bound --
    # exiting 1 with stdout completely empty, so a caller got no exit code it recognised and
    # nothing to read. horizon.py already handled the identical payload correctly.
    code, raw = _raw_bond({"coupon_rate": 0.05, "years": 1, "ytm": 1e308})
    assert code == 2
    assert "error" in _strict_loads(raw)


def test_figures_that_price_to_infinity_exit_two_rather_than_printing_nan():
    # A coupon and face of 1e308 are finite inputs that price to Infinity, and the durations that
    # divide by that price to NaN. Python prints both as bare tokens and exits 0, so the script
    # reported success having written something jq and JSON.parse both reject -- against the
    # constraint that every script here prints JSON on stdout.
    code, raw = _raw_bond({"coupon_rate": 1e308, "years": 1, "ytm": 0.05, "face": 1e308})
    assert code == 2
    assert "error" in _strict_loads(raw)
    assert "Infinity" not in raw and "NaN" not in raw


def test_ordinary_bonds_still_price_and_parse_strictly():
    # The guard rejects; it must not have narrowed what succeeds.
    for payload in (
        {"coupon_rate": 0.05, "years": 10, "ytm": 0.04},
        {"coupon_rate": 0.05, "years": 10, "price": 108.1757},
        {"coupon_rate": 0.0, "years": 5, "ytm": 0.04},
    ):
        code, raw = _raw_bond(payload)
        assert code == 0, payload
        assert _strict_loads(raw)["price"] > 0
