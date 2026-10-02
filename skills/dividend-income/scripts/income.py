"""Dividend income analysis for a set of holdings: forward income, yields,
trailing twelve months, growth, a monthly schedule, and flags.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python income.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``). Output is deterministic (fixed sort orders).

Input JSON contract (stdin)::

    {
      "as_of": "2026-09-04",                # optional, default today (local date)
      "positions": [                        # required unless "accounts" given
        {"symbol": "AAPL", "units": 20, "price": 100.0,
         "average_purchase_price": 80.0}    # price/avg optional
      ],
      "accounts": [ ...summary.py-style accounts with raw SnapTrade
                    positions; aggregated by symbol... ],   # alternative
      "dividends": {                        # per-share cash dividends by EX-DATE
        "AAPL": [{"date": "2026-08-10", "dividend": 0.26}, ...],
        "VTI":  {"dividends": [...]}        # the get_dividend_history / dividends.py
      },                                    #   envelope is accepted as-is
      "fundamentals": {                     # optional
        "AAPL": {"payout_ratio": 0.15, "eps_ttm": 6.5}
      }
    }

Output JSON contract (stdout)::

    {
      "as_of": "YYYY-MM-DD",
      "totals": {annual_income, ttm_income, market_value, portfolio_yield,
                 cost_basis, yield_on_cost, payer_count, position_count,
                 top_payer, top_payer_share},
      "positions": [{symbol, units, price, market_value, cost_basis,
                     frequency, payments_per_year, last_dividend, last_ex_date,
                     next_ex_date_est, next_ex_amount_est, forward_rate, forward_yield,
                     yield_on_cost, annual_income, income_share,
                     ttm_per_share, ttm_income, prior_ttm_per_share,
                     ttm_change, growth_1y, growth_3y, growth_5y,
                     special_ttm, payout_ratio,
                     safety | null}],   # annual_income desc, symbol asc
      "monthly": [{month: "YYYY-MM", income, payers: [...]}],   # next 12 months
      "flags": [{code, message}]     # DIVIDEND_CUT, HIGH_PAYOUT, NEGATIVE_EARNINGS,
                                     # INCOME_CONCENTRATED, NO_DIVIDENDS, MISSING_HISTORY
    }

Method:
- Special dividends are payments above 1.75x the median payment; they count
  in trailing sums (``special_ttm``) but not in the forward rate or frequency.
- Frequency is the median gap between the last six regular ex-dates:
  <=45 days monthly (12/yr), <=135 quarterly (4), <=250 semiannual (2), else
  annual (1). Fewer than two regular payments -> "irregular", and the forward
  rate is the trailing 12-month sum instead of last payment x payments/yr.
- ``next_ex_date_est`` is the last regular ex-date plus 30/91/182/365 days;
  ``next_ex_amount_est`` is the last regular dividend x units (the same forward
  payment the monthly schedule places), null when no next date is estimated.
- ``ttm`` covers ex-dates in (as_of-365d, as_of]; ``prior_ttm`` the year before.
- Growth uses regular dividends summed per full calendar year: growth_ny =
  (sum[Y-1] / sum[Y-1-n])^(1/n) - 1 where Y is the as_of year.
- The monthly schedule places one forward payment (last regular dividend x
  units) in the calendar month of each of the last payments_per_year regular
  ex-dates; irregular payers use their actual last-12-month payments.
- Payout ratio is taken from fundamentals, else forward_rate / eps_ttm when
  eps_ttm > 0. Money 2 dp, per-share amounts and ratios 4 dp.
- ``safety`` (heuristic screen, NOT a rating) is a per-payer block
  {score, consecutive_years, cuts_in_window, payment_cv, payout_ratio, flags}
  built only from the dividend history already supplied; null when there is no
  dividend history. ``consecutive_years`` counts calendar years with at least
  one regular payment ending at the year before ``as_of`` (or the last year
  with payments), counting back to the first gap. ``cuts_in_window`` counts
  year-over-year declines in the regular sums per full calendar year up to
  ``as_of``'s previous year (the incomplete current year is never a cut;
  gap years are penalized by the streak, not double-counted as cuts).
  ``payment_cv`` is the population stdev/mean of the most recent 12 regular
  payments (null below 4). ``payout_ratio`` passes through the computed
  payout. The score starts at 10 and subtracts 2.5 per cut year (capped 5),
  2 when the streak is under 5 years (stacking to 4 under 2), 1.5 when
  payment_cv > 0.15 (3 when > 0.30), and 2 when payout_ratio > 0.8 (3.5 when
  > 1.0, payout deduction capped 3.5), clamped to [0, 10] at 1 dp.
  ``flags``: DIVIDEND_CUT (any cut year), DIVIDEND_UNSTABLE (payment_cv
  > 0.15), HIGH_PAYOUT (payout_ratio > 0.8).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from statistics import median, pstdev

_SPECIAL_MULTIPLE = 1.75
_FREQ = [
    (45, "monthly", 12, 30),
    (135, "quarterly", 4, 91),
    (250, "semiannual", 2, 182),
    (10**9, "annual", 1, 365),
]
_CUT_THRESHOLD = -0.05
_HIGH_PAYOUT = 0.80
_CONCENTRATION = 0.50
_CV_STABLE = 0.15
_CV_UNSTABLE = 0.30
_PAYOUT_EXTREME = 1.00
_CUT_DEDUCTION = 2.5
_CUT_CAP = 5.0
_STREAK_DEDUCTION = 2.0
_STREAK_STACK = 4.0
_CV_LIGHT = 1.5
_CV_HEAVY = 3.0
_PAYOUT_HIGH_DEDUCTION = 2.0
_PAYOUT_EXTREME_DEDUCTION = 3.5
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _money(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _ratio(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _number(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _parse_date(raw: object, field: str) -> date:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def _symbol(position: dict) -> str:
    sym = position.get("symbol")
    for _ in range(2):  # SnapTrade nests symbol.symbol.symbol
        if isinstance(sym, dict):
            sym = sym.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise ValueError("each position requires a symbol")
    return sym.strip().upper()


def _flatten(params: dict) -> list[dict]:
    """Positions aggregated by symbol from either ``positions`` or ``accounts``."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    raw: list[dict] = []
    if isinstance(params.get("accounts"), list):
        for a in params["accounts"]:
            if isinstance(a, dict):
                raw.extend(p for p in (a.get("positions") or []) if isinstance(p, dict))
    if isinstance(params.get("positions"), list):
        raw.extend(p for p in params["positions"] if isinstance(p, dict))
    if not raw:
        raise ValueError("at least one position is required")
    book: dict[str, dict] = {}
    for p in raw:
        sym = _symbol(p)
        units = _number(p.get("units"), "units") or 0.0
        if units < 0:
            raise ValueError("units must not be negative")
        price = _number(p.get("price"), "price")
        avg = _number(p.get("average_purchase_price"), "average_purchase_price")
        row = book.setdefault(
            sym, {"symbol": sym, "units": 0.0, "price": None, "cost": 0.0, "has_cost": True}
        )
        row["units"] += units
        row["price"] = row["price"] if row["price"] is not None else price
        if avg is None:
            row["has_cost"] = False
        else:
            row["cost"] += units * avg
    return list(book.values())


def _history(entry: object) -> list[tuple[date, float]]:
    if isinstance(entry, dict):
        entry = entry.get("dividends")
    if not isinstance(entry, list):
        raise ValueError("dividend history must be a list")
    out = []
    for d in entry:
        if not isinstance(d, dict) or "date" not in d or "dividend" not in d:
            raise ValueError("each dividend requires 'date' and 'dividend'")
        amount = _number(d["dividend"], "dividend")
        if amount is None or amount <= 0:
            continue
        out.append((_parse_date(d["date"], "dividend date"), amount))
    return sorted(out)


def _split_specials(
    hist: list[tuple[date, float]],
) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    if len(hist) < 3:
        return hist, []
    med = median(a for _, a in hist)
    regular = [h for h in hist if h[1] <= _SPECIAL_MULTIPLE * med]
    special = [h for h in hist if h[1] > _SPECIAL_MULTIPLE * med]
    return regular, special


def _frequency(regular: list[tuple[date, float]]) -> tuple[str | None, int | None, int | None]:
    if len(regular) < 2:
        return ("irregular", None, None) if regular else (None, None, None)
    recent = regular[-6:]
    gaps = [(b[0] - a[0]).days for a, b in zip(recent, recent[1:], strict=False)]
    gap = median(gaps)
    for limit, name, per_year, step in _FREQ:
        if gap <= limit:
            return name, per_year, step
    return "annual", 1, 365  # unreachable, keeps type checkers calm


def _growth(regular: list[tuple[date, float]], year: int, n: int) -> float | None:
    sums: dict[int, float] = {}
    for d, a in regular:
        sums[d.year] = sums.get(d.year, 0.0) + a
    last, base = sums.get(year - 1), sums.get(year - 1 - n)
    if not last or not base:
        return None
    return (last / base) ** (1.0 / n) - 1


def _safety(regular: list[tuple[date, float]], as_of: date, payout: float | None) -> dict:
    """Dividend-safety screen for one payer: 0-10 score plus components.

    Heuristic, not a rating. See the module docstring for the formula.
    """
    sums: dict[int, float] = {}
    for d, a in regular:
        sums[d.year] = sums.get(d.year, 0.0) + a
    consecutive = 0
    if sums:
        y = min(as_of.year - 1, max(sums))
        while y in sums:
            consecutive += 1
            y -= 1
    full_year = as_of.year - 1  # the current year is incomplete: never a cut
    cuts = sum(1 for y in sums if y - 1 in sums and y <= full_year and sums[y] < sums[y - 1])
    recent = [a for _, a in regular[-12:]]
    cv = None
    if len(recent) >= 4:
        cv = pstdev(recent) / (sum(recent) / len(recent))
    deduction = min(_CUT_DEDUCTION * cuts, _CUT_CAP)
    if consecutive < 2:
        deduction += _STREAK_STACK
    elif consecutive < 5:
        deduction += _STREAK_DEDUCTION
    if cv is not None:
        if cv > _CV_UNSTABLE:
            deduction += _CV_HEAVY
        elif cv > _CV_STABLE:
            deduction += _CV_LIGHT
    if payout is not None:
        if payout > _PAYOUT_EXTREME:
            deduction += _PAYOUT_EXTREME_DEDUCTION
        elif payout > _HIGH_PAYOUT:
            deduction += _PAYOUT_HIGH_DEDUCTION
    score = round(max(0.0, min(10.0, 10.0 - deduction)), 1)
    flags: list[str] = []
    if cuts:
        flags.append("DIVIDEND_CUT")
    if cv is not None and cv > _CV_STABLE:
        flags.append("DIVIDEND_UNSTABLE")
    if payout is not None and payout > _HIGH_PAYOUT:
        flags.append("HIGH_PAYOUT")
    return {
        "score": score,
        "consecutive_years": consecutive,
        "cuts_in_window": cuts,
        "payment_cv": _ratio(cv),
        "payout_ratio": _ratio(payout),
        "flags": flags,
    }


def _month_labels(as_of: date) -> list[str]:
    labels = []
    y, m = as_of.year, as_of.month
    for _ in range(12):
        labels.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return labels


def run_income(params: dict) -> dict:
    """Build the income report described by ``params``; raises ValueError/TypeError on bad input."""
    positions = _flatten(params)
    as_of = (
        _parse_date(params["as_of"], "as_of") if params.get("as_of") is not None else date.today()
    )
    dividends = params.get("dividends") or {}
    fundamentals = params.get("fundamentals") or {}
    if not isinstance(dividends, dict) or not isinstance(fundamentals, dict):
        raise ValueError("dividends and fundamentals must be objects")
    dividends = {str(k).upper(): v for k, v in dividends.items()}
    fundamentals = {str(k).upper(): v for k, v in fundamentals.items()}

    ttm_start, prior_start = as_of - timedelta(days=365), as_of - timedelta(days=730)
    labels = _month_labels(as_of)
    schedule: dict[str, dict] = {m: {"income": 0.0, "payers": []} for m in labels}
    by_month_of_year = {int(m[5:]): m for m in labels}

    rows: list[dict] = []
    cut: list[tuple[str, float]] = []
    high_payout: list[tuple[str, float]] = []
    negative_eps: list[str] = []
    no_dividends: list[str] = []
    missing_history: list[str] = []

    for pos in positions:
        sym = pos["symbol"]
        mv = pos["units"] * pos["price"] if pos["price"] is not None else None
        cost = pos["cost"] if pos["has_cost"] else None
        row: dict = {
            "symbol": sym,
            "units": _ratio(pos["units"]),
            "price": _money(pos["price"]),
            "market_value": _money(mv),
            "cost_basis": _money(cost),
            "frequency": None,
            "payments_per_year": None,
            "last_dividend": None,
            "last_ex_date": None,
            "next_ex_date_est": None,
            "next_ex_amount_est": None,
            "forward_rate": None,
            "forward_yield": None,
            "yield_on_cost": None,
            "annual_income": None,
            "income_share": None,
            "ttm_per_share": None,
            "ttm_income": None,
            "prior_ttm_per_share": None,
            "ttm_change": None,
            "growth_1y": None,
            "growth_3y": None,
            "growth_5y": None,
            "special_ttm": None,
            "payout_ratio": None,
            "safety": None,
        }
        if sym not in dividends:
            missing_history.append(sym)
            rows.append(row)
            continue
        hist = _history(dividends[sym])
        regular, special = _split_specials(hist)
        ttm = sum(a for d, a in hist if ttm_start < d <= as_of)
        prior = sum(a for d, a in hist if prior_start < d <= ttm_start)
        special_ttm = sum(a for d, a in special if ttm_start < d <= as_of)
        freq, per_year, step = _frequency(regular)
        if not hist:
            no_dividends.append(sym)
            forward = 0.0
        elif per_year is None:
            forward = ttm
        else:
            forward = regular[-1][1] * per_year
        last = regular[-1] if regular else (hist[-1] if hist else None)
        fund = fundamentals.get(sym) if isinstance(fundamentals.get(sym), dict) else {}
        payout = _number(fund.get("payout_ratio"), "payout_ratio")
        eps = _number(fund.get("eps_ttm"), "eps_ttm")
        if payout is None and eps is not None and forward > 0:
            if eps > 0:
                payout = forward / eps
            else:
                negative_eps.append(sym)
        if payout is not None and payout > _HIGH_PAYOUT:
            high_payout.append((sym, payout))
        change = (ttm / prior - 1) if prior > 0 else None
        if change is not None and change < _CUT_THRESHOLD:
            cut.append((sym, change))

        # monthly schedule
        if per_year is not None and regular:
            for d, _ in regular[-per_year:]:
                label = by_month_of_year[d.month]
                schedule[label]["income"] += regular[-1][1] * pos["units"]
                schedule[label]["payers"].append(sym)
        else:
            for d, a in hist:
                if ttm_start < d <= as_of:
                    label = by_month_of_year[d.month]
                    schedule[label]["income"] += a * pos["units"]
                    schedule[label]["payers"].append(sym)

        row.update(
            {
                "frequency": freq,
                "payments_per_year": per_year,
                "last_dividend": _ratio(last[1]) if last else None,
                "last_ex_date": last[0].isoformat() if last else None,
                "next_ex_date_est": (regular[-1][0] + timedelta(days=step)).isoformat()
                if step and regular
                else None,
                "next_ex_amount_est": (
                    _money(regular[-1][1] * pos["units"]) if step and regular else None
                ),
                "forward_rate": _ratio(forward),
                "forward_yield": _ratio(forward / pos["price"]) if pos["price"] else None,
                "yield_on_cost": _ratio(forward * pos["units"] / cost) if cost else None,
                "annual_income": _money(forward * pos["units"]),
                "ttm_per_share": _ratio(ttm),
                "ttm_income": _money(ttm * pos["units"]),
                "prior_ttm_per_share": _ratio(prior),
                "ttm_change": _ratio(change),
                "growth_1y": _ratio(_growth(regular, as_of.year, 1)),
                "growth_3y": _ratio(_growth(regular, as_of.year, 3)),
                "growth_5y": _ratio(_growth(regular, as_of.year, 5)),
                "special_ttm": _ratio(special_ttm),
                "payout_ratio": _ratio(payout),
                "_forward_income": forward * pos["units"],
            }
        )
        row["safety"] = _safety(regular, as_of, payout) if hist else None
        rows.append(row)

    # --- totals ----------------------------------------------------------------------
    payers = [r for r in rows if (r.get("_forward_income") or 0.0) > 0]
    annual_income = sum(r["_forward_income"] for r in payers)
    ttm_income = sum((r["ttm_income"] or 0.0) for r in rows)
    market_value = sum(p["units"] * p["price"] for p in positions if p["price"] is not None)
    payer_cost_known = payers and all(r["cost_basis"] is not None for r in payers)
    cost_basis = sum(r["cost_basis"] for r in payers) if payer_cost_known else None
    top = max(payers, key=lambda r: (r["_forward_income"], r["symbol"])) if payers else None
    for r in rows:
        if r.get("_forward_income") is not None:
            r["income_share"] = (
                _ratio(r["_forward_income"] / annual_income) if annual_income > 0 else 0.0
            )
        r.pop("_forward_income", None)
    rows.sort(key=lambda r: (-(r["annual_income"] or 0.0), r["symbol"]))
    totals = {
        "annual_income": _money(annual_income),
        "ttm_income": _money(ttm_income),
        "market_value": _money(market_value),
        "portfolio_yield": _ratio(annual_income / market_value) if market_value > 0 else None,
        "cost_basis": _money(cost_basis),
        "yield_on_cost": _ratio(annual_income / cost_basis) if cost_basis else None,
        "payer_count": len(payers),
        "position_count": len(rows),
        "top_payer": top["symbol"] if top else None,
        "top_payer_share": _ratio(top["income_share"]) if top else None,
    }

    monthly = [
        {
            "month": m,
            "income": _money(schedule[m]["income"]),
            "payers": sorted(set(schedule[m]["payers"])),
        }
        for m in labels
    ]

    # --- flags -----------------------------------------------------------------------
    flags: list[dict] = []
    if cut:
        detail = ", ".join(f"{s} ({round(c * 100, 1)}%)" for s, c in sorted(cut))
        flags.append(
            {"code": "DIVIDEND_CUT", "message": f"trailing 12-month dividends fell for: {detail}"}
        )
    if high_payout:
        detail = ", ".join(f"{s} ({round(p * 100, 1)}%)" for s, p in sorted(high_payout))
        flags.append(
            {
                "code": "HIGH_PAYOUT",
                "message": f"payout ratio above {int(_HIGH_PAYOUT * 100)}% for: {detail}",
            }
        )
    if negative_eps:
        neg = ", ".join(sorted(negative_eps))
        flags.append(
            {
                "code": "NEGATIVE_EARNINGS",
                "message": "dividend paid despite negative earnings: " + neg,
            }
        )
    if top and len(payers) > 1 and totals["top_payer_share"] > _CONCENTRATION:
        share = round(totals["top_payer_share"] * 100, 1)
        limit = int(_CONCENTRATION * 100)
        flags.append(
            {
                "code": "INCOME_CONCENTRATED",
                "message": f"{top['symbol']} pays {share}% of projected income (above {limit}%)",
            }
        )
    if no_dividends:
        flags.append(
            {
                "code": "NO_DIVIDENDS",
                "message": f"no dividends in history for: {', '.join(sorted(no_dividends))}",
            }
        )
    if missing_history:
        missing = ", ".join(sorted(missing_history))
        flags.append(
            {
                "code": "MISSING_HISTORY",
                "message": "no dividend history supplied for: " + missing,
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "totals": totals,
        "positions": rows,
        "monthly": monthly,
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the income report (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_income(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
