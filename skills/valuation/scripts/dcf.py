"""Two-stage FCFF discounted cash flow valuation with a sensitivity grid.

This script reads a JSON object from stdin, runs a vetted two-stage
free-cash-flow-to-firm DCF (explicit stage-1 forecast + Gordon-growth
terminal value), and writes a JSON object to stdout. It is invoked as:

    python dcf.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "fcf0": 100.0,                  # trailing free cash flow to firm
      "growth_rate": 0.08,            # stage-1 annual growth rate (decimal).
                                       # Required unless stage1_growth is
                                       # given; then optional, defaulting to
                                       # the schedule's mean (echoed only).
      "stage1_growth": [0.20, 0.15],  # optional per-year stage-1 growth rates
                                       # (a fade schedule); when present its
                                       # length must equal "years"
      "years": 5,                     # stage-1 length, integer 1..20
      "terminal_growth": 0.025,       # perpetuity growth rate; must be < wacc
      "wacc": 0.09,                   # discount rate; must be > 0
      "net_debt": 250.0,              # total debt minus cash (any sign)
      "shares_outstanding": 50.0,     # must be > 0
      "current_share_price": 34.97,   # optional; enables the reverse-DCF
                                       # "implied" block (see below)
      "sensitivity": {                # optional; defaults shown
        "wacc_step": 0.005,
        "growth_step": 0.005,
        "steps": 2                    # grid spans base +/- steps
      }
    }

Output JSON contract (stdout)::

    {
      "pv_stage1": ...,                    # PV of stage-1 FCFs, 2dp
      "pv_terminal": ...,                  # PV of terminal value, 2dp
      "enterprise_value": ...,             # pv_stage1 + pv_terminal, 2dp
      "equity_value": ...,                 # enterprise_value - net_debt, 2dp
      "fair_value_per_share": ...,         # equity_value / shares, 2dp
      "terminal_value_share_of_ev": ...,   # pv_terminal / enterprise_value, 4dp
                                           # (defined as 0.0 when enterprise_value
                                           # is 0, e.g. fcf0=0 for a pre-FCF company)
      "implied": {                         # only when current_share_price is given
        "current_share_price": ...,        # echoed input, 2dp
        "stage1_growth": ...,              # UNIFORM stage-1 growth rate that makes
                                           # fair_value_per_share equal the price,
                                           # solved at the base terminal_growth;
                                           # null when no admissible rate does
        "terminal_growth": ...             # terminal growth that reproduces the
                                           # price at the base stage-1 growth
                                           # (scalar, or the stage1_growth
                                           # schedule when given); null when the
                                           # price implies terminal_growth >= wacc
      },
      "inputs_echo": { ... resolved inputs, including defaulted sensitivity ... },
      "sensitivity_grid": {
        "wacc_values": [...],              # rows, 4dp
        "terminal_growth_values": [...],   # cols, 4dp
        "fair_value_per_share": [[...], ...]  # rows=wacc, cols=tg; null where tg >= wacc
      }
    }

Reverse-DCF solve (bisection): fair value is monotone in both stage-1
growth and terminal growth, so plain bisection suffices. The stage-1
growth is solved on [-0.99, 1.0] (per-year shrink of at most 99%, growth
of at most 100% — beyond that a DCF says more about the bounds than the
company); the terminal growth on [-0.99, wacc - 1e-6] (it must stay
strictly below wacc). Both use 100 iterations, which halves the bracket
100 times (final resolution ~1e-30, far past float64 precision), and the
solved rate is reported rounded to 6dp. When the price lies outside what
those bounds can produce, the field is null rather than an error.

Validation errors (missing fields, non-object input, non-positive wacc,
non-positive shares_outstanding, years outside 1..20, terminal_growth >=
wacc, stage1_growth that is not a list of exactly `years` numbers) are
reported as ``{"error": "..."}`` on stdout with exit code 2.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence

_DEFAULT_SENSITIVITY = {"wacc_step": 0.005, "growth_step": 0.005, "steps": 2}

_BISECT_ITERATIONS = 100
_STAGE1_GROWTH_BOUNDS = (-0.99, 1.0)
_TERMINAL_GROWTH_FLOOR = -0.99
_WACC_EPSILON = 1e-6


def _coerce_int(value: object, field: str) -> int:
    """Accept int or integral float (JSON has one numeric type; LLM callers
    emit 5 or 5.0 interchangeably). Reject bools, non-integral floats, and
    non-numeric types."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{field} must be an integer")


_REQUIRED_FIELDS = (
    "fcf0",
    "growth_rate",
    "years",
    "terminal_growth",
    "wacc",
    "net_debt",
    "shares_outstanding",
)


def _discounted_values(
    fcf0: float, growth_rates: Sequence[float], terminal_growth: float, wacc: float
) -> tuple[float, float] | None:
    """Return (pv_stage1, pv_terminal) or None if terminal_growth >= wacc.

    Stage-1 FCF_t compounds fcf0 by growth_rates[t-1] in year t and is
    discounted at wacc. Terminal value is a YEAR-N value (Gordon growth on
    FCF_{N+1} = FCF_N * (1+terminal_growth)), so it is discounted back N
    years, not N+1.
    """
    if terminal_growth >= wacc:
        return None

    pv_stage1 = 0.0
    fcf_t = fcf0
    for t, rate in enumerate(growth_rates, start=1):
        fcf_t = fcf_t * (1 + rate)
        pv_stage1 += fcf_t / (1 + wacc) ** t

    terminal_value = fcf_t * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** len(growth_rates)

    return pv_stage1, pv_terminal


def _fair_value(
    fcf0: float,
    growth_rates: Sequence[float],
    terminal_growth: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
) -> float | None:
    """Fair value per share for one (growth, terminal_growth) pair, or None
    when terminal_growth >= wacc makes the Gordon term undefined."""
    cell = _discounted_values(fcf0, growth_rates, terminal_growth, wacc)
    if cell is None:
        return None
    pv_stage1, pv_terminal = cell
    return (pv_stage1 + pv_terminal - net_debt) / shares_outstanding


def _bisect_increasing(
    fn: Callable[[float], float | None], low: float, high: float, target: float
) -> float | None:
    """Bisect ``fn`` (monotone in its argument) for fn(x) == target on
    [low, high]; return the solved argument rounded to 6dp, or None when the
    bracket cannot produce the target (or fn is undefined at a bound)."""
    f_low = fn(low)
    f_high = fn(high)
    if f_low is None or f_high is None:
        return None
    if f_low > f_high:  # allow a decreasing fn; bisection works either way
        low, high = high, low
        f_low, f_high = f_high, f_low
    if f_low == f_high or target < f_low or target > f_high:
        return None
    for _ in range(_BISECT_ITERATIONS):
        mid = (low + high) / 2
        f_mid = fn(mid)
        if f_mid is None:
            return None
        if f_mid < target:
            low = mid
        else:
            high = mid
    return round((low + high) / 2, 6)


def run_dcf(params: dict) -> dict:
    """Run the two-stage DCF described by ``params`` and return the result dict.

    Raises ValueError (or TypeError for non-numeric fields) on invalid input;
    callers that need the stdin/stdout error contract should use main().
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")

    has_schedule = params.get("stage1_growth") is not None
    missing = [
        field
        for field in _REQUIRED_FIELDS
        if field not in params and not (field == "growth_rate" and has_schedule)
    ]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    fcf0 = float(params["fcf0"])
    if "growth_rate" in params:
        growth_rate = float(params["growth_rate"])
    else:  # a schedule was given (checked above); echo its mean as the scalar rate
        schedule = params["stage1_growth"]
        if not isinstance(schedule, list) or not schedule:
            raise ValueError("stage1_growth must be a list of per-year growth rates")
        growth_rate = sum(float(r) for r in schedule) / len(schedule)
    years = params["years"]
    terminal_growth = float(params["terminal_growth"])
    wacc = float(params["wacc"])
    net_debt = float(params["net_debt"])
    shares_outstanding = float(params["shares_outstanding"])

    years = _coerce_int(years, "years")
    if years <= 0 or years > 20:
        raise ValueError("years must be between 1 and 20")
    if wacc <= 0:
        raise ValueError("wacc must be positive")
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")
    if terminal_growth >= wacc:
        raise ValueError("terminal_growth must be less than wacc")

    stage1_growth_raw = params.get("stage1_growth")
    if stage1_growth_raw is None:
        rates: list[float] = [growth_rate] * years
    else:
        if not isinstance(stage1_growth_raw, list):
            raise ValueError("stage1_growth must be a list of per-year growth rates")
        if len(stage1_growth_raw) != years:
            raise ValueError(
                f"stage1_growth must have exactly {years} entries (one per stage-1 year)"
            )
        rates = [float(rate) for rate in stage1_growth_raw]

    sensitivity_in = params.get("sensitivity", {})
    if not isinstance(sensitivity_in, dict):
        raise ValueError("sensitivity must be an object")
    sensitivity = {**_DEFAULT_SENSITIVITY, **sensitivity_in}
    wacc_step = float(sensitivity["wacc_step"])
    growth_step = float(sensitivity["growth_step"])
    steps = _coerce_int(sensitivity["steps"], "sensitivity.steps")
    if steps < 0:
        raise ValueError("sensitivity.steps must be a non-negative integer")

    base = _discounted_values(fcf0, rates, terminal_growth, wacc)
    assert base is not None  # terminal_growth < wacc already validated above
    pv_stage1, pv_terminal = base
    enterprise_value = pv_stage1 + pv_terminal
    equity_value = enterprise_value - net_debt
    fair_value_per_share = equity_value / shares_outstanding
    terminal_value_share_of_ev = pv_terminal / enterprise_value if enterprise_value != 0 else 0.0

    wacc_values = [wacc + wacc_step * i for i in range(-steps, steps + 1)]
    tg_values = [terminal_growth + growth_step * j for j in range(-steps, steps + 1)]

    grid: list[list[float | None]] = []
    for w in wacc_values:
        row: list[float | None] = []
        for tg in tg_values:
            cell_fair_value = _fair_value(fcf0, rates, tg, w, net_debt, shares_outstanding)
            row.append(None if cell_fair_value is None else round(cell_fair_value, 2))
        grid.append(row)

    result: dict = {
        "pv_stage1": round(pv_stage1, 2),
        "pv_terminal": round(pv_terminal, 2),
        "enterprise_value": round(enterprise_value, 2),
        "equity_value": round(equity_value, 2),
        "fair_value_per_share": round(fair_value_per_share, 2),
        "terminal_value_share_of_ev": round(terminal_value_share_of_ev, 4),
        "inputs_echo": {
            "fcf0": fcf0,
            "growth_rate": growth_rate,
            "stage1_growth": stage1_growth_raw,
            "years": years,
            "terminal_growth": terminal_growth,
            "wacc": wacc,
            "net_debt": net_debt,
            "shares_outstanding": shares_outstanding,
            "sensitivity": {
                "wacc_step": wacc_step,
                "growth_step": growth_step,
                "steps": steps,
            },
        },
        "sensitivity_grid": {
            "wacc_values": [round(w, 4) for w in wacc_values],
            "terminal_growth_values": [round(tg, 4) for tg in tg_values],
            "fair_value_per_share": grid,
        },
    }

    current_share_price = params.get("current_share_price")
    if current_share_price is not None:
        price = float(current_share_price)

        def fv_at_growth(rate: float) -> float | None:
            return _fair_value(
                fcf0, [rate] * years, terminal_growth, wacc, net_debt, shares_outstanding
            )

        def fv_at_terminal_growth(tg: float) -> float | None:
            return _fair_value(fcf0, rates, tg, wacc, net_debt, shares_outstanding)

        result["implied"] = {
            "current_share_price": round(price, 2),
            "stage1_growth": _bisect_increasing(
                fv_at_growth, _STAGE1_GROWTH_BOUNDS[0], _STAGE1_GROWTH_BOUNDS[1], price
            ),
            "terminal_growth": _bisect_increasing(
                fv_at_terminal_growth, _TERMINAL_GROWTH_FLOOR, wacc - _WACC_EPSILON, price
            ),
        }

    return result


def main() -> None:
    """Read JSON params from stdin, write the DCF result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_dcf(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
