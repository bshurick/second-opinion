"""Dividend discount models: Gordon, two-stage, and H-model, with a sensitivity grid.

This script reads a JSON object from stdin, runs the requested dividend
discount model, and writes a JSON object to stdout. It is invoked as:

    python ddm.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "model": "gordon",            # "gordon" | "two_stage" | "h"
      "dividend0": 2.0,             # trailing annual dividend per share; >= 0
      "required_return": 0.09,      # cost of equity k (decimal); > 0
      "terminal_growth": 0.025,     # perpetuity growth gL; must be < required_return

      "growth_rate": 0.12,          # two_stage only: stage-1 annual growth
      "years": 5,                   # two_stage only: stage-1 length, integer 1..20

      "initial_growth": 0.15,       # h only: initial (short-run) growth gS
      "h_years": 5.0,              # h only: half-life of the fade in years; > 0

      "sensitivity": {              # optional; defaults shown
        "required_return_step": 0.005,
        "growth_step": 0.005,
        "steps": 2                  # grid spans base +/- steps
      }
    }

Models (value per share, D0 = dividend0, k = required_return, gL =
terminal_growth):

- gordon:  V = D0 * (1 + gL) / (k - gL)
- two_stage: stage-1 dividends grow at growth_rate for years, discounted
  at k; the terminal value is a YEAR-N Gordon value on D_N*(1+gL),
  discounted back N years (same convention as dcf.py).
- h (H-model): V = D0 * ((1 + gL) + H * (gS - gL)) / (k - gL), where
  gS = initial_growth and H = h_years is the half-life of the linear fade
  from gS to gL (a half-life of 5 fades over roughly a decade).

Output JSON contract (stdout)::

    {
      "model": ...,                       # echoed
      "fair_value_per_share": ...,        # 2dp
      "inputs_echo": { ... resolved inputs, including defaulted sensitivity ... },
      "sensitivity_grid": {
        "required_return_values": [...],      # rows, 4dp
        "terminal_growth_values": [...],      # cols, 4dp
        "fair_value_per_share": [[...], ...]  # rows=k, cols=gL; null where gL >= k
      }
    }

The grid re-runs the SAME model with the other inputs fixed, varying only
the required return (rows) and terminal growth (cols) — mirroring dcf.py's
conventions (null where terminal_growth >= required_return).

Validation errors (non-object input, unknown/missing model, missing
fields, negative dividend0, non-positive required_return, terminal_growth
>= required_return, two_stage years outside 1..20, non-positive h_years)
are reported as ``{"error": "..."}`` on stdout with exit code 2.
"""

from __future__ import annotations

import json
import sys

_DEFAULT_SENSITIVITY = {"required_return_step": 0.005, "growth_step": 0.005, "steps": 2}

_MODELS = ("gordon", "two_stage", "h")

_COMMON_REQUIRED_FIELDS = ("dividend0", "required_return", "terminal_growth")


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


def _model_value(
    model: str,
    dividend0: float,
    required_return: float,
    terminal_growth: float,
    growth_rate: float,
    years: int,
    initial_growth: float,
    h_years: float,
) -> float | None:
    """Value per share under ``model``, or None when terminal_growth >= required_return."""
    if terminal_growth >= required_return:
        return None
    if model == "gordon":
        return dividend0 * (1 + terminal_growth) / (required_return - terminal_growth)
    if model == "two_stage":
        pv_stage1 = 0.0
        dividend_t = dividend0
        for t in range(1, years + 1):
            dividend_t = dividend_t * (1 + growth_rate)
            pv_stage1 += dividend_t / (1 + required_return) ** t
        terminal_value = dividend_t * (1 + terminal_growth) / (required_return - terminal_growth)
        return pv_stage1 + terminal_value / (1 + required_return) ** years
    # h model
    return (
        dividend0
        * ((1 + terminal_growth) + h_years * (initial_growth - terminal_growth))
        / (required_return - terminal_growth)
    )


def run_ddm(params: dict) -> dict:
    """Run the dividend discount model described by ``params`` and return the
    result dict.

    Raises ValueError (or TypeError for non-numeric fields) on invalid input;
    callers that need the stdin/stdout error contract should use main().
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")

    model = params.get("model")
    if model not in _MODELS:
        raise ValueError(f"model must be one of: {', '.join(_MODELS)}")

    missing = [field for field in _COMMON_REQUIRED_FIELDS if field not in params]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    dividend0 = float(params["dividend0"])
    required_return = float(params["required_return"])
    terminal_growth = float(params["terminal_growth"])

    if dividend0 < 0:
        raise ValueError("dividend0 must be non-negative")
    if required_return <= 0:
        raise ValueError("required_return must be positive")
    if terminal_growth >= required_return:
        raise ValueError("terminal_growth must be less than required_return")

    growth_rate = 0.0
    years = 0
    initial_growth = 0.0
    h_years = 0.0
    if model == "two_stage":
        if "growth_rate" not in params:
            raise ValueError(
                "missing required field(s): growth_rate (two_stage needs a stage-1 rate)"
            )
        growth_rate = float(params["growth_rate"])
        if "years" not in params:
            raise ValueError("missing required field(s): years (two_stage needs a stage-1 length)")
        years = _coerce_int(params["years"], "years")
        if years <= 0 or years > 20:
            raise ValueError("years must be between 1 and 20")
    elif model == "h":
        if "initial_growth" not in params:
            raise ValueError(
                "missing required field(s): initial_growth (h model needs the short-run rate)"
            )
        initial_growth = float(params["initial_growth"])
        if "h_years" not in params:
            raise ValueError("missing required field(s): h_years (h model needs a fade half-life)")
        h_years = float(params["h_years"])
        if h_years <= 0:
            raise ValueError("h_years must be positive")

    sensitivity_in = params.get("sensitivity", {})
    if not isinstance(sensitivity_in, dict):
        raise ValueError("sensitivity must be an object")
    sensitivity = {**_DEFAULT_SENSITIVITY, **sensitivity_in}
    rr_step = float(sensitivity["required_return_step"])
    growth_step = float(sensitivity["growth_step"])
    steps = _coerce_int(sensitivity["steps"], "sensitivity.steps")
    if steps < 0:
        raise ValueError("sensitivity.steps must be a non-negative integer")

    fair_value = _model_value(
        model,
        dividend0,
        required_return,
        terminal_growth,
        growth_rate,
        years,
        initial_growth,
        h_years,
    )
    assert fair_value is not None  # terminal_growth < required_return validated above

    rr_values = [required_return + rr_step * i for i in range(-steps, steps + 1)]
    tg_values = [terminal_growth + growth_step * j for j in range(-steps, steps + 1)]

    grid: list[list[float | None]] = []
    for k in rr_values:
        row: list[float | None] = []
        for tg in tg_values:
            cell = _model_value(
                model, dividend0, k, tg, growth_rate, years, initial_growth, h_years
            )
            row.append(None if cell is None else round(cell, 2))
        grid.append(row)

    inputs_echo: dict = {
        "model": model,
        "dividend0": dividend0,
        "required_return": required_return,
        "terminal_growth": terminal_growth,
        "sensitivity": {
            "required_return_step": rr_step,
            "growth_step": growth_step,
            "steps": steps,
        },
    }
    if model == "two_stage":
        inputs_echo["growth_rate"] = growth_rate
        inputs_echo["years"] = years
    elif model == "h":
        inputs_echo["initial_growth"] = initial_growth
        inputs_echo["h_years"] = h_years

    return {
        "model": model,
        "fair_value_per_share": round(fair_value, 2),
        "inputs_echo": inputs_echo,
        "sensitivity_grid": {
            "required_return_values": [round(k, 4) for k in rr_values],
            "terminal_growth_values": [round(tg, 4) for tg in tg_values],
            "fair_value_per_share": grid,
        },
    }


def main() -> None:
    """Read JSON params from stdin, write the DDM result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_ddm(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
