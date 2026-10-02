"""Options math: Black-Scholes pricing and greeks, implied volatility,
strategy payoff diagrams, expected move, option-chain summary, and
historical volatility.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python options.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).
The ``action`` field selects the calculation:

``greeks`` -- one contract::

    {"action": "greeks", "spot": 100, "strike": 100, "type": "call"|"put",
     "days": 30 | "expiry": "YYYY-MM-DD" (+ optional "as_of"),
     "iv": 0.2 | "price": 3.1 (implied vol is solved when only price is given),
     "rate": 0.04 (default), "dividend_yield": 0.0 (default),
     "ex_dividend_date": "YYYY-MM-DD" (optional; feeds the assignment screen)}
    -> {price, iv, iv_source: "given"|"solved", delta, gamma, theta (per day),
        vega (per 1 vol point), rho (per 1 rate point), prob_itm, breakeven, days,
        early_assignment: {plausible, deep_itm, delta, time_value, exercise_gain,
        reasons}}

``payoff`` -- P&L at expiry for a set of legs::

    {"action": "payoff", "spot": 100,
     "legs": [{"type": "call"|"put", "side": "long"|"short", "strike": 105,
               "premium": 2.0, "qty": 1},            # qty = contracts (x100)
              {"type": "stock", "side": "long", "qty": 100, "price": 100}],
     "iv": 0.2, "days": 30, "rate": 0.04,           # optional -> prob_profit
     "range": [50, 150], "step": 1}                 # optional grid
    -> {strategy, net_premium (credit > 0, debit < 0), collateral,
        breakevens, max_profit, max_loss, unlimited_profit, unlimited_loss,
        prob_profit, expected_move_1sd, grid: [{price, pnl}]}

``expected_move``::

    {"action": "expected_move", "spot": 100, "iv": 0.2, "days": 30,
     "straddle_price": 6.5}                         # optional
    -> {move_1sd, move_pct_1sd, range_1sd, range_2sd, move_from_straddle}

``chain`` -- summarize one expiry's chain (yfinance / get_option_chain shape)::

    {"action": "chain", "spot": 100, "expiry": "YYYY-MM-DD", "as_of": ...,
     "rate": 0.04, "dividend_yield": 0.0 (default), "around": 10,
     "ex_dividend_date": "YYYY-MM-DD" (optional; feeds the assignment screen),
     "calls": [{strike, bid, ask, last, volume, open_interest, implied_volatility}],
     "puts": [...], "history": [{date, close}]}     # history optional -> hv
    -> {days, atm_strike, atm_iv, expected_move_1sd, expected_move_pct,
        put_call_oi_ratio, put_call_volume_ratio, max_pain, top_open_interest,
        skew: {otm_put_strike, otm_put_iv, otm_call_strike, otm_call_iv, put_minus_call},
        dividend_yield, ex_dividend_days,
        assignment_candidates: [{type, strike, mid, time_value, exercise_gain,
        ex_dividend_days, reasons}] (deep-ITM contracts where early exercise is
        plausible; up to six, smallest time value first),
        strikes: [{strike, call: {bid, ask, mid, last, volume, open_interest,
                  iv, delta, spread_pct}, put: {...}}],
        hv_30, hv_90, iv_hv_ratio}

``term_structure`` -- per-expiry ATM stats across several expiries::

    {"action": "term_structure", "spot": 100, "as_of": "YYYY-MM-DD",
     "expiries": [{"expiry": "YYYY-MM-DD",
                   "calls": [{...same shape as chain...}], "puts": [...]}, ...]}
    -> {rows: [{expiry, days, atm_strike, atm_iv, atm_straddle, iv_move_pct,
          straddle_move_pct, put_skew}], front: {expiry, days, atm_iv,
          atm_straddle, put_skew}, back: {same shape}, iv_slope_30d,
        iv_term_shape: "rising"|"falling"|"flat", skew_slope_30d}

``hv``::

    {"action": "hv", "history": [{date, close}]} -> {hv_30, hv_90, observations}

Method: European Black-Scholes-Merton with continuous dividend yield;
theta is per calendar day, vega per one volatility point, rho per one
rate point; prob_itm is the risk-neutral N(d2) (calls) / N(-d2) (puts).
Implied volatility is bisected on [0.0001, 5]. Payoff breakevens are the
zero crossings of the expiry P&L; unlimited profit/loss means the P&L
slope above the highest strike is positive/negative (downside is always
bounded by price zero). prob_profit is the risk-neutral lognormal
probability mass of the profitable price regions, so it needs iv and days.
Expected move is spot x iv x sqrt(days/365); the straddle rule of thumb is
0.85 x the ATM straddle price. Max pain is the expiry price that minimizes
the total intrinsic value paid to option holders, weighted by open interest.
Skew compares the IV of the put nearest 90% of spot with the call nearest
110% of spot. hv_N is the sample standard deviation of the last N daily log
returns x sqrt(252), computed once at least N/2 returns exist. Ratios are
rounded to 4 dp, money to 4 dp for per-share values and 2 dp for P&L.

Early assignment is an American approximation, not a boundary solve: a
contract is flagged when it is deep ITM (|delta| >= 0.90) and exercising
now plausibly beats holding -- for calls the estimated next dividend (one
quarterly payment, dividend_yield x spot / 4, when the ex-dividend date
falls inside the option's life, else the yield accrued over the remaining
life) exceeds the remaining time value, for puts the interest on the
strike (rate x strike x t) does; days to the ex-dividend date are echoed
while it is inside the life. The term-structure action reuses the chain
skew and the 0.85 straddle rule: iv_move_pct is ATM IV x sqrt(days/365),
straddle_move_pct is 0.85 x straddle / spot, and iv_slope_30d is the ATM
IV change per 30 days between the first and last expiry (the shape is
flat within 0.005 per 30 days).
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from statistics import stdev

_ACTIONS = ("chain", "expected_move", "greeks", "hv", "payoff", "term_structure")
_MULT = 100
_IV_LO, _IV_HI = 1e-4, 5.0


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _num(v: object, field: str, required: bool = False) -> float | None:
    if v is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    try:
        return float(v)
    except ValueError as exc:
        raise TypeError(f"{field} must be numeric") from exc


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _days(params: dict) -> int:
    if params.get("days") is not None:
        days = _num(params["days"], "days")
    elif params.get("expiry"):
        as_of = date.fromisoformat(str(params["as_of"])) if params.get("as_of") else date.today()
        days = (date.fromisoformat(str(params["expiry"])) - as_of).days
    else:
        raise ValueError("days or expiry is required")
    if days is None or days <= 0:
        raise ValueError("days must be positive")
    return int(days)


def bs(spot: float, strike: float, t: float, r: float, q: float, iv: float, kind: str) -> dict:
    """Black-Scholes-Merton price and greeks (per share)."""
    sq = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * iv * iv) * t) / (iv * sq)
    d2 = d1 - iv * sq
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    if kind == "call":
        price = spot * disc_q * _ncdf(d1) - strike * disc_r * _ncdf(d2)
        delta = disc_q * _ncdf(d1)
        theta = (
            -spot * disc_q * _npdf(d1) * iv / (2 * sq)
            - r * strike * disc_r * _ncdf(d2)
            + q * spot * disc_q * _ncdf(d1)
        )
        rho = strike * t * disc_r * _ncdf(d2)
        prob_itm = _ncdf(d2)
    else:
        price = strike * disc_r * _ncdf(-d2) - spot * disc_q * _ncdf(-d1)
        delta = disc_q * (_ncdf(d1) - 1)
        theta = (
            -spot * disc_q * _npdf(d1) * iv / (2 * sq)
            + r * strike * disc_r * _ncdf(-d2)
            - q * spot * disc_q * _ncdf(-d1)
        )
        rho = -strike * t * disc_r * _ncdf(-d2)
        prob_itm = _ncdf(-d2)
    gamma = disc_q * _npdf(d1) / (spot * iv * sq)
    vega = spot * disc_q * _npdf(d1) * sq
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta / 365.0,
        "vega": vega / 100.0,
        "rho": rho / 100.0,
        "prob_itm": prob_itm,
        "d2": d2,
    }


def implied_vol(
    price: float, spot: float, strike: float, t: float, r: float, q: float, kind: str
) -> float:
    lo, hi = _IV_LO, _IV_HI
    f_lo = bs(spot, strike, t, r, q, lo, kind)["price"] - price
    f_hi = bs(spot, strike, t, r, q, hi, kind)["price"] - price
    if f_lo > 0 or f_hi < 0:
        raise ValueError(
            "no implied volatility reproduces price (below intrinsic or above the 500% vol bound)"
        )
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = bs(spot, strike, t, r, q, mid, kind)["price"] - price
        if abs(f_mid) < 1e-10:
            return mid
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _early_assignment(
    kind: str,
    spot: float,
    strike: float,
    days: int,
    rate: float,
    q: float,
    iv: float,
    price: float,
    ex_div_days: int | None,
) -> dict:
    """American early-exercise screen (approximation; see the module docstring)."""
    t = days / 365.0
    intrinsic = max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    time_value = max(price - intrinsic, 0.0)
    delta = float(bs(spot, strike, t, rate, q, iv, kind)["delta"])
    deep = abs(delta) >= 0.90
    reasons: list[str] = []
    if kind == "call":
        if ex_div_days is not None and 0 <= ex_div_days < days:
            gain = q * spot / 4.0  # one quarterly payment from the annual yield
        else:
            gain = q * spot * t
        if deep and gain > time_value:
            reasons.append(f"deep ITM (delta {_r4(delta)})")
            reasons.append(
                f"estimated dividend {_r4(gain)} exceeds remaining time value {_r4(time_value)}"
            )
            if ex_div_days is not None and 0 <= ex_div_days < days:
                reasons.append(f"ex-dividend in {ex_div_days} days")
    else:
        gain = rate * strike * t
        if deep and gain > time_value:
            reasons.append(f"deep ITM (delta {_r4(delta)})")
            reasons.append(
                f"interest on strike {_r4(gain)} exceeds remaining time value {_r4(time_value)}"
            )
    return {
        "plausible": bool(reasons),
        "deep_itm": deep,
        "delta": _r4(delta),
        "time_value": _r4(time_value),
        "exercise_gain": _r4(gain),
        "reasons": reasons,
    }


# --- greeks ------------------------------------------------------------------------


def _greeks(params: dict) -> dict:
    kind = str(params.get("type") or "").lower()
    if kind not in ("call", "put"):
        raise ValueError("type must be 'call' or 'put'")
    spot = _num(params.get("spot"), "spot", True)
    strike = _num(params.get("strike"), "strike", True)
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    days = _days(params)
    t = days / 365.0
    r = _num(params.get("rate"), "rate") if params.get("rate") is not None else 0.04
    q = _num(params.get("dividend_yield"), "dividend_yield") or 0.0
    iv = _num(params.get("iv"), "iv")
    price = _num(params.get("price"), "price")
    if iv is None and price is None:
        raise ValueError("either iv or price is required")
    if iv is not None:
        if iv <= 0:
            raise ValueError("iv must be positive")
        source = "given"
    else:
        iv = implied_vol(price, spot, strike, t, r, q, kind)
        source = "solved"
    g = bs(spot, strike, t, r, q, iv, kind)
    breakeven = strike + g["price"] if kind == "call" else strike - g["price"]
    ex_div_days = None
    if params.get("ex_dividend_date"):
        as_of = date.fromisoformat(str(params["as_of"])) if params.get("as_of") else date.today()
        ex_div_days = (date.fromisoformat(str(params["ex_dividend_date"])) - as_of).days
    return {
        "type": kind,
        "spot": spot,
        "strike": strike,
        "days": days,
        "rate": r,
        "dividend_yield": q,
        "iv": _r4(iv),
        "iv_source": source,
        "price": _r4(g["price"]),
        "delta": _r4(g["delta"]),
        "gamma": _r4(g["gamma"]),
        "theta": _r4(g["theta"]),
        "vega": _r4(g["vega"]),
        "rho": _r4(g["rho"]),
        "prob_itm": _r4(g["prob_itm"]),
        "breakeven": _r4(breakeven),
        "early_assignment": _early_assignment(
            kind, spot, strike, days, r, q, iv, g["price"], ex_div_days
        ),
    }


# --- payoff --------------------------------------------------------------------------


def _legs(params: dict) -> list[dict]:
    legs = params.get("legs")
    if not isinstance(legs, list) or not legs:
        raise ValueError("at least one leg is required")
    out = []
    for leg in legs:
        if not isinstance(leg, dict):
            raise ValueError("each leg must be an object")
        kind = str(leg.get("type") or "").lower()
        side = str(leg.get("side") or "long").lower()
        if kind not in ("call", "put", "stock"):
            raise ValueError("leg type must be call, put, or stock")
        if side not in ("long", "short"):
            raise ValueError("leg side must be long or short")
        sign = 1.0 if side == "long" else -1.0
        if kind == "stock":
            qty = _num(leg.get("qty"), "qty") or 100.0
            price = _num(leg.get("price"), "price")
            if price is None:
                price = _num(params.get("spot"), "spot", True)
            out.append({"type": "stock", "side": side, "shares": sign * qty, "price": price})
        else:
            strike = _num(leg.get("strike"), "strike")
            premium = _num(leg.get("premium"), "premium")
            if strike is None or premium is None:
                raise ValueError("option legs require strike and premium")
            qty = _num(leg.get("qty"), "qty") or 1.0
            out.append(
                {
                    "type": kind,
                    "side": side,
                    "contracts": sign * qty,
                    "strike": strike,
                    "premium": premium,
                }
            )
    return out


def _pnl_at(legs: list[dict], s: float) -> float:
    total = 0.0
    for leg in legs:
        if leg["type"] == "stock":
            total += leg["shares"] * (s - leg["price"])
        else:
            intrinsic = (
                max(s - leg["strike"], 0.0)
                if leg["type"] == "call"
                else max(leg["strike"] - s, 0.0)
            )
            total += leg["contracts"] * _MULT * (intrinsic - leg["premium"])
    return total


def _strategy_name(legs: list[dict]) -> str:
    opts = [leg for leg in legs if leg["type"] != "stock"]
    stock = [leg for leg in legs if leg["type"] == "stock"]
    calls = [leg for leg in opts if leg["type"] == "call"]
    puts = [leg for leg in opts if leg["type"] == "put"]
    if stock and len(opts) == 1:
        if stock[0]["shares"] > 0 and calls and calls[0]["contracts"] < 0:
            return "covered call"
        if stock[0]["shares"] > 0 and puts and puts[0]["contracts"] > 0:
            return "protective put"
    if not stock and len(opts) == 1:
        leg = opts[0]
        if leg["type"] == "put" and leg["contracts"] < 0:
            return "short put (cash-secured if collateral is held)"
        if leg["type"] == "call" and leg["contracts"] < 0:
            return "short call (uncovered)"
        return f"long {leg['type']}"
    if not stock and len(opts) == 2:
        a, b = sorted(opts, key=lambda leg: leg["strike"])
        if len(calls) == 1 and len(puts) == 1 and a["strike"] == b["strike"]:
            return (
                "long straddle"
                if a["contracts"] > 0 and b["contracts"] > 0
                else "short straddle"
                if a["contracts"] < 0 and b["contracts"] < 0
                else "custom (2 legs)"
            )
        if len(calls) == 1 and len(puts) == 1 and puts[0]["strike"] < calls[0]["strike"]:
            both_long = a["contracts"] > 0 and b["contracts"] > 0
            both_short = a["contracts"] < 0 and b["contracts"] < 0
            return (
                "long strangle"
                if both_long
                else "short strangle"
                if both_short
                else "custom (2 legs)"
            )
        if len(calls) == 2:
            return (
                "bull call spread"
                if a["contracts"] > 0 and b["contracts"] < 0
                else "bear call spread"
                if a["contracts"] < 0 and b["contracts"] > 0
                else "custom (2 legs)"
            )
        if len(puts) == 2:
            return (
                "bear put spread"
                if b["contracts"] > 0 and a["contracts"] < 0
                else "bull put spread"
                if b["contracts"] < 0 and a["contracts"] > 0
                else "custom (2 legs)"
            )
    if not stock and len(opts) == 4 and len(calls) == 2 and len(puts) == 2:
        return "iron condor / iron butterfly"
    return f"custom ({len(legs)} legs)"


def _payoff(params: dict) -> dict:
    spot = _num(params.get("spot"), "spot", True)
    legs = _legs(params)
    strikes = sorted({leg["strike"] for leg in legs if leg["type"] != "stock"})
    lo, hi = (
        (params.get("range") or [None, None])[:2]
        if isinstance(params.get("range"), list)
        else (None, None)
    )
    lo = _num(lo, "range") if lo is not None else max(0.0, round(spot * 0.5, 2))
    hi = _num(hi, "range") if hi is not None else round(spot * 1.5, 2)
    step = _num(params.get("step"), "step") or max(round(spot * 0.01, 2), 0.01)
    points = set()
    x = lo
    while x <= hi + 1e-9:
        points.add(round(x, 4))
        x += step
    points.update(strikes)
    points.add(0.0)
    points.add(round(spot, 4))
    slope_hi = sum(leg["shares"] for leg in legs if leg["type"] == "stock") + sum(
        leg["contracts"] * _MULT for leg in legs if leg["type"] == "call"
    )
    unlimited_profit = slope_hi > 1e-9
    unlimited_loss = slope_hi < -1e-9

    # breakevens: exact zero crossings between consecutive kink points
    kinks = sorted(set([0.0, *strikes, hi * 4]))
    breakevens: list[float] = []
    for a, b in zip(kinks, kinks[1:], strict=False):
        pa, pb = _pnl_at(legs, a), _pnl_at(legs, b)
        if pa == 0 and a > 0:
            breakevens.append(a)
        if (pa < 0 < pb) or (pb < 0 < pa):
            breakevens.append(a + (b - a) * (-pa) / (pb - pa))
    breakevens = sorted({round(v, 4) for v in breakevens if v > 0 and v <= hi * 4})
    points.update(breakevens)
    grid = [{"price": round(p, 4), "pnl": _r2(_pnl_at(legs, p))} for p in sorted(points)]
    pnls = [_pnl_at(legs, p) for p in sorted(points)]
    net_premium = sum(
        -leg["contracts"] * _MULT * leg["premium"] for leg in legs if leg["type"] != "stock"
    )
    collateral = sum(
        -leg["contracts"] * _MULT * leg["strike"]
        for leg in legs
        if leg["type"] == "put" and leg["contracts"] < 0
    )

    prob_profit = expected_move = None
    iv, days = _num(params.get("iv"), "iv"), params.get("days")
    if iv and days:
        t = int(_num(days, "days")) / 365.0
        r = _num(params.get("rate"), "rate") if params.get("rate") is not None else 0.04
        q = _num(params.get("dividend_yield"), "dividend_yield") or 0.0
        expected_move = spot * iv * math.sqrt(t)

        def p_above(k: float) -> float:
            if k <= 0:
                return 1.0
            d2 = (math.log(spot / k) + (r - q - 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
            return _ncdf(d2)

        edges = [0.0, *breakevens, float("inf")]
        prob = 0.0
        for a, b in zip(edges, edges[1:], strict=False):
            probe = (a + b) / 2 if b != float("inf") else (a * 1.5 if a > 0 else spot * 3)
            if _pnl_at(legs, probe) > 0:
                prob += p_above(a) - (0.0 if b == float("inf") else p_above(b))
        prob_profit = prob

    return {
        "strategy": _strategy_name(legs),
        "spot": spot,
        "legs": len(legs),
        "net_premium": _r2(net_premium),
        "collateral": _r2(collateral) if collateral else None,
        "breakevens": breakevens,
        "max_profit": None if unlimited_profit else _r2(max(pnls)),
        "max_loss": None if unlimited_loss else _r2(min(pnls)),
        "unlimited_profit": unlimited_profit,
        "unlimited_loss": unlimited_loss,
        "prob_profit": _r4(prob_profit),
        "expected_move_1sd": _r4(expected_move),
        "grid": grid,
    }


# --- expected move -----------------------------------------------------------------


def _expected_move(params: dict) -> dict:
    spot = _num(params.get("spot"), "spot", True)
    iv = _num(params.get("iv"), "iv", True)
    days = _days(params)
    move = spot * iv * math.sqrt(days / 365.0)
    straddle = _num(params.get("straddle_price"), "straddle_price")
    return {
        "spot": spot,
        "iv": iv,
        "days": days,
        "move_1sd": _r4(move),
        "move_pct_1sd": _r4(move / spot),
        "range_1sd": [_r4(spot - move), _r4(spot + move)],
        "range_2sd": [_r4(spot - 2 * move), _r4(spot + 2 * move)],
        "move_from_straddle": _r4(0.85 * straddle) if straddle else None,
    }


# --- historical volatility ---------------------------------------------------------


def _hv(history: object) -> dict:
    if not isinstance(history, list):
        raise ValueError("history must be a list of {date, close}")
    closes = [
        (_num(h.get("close"), "close"), str(h.get("date")))
        for h in history
        if isinstance(h, dict) and h.get("close") is not None
    ]
    closes = [c for c, _ in sorted(closes, key=lambda x: x[1])]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0]

    def hv(n: int) -> float | None:
        window = rets[-n:]
        if len(window) < max(2, n // 2):
            return None
        return _r4(stdev(window) * math.sqrt(252))

    return {"hv_30": hv(30), "hv_90": hv(90), "observations": len(closes)}


# --- chain -----------------------------------------------------------------------------


def _rows(raw: object, label: str) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    rows = []
    for r in raw:
        if not isinstance(r, dict) or r.get("strike") is None:
            continue
        rows.append(
            {
                "strike": float(r["strike"]),
                "bid": _num(r.get("bid"), "bid"),
                "ask": _num(r.get("ask"), "ask"),
                "last": _num(r.get("last") if "last" in r else r.get("lastPrice"), "last"),
                "volume": _num(r.get("volume"), "volume") or 0.0,
                "open_interest": _num(
                    r.get("open_interest") if "open_interest" in r else r.get("openInterest"),
                    "open_interest",
                )
                or 0.0,
                "iv": _num(
                    r.get("implied_volatility")
                    if "implied_volatility" in r
                    else r.get("impliedVolatility"),
                    "implied_volatility",
                ),
            }
        )
    return sorted(rows, key=lambda r: r["strike"])


def _mid(r: dict) -> float | None:
    """Mid of a chain row, falling back to last when a side of the quote is missing."""
    if r["bid"] is not None and r["ask"] is not None and (r["bid"] or r["ask"]):
        return float((r["bid"] + r["ask"]) / 2)
    return float(r["last"]) if r["last"] is not None else None


def _atm_stats(by_c: dict, by_p: dict, spot: float) -> tuple[float, float | None, float | None]:
    """ATM strike, mean ATM IV and ATM straddle (sum of the ATM call and put mids)."""
    strikes = sorted(set(by_c) | set(by_p))
    atm = min(strikes, key=lambda k: (abs(k - spot), k))
    ivs = [r["iv"] for r in (by_c.get(atm), by_p.get(atm)) if r and r["iv"]]
    mids = [_mid(r) for r in (by_c.get(atm), by_p.get(atm)) if r]
    straddle = sum(m for m in mids if m is not None) if any(m is not None for m in mids) else None
    return atm, (sum(ivs) / len(ivs) if ivs else None), straddle


def _skew(by_p: dict, by_c: dict, spot: float) -> dict | None:
    """IV of the put nearest 90% of spot minus the call nearest 110% of spot."""
    if not by_p or not by_c:
        return None
    pk = min(by_p, key=lambda k: (abs(k - spot * 0.9), k))
    ck = min(by_c, key=lambda k: (abs(k - spot * 1.1), k))
    piv, civ = by_p[pk]["iv"], by_c[ck]["iv"]
    return {
        "otm_put_strike": pk,
        "otm_put_iv": _r4(piv),
        "otm_call_strike": ck,
        "otm_call_iv": _r4(civ),
        "put_minus_call": _r4(piv - civ) if piv is not None and civ is not None else None,
    }


def _quote(r: dict | None, spot: float, t: float, rate: float, q: float, kind: str) -> dict | None:
    if r is None:
        return None
    mid = _mid(r)
    delta = (
        bs(spot, r["strike"], t, rate, q, r["iv"], kind)["delta"]
        if r["iv"] and r["iv"] > 0 and t > 0
        else None
    )
    return {
        "bid": r["bid"],
        "ask": r["ask"],
        "mid": _r4(mid),
        "last": r["last"],
        "volume": int(r["volume"]),
        "open_interest": int(r["open_interest"]),
        "iv": _r4(r["iv"]),
        "delta": _r4(delta),
        "spread_pct": _r4((r["ask"] - r["bid"]) / mid)
        if mid and r["bid"] is not None and r["ask"] is not None
        else None,
    }


def _chain(params: dict) -> dict:
    spot = _num(params.get("spot"), "spot", True)
    days = _days(params)
    t = days / 365.0
    rate = _num(params.get("rate"), "rate") if params.get("rate") is not None else 0.04
    q = _num(params.get("dividend_yield"), "dividend_yield") or 0.0
    calls, puts = _rows(params.get("calls") or [], "calls"), _rows(params.get("puts") or [], "puts")
    if not calls and not puts:
        raise ValueError("calls or puts are required")
    by_strike_c = {r["strike"]: r for r in calls}
    by_strike_p = {r["strike"]: r for r in puts}
    strikes = sorted(set(by_strike_c) | set(by_strike_p))
    atm, atm_iv, _ = _atm_stats(by_strike_c, by_strike_p, spot)
    move = spot * atm_iv * math.sqrt(t) if atm_iv else None

    ex_div_days = None
    if params.get("ex_dividend_date"):
        as_of = date.fromisoformat(str(params["as_of"])) if params.get("as_of") else date.today()
        d = (date.fromisoformat(str(params["ex_dividend_date"])) - as_of).days
        if 0 <= d < days:
            ex_div_days = d

    call_oi, put_oi = sum(r["open_interest"] for r in calls), sum(r["open_interest"] for r in puts)
    call_vol, put_vol = sum(r["volume"] for r in calls), sum(r["volume"] for r in puts)

    def pain(s: float) -> float:
        return sum(r["open_interest"] * max(s - r["strike"], 0.0) for r in calls) + sum(
            r["open_interest"] * max(r["strike"] - s, 0.0) for r in puts
        )

    max_pain = min(strikes, key=lambda k: (pain(k), k)) if (call_oi or put_oi) else None
    top = sorted(
        [
            {"type": "call", "strike": r["strike"], "open_interest": int(r["open_interest"])}
            for r in calls
        ]
        + [
            {"type": "put", "strike": r["strike"], "open_interest": int(r["open_interest"])}
            for r in puts
        ],
        key=lambda x: (-x["open_interest"], x["type"], x["strike"]),
    )[:3]

    skew = _skew(by_strike_p, by_strike_c, spot)

    around = int(_num(params.get("around"), "around") or 10)
    idx = strikes.index(atm)
    window = strikes[max(0, idx - around) : idx + around + 1]
    rows = [
        {
            "strike": k,
            "call": _quote(by_strike_c.get(k), spot, t, rate, q, "call"),
            "put": _quote(by_strike_p.get(k), spot, t, rate, q, "put"),
        }
        for k in window
    ]

    candidates = []
    for row in rows:
        for kind in ("call", "put"):
            quote = row[kind]
            if quote is None or quote["delta"] is None or quote["iv"] is None:
                continue
            if abs(quote["delta"]) < 0.90:
                continue
            ea = _early_assignment(
                kind, spot, row["strike"], days, rate, q, quote["iv"], quote["mid"], ex_div_days
            )
            if not ea["plausible"]:
                continue
            candidates.append(
                {
                    "type": kind,
                    "strike": row["strike"],
                    "mid": quote["mid"],
                    "time_value": ea["time_value"],
                    "exercise_gain": ea["exercise_gain"],
                    "ex_dividend_days": ex_div_days if kind == "call" else None,
                    "reasons": ea["reasons"],
                }
            )
    candidates.sort(
        key=lambda c: (c["time_value"] if c["time_value"] is not None else 0.0, c["strike"])
    )
    candidates = candidates[:6]

    out = {
        "spot": spot,
        "expiry": params.get("expiry"),
        "days": days,
        "rate": rate,
        "atm_strike": atm,
        "atm_iv": _r4(atm_iv),
        "expected_move_1sd": _r4(move),
        "expected_move_pct": _r4(move / spot) if move else None,
        "put_call_oi_ratio": _r4(put_oi / call_oi) if call_oi else None,
        "put_call_volume_ratio": _r4(put_vol / call_vol) if call_vol else None,
        "max_pain": max_pain,
        "top_open_interest": top,
        "skew": skew,
        "dividend_yield": q,
        "ex_dividend_days": ex_div_days,
        "assignment_candidates": candidates,
        "strikes": rows,
        "hv_30": None,
        "hv_90": None,
        "iv_hv_ratio": None,
    }
    if params.get("history"):
        h = _hv(params["history"])
        out["hv_30"], out["hv_90"] = h["hv_30"], h["hv_90"]
        out["iv_hv_ratio"] = _r4(atm_iv / h["hv_30"]) if atm_iv and h["hv_30"] else None
    return out


# --- term structure ------------------------------------------------------------------


def _term_structure(params: dict) -> dict:
    spot = _num(params.get("spot"), "spot", True)
    as_of = date.fromisoformat(str(params["as_of"])) if params.get("as_of") else date.today()
    raw = params.get("expiries")
    if not isinstance(raw, list):
        raise ValueError("expiries must be a list of {expiry, calls, puts}")
    rows: list[dict] = []
    for e in raw:
        if not isinstance(e, dict) or not e.get("expiry"):
            continue
        days = (date.fromisoformat(str(e["expiry"])) - as_of).days
        if days <= 0:
            continue
        by_c = {r["strike"]: r for r in _rows(e.get("calls") or [], "calls")}
        by_p = {r["strike"]: r for r in _rows(e.get("puts") or [], "puts")}
        if not by_c and not by_p:
            continue
        atm, atm_iv, straddle = _atm_stats(by_c, by_p, spot)
        skew = _skew(by_p, by_c, spot)
        rows.append(
            {
                "expiry": str(e["expiry"]),
                "days": days,
                "atm_strike": atm,
                "atm_iv": _r4(atm_iv),
                "atm_straddle": _r4(straddle),
                "iv_move_pct": _r4(atm_iv * math.sqrt(days / 365.0)) if atm_iv else None,
                "straddle_move_pct": _r4(0.85 * straddle / spot) if straddle else None,
                "put_skew": skew["put_minus_call"] if skew else None,
            }
        )
    if not rows:
        raise ValueError("expiries must contain at least one future expiry with option rows")
    rows.sort(key=lambda r: str(r["expiry"]))
    front, back = rows[0], rows[-1]

    def slope(field: str) -> float | None:
        span = back["days"] - front["days"]
        a, b = front[field], back[field]
        if not span or a is None or b is None:
            return None
        return _r4((b - a) * 30.0 / span)

    iv_slope = slope("atm_iv")
    shape = (
        None
        if iv_slope is None
        else "flat"
        if abs(iv_slope) <= 0.005
        else "rising"
        if iv_slope > 0
        else "falling"
    )

    def _end(e: dict) -> dict:
        return {
            "expiry": e["expiry"],
            "days": e["days"],
            "atm_iv": e["atm_iv"],
            "atm_straddle": e["atm_straddle"],
            "put_skew": e["put_skew"],
        }

    return {
        "spot": spot,
        "as_of": params.get("as_of"),
        "rows": rows,
        "front": _end(front),
        "back": _end(back),
        "iv_slope_30d": iv_slope,
        "iv_term_shape": shape,
        "skew_slope_30d": slope("put_skew"),
    }


def run_options(params: dict) -> dict:
    """Dispatch on ``params['action']``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    action = params.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(_ACTIONS)}")
    if action == "greeks":
        return _greeks(params)
    if action == "payoff":
        return _payoff(params)
    if action == "expected_move":
        return _expected_move(params)
    if action == "hv":
        return _hv(params.get("history"))
    if action == "term_structure":
        return _term_structure(params)
    return _chain(params)


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_options(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
