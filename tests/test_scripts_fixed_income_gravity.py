"""scripts/gravity.py: the bond's implied P/E against the market's."""

import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GRAVITY = PLUGIN_ROOT / "skills" / "fixed-income" / "scripts" / "gravity.py"


def _module():
    """Import gravity.py by path, the way the other fixed-income tests do."""
    spec = importlib.util.spec_from_file_location("gravity", GRAVITY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Pinned so these three ValueError messages can't grow prose at either
# end -- pytest.raises(..., match=...) is a regex SEARCH, so text appended before or after the
# original message would still match "positive"/"empty history" and pass. Reachable in
# production, not just by construction: implied_pe is called from build() with the raw FRED
# value, and DGS1MO printed 0.00 on FRED on real days in 2020-21, so `--tenor 0.0833` takes
# this path with no malformed input at all -- see the subprocess test further down.
ERR_YIELD_NOT_POSITIVE = "yield must be positive to have an implied P/E, got {yield_pct:g}"
ERR_PE_NOT_POSITIVE = "P/E must be positive to have an earnings yield, got {trailing_pe:g}"
ERR_EMPTY_HISTORY = "empty history"


def test_implied_pe_is_the_reciprocal_of_the_yield():
    # The whole point of the feature: a bond yielding y with no growth costs 1/y per unit of
    # coupon, so a 4.96% yield is about 20.2x.
    g = _module()
    assert g.implied_pe(4.96) == pytest.approx(20.1613, abs=1e-4)
    assert g.implied_pe(5.0) == pytest.approx(20.0, abs=1e-9)
    assert g.implied_pe(4.0) == pytest.approx(25.0, abs=1e-9)


def test_earnings_yield_is_the_reciprocal_of_the_pe():
    # SPY trailing P/E 24.81 -> 4.03%, measured 2026-09-23.
    g = _module()
    assert g.earnings_yield_pct(24.81) == pytest.approx(4.0306, abs=1e-4)
    assert g.earnings_yield_pct(20.0) == pytest.approx(5.0, abs=1e-9)


def test_a_zero_or_negative_yield_has_no_implied_pe():
    # 1/0 is not a large P/E, it is undefined, and a negative yield's reciprocal is worse than
    # useless. Both must raise rather than return a number a reader would trust. Pinned to the
    # exact message, not a match="positive" search: a search cannot see prose appended before
    # or after "positive" and would still pass.
    g = _module()
    assert g.ERR_YIELD_NOT_POSITIVE == ERR_YIELD_NOT_POSITIVE
    assert g.ERR_PE_NOT_POSITIVE == ERR_PE_NOT_POSITIVE
    for bad in (0.0, -0.5):
        with pytest.raises(ValueError) as excinfo:
            g.implied_pe(bad)
        assert str(excinfo.value) == ERR_YIELD_NOT_POSITIVE.format(yield_pct=bad)
        with pytest.raises(ValueError) as excinfo:
            g.earnings_yield_pct(bad)
        assert str(excinfo.value) == ERR_PE_NOT_POSITIVE.format(trailing_pe=bad)


def test_percentile_counts_the_history_strictly_below():
    g = _module()
    assert g.ERR_EMPTY_HISTORY == ERR_EMPTY_HISTORY
    hist = [{"value": v} for v in (1.0, 2.0, 3.0, 4.0)]
    assert g.percentile_of(3.0, hist) == pytest.approx(50.0)
    assert g.percentile_of(0.5, hist) == pytest.approx(0.0)
    assert g.percentile_of(9.0, hist) == pytest.approx(100.0)
    with pytest.raises(ValueError) as excinfo:
        g.percentile_of(1.0, [])
    assert str(excinfo.value) == ERR_EMPTY_HISTORY
    # Confirmed dead code, not an emission site, ruled out of scope for this
    # round. _ranked (the only caller of percentile_of) raises IndexError computing the median
    # BEFORE percentile_of ever runs, because `values[midpoint - 1]` on an empty `values` list
    # raises first -- so an empty history can never reach percentile_of's own ValueError
    # through this module's only call path. Documented here, not fixed: the brief asked me to
    # say so rather than change behavior this round.
    with pytest.raises(IndexError):
        g._ranked(1.0, [])


def test_the_value_error_messages_read_no_call():
    for text in (ERR_YIELD_NOT_POSITIVE, ERR_PE_NOT_POSITIVE, ERR_EMPTY_HISTORY):
        lowered = text.lower()
        for word in _FORBIDDEN_WORDS:
            assert word not in lowered, f"{text!r} contains {word!r}"


# Pinned as a LITERAL, independent of the module under test. Reading
# the allowlist's truth from `set(g.TENOR_SERIES.values())` would let prose appended to a
# TENOR_SERIES value be simultaneously the mutation and the allowlist entry that clears it --
# an expectation must not be derived from the thing it checks.
_TENOR_SERIES_PINNED: dict[float, str] = {
    0.0833: "DGS1MO",
    0.25: "DGS3MO",
    0.5: "DGS6MO",
    1.0: "DGS1",
    2.0: "DGS2",
    3.0: "DGS3",
    5.0: "DGS5",
    7.0: "DGS7",
    10.0: "DGS10",
    20.0: "DGS20",
    30.0: "DGS30",
}
_SERIES_IDS = frozenset(_TENOR_SERIES_PINNED.values())


def test_the_tenor_table_covers_the_points_rates_py_maps():
    # Same tenors as rates.py's PAR_SERIES, so a caller who knows one knows the other. All
    # eleven mappings are pinned (not just DGS10/DGS30), so a mutation to any one of them --
    # including the nine that a tenor=10.0-only walk would never exercise -- fails here too.
    g = _module()
    assert g.TENOR_SERIES == _TENOR_SERIES_PINNED


TREASURY = {"value": 4.96, "date": "2026-09-22"}
HISTORY = [{"value": v, "date": f"2020-01-{i + 1:02d}"} for i, v in enumerate([1.0, 2.0, 3.0, 9.0])]


def test_build_reports_both_sides_and_the_gap():
    # 4.96% -> 20.16x; SPY at 24.81 -> 4.0306%; gap = 4.0306 - 4.96 = -0.9294.
    g = _module()
    out = g.build(10.0, "SPY", TREASURY, HISTORY, 24.81)
    assert out["treasury"]["yield_pct"] == 4.96
    assert out["treasury"]["implied_pe"] == pytest.approx(20.1613, abs=1e-4)
    assert out["equity"]["trailing_pe"] == 24.81
    assert out["equity"]["earnings_yield_pct"] == pytest.approx(4.0306, abs=1e-4)
    assert out["gap"]["equity_earnings_yield_minus_treasury_pp"] == pytest.approx(-0.9294, abs=1e-4)


def test_the_treasury_side_is_ranked_and_the_equity_side_is_not():
    g = _module()
    out = g.build(10.0, "SPY", TREASURY, HISTORY, 24.81)
    # 3 of 4 history values are below 4.96.
    assert out["treasury"]["percentiles"]["yield_pct"]["percentile"] == pytest.approx(75.0)
    # The implied P/E's percentile is the yield's inverted, because the transform is monotone.
    assert out["treasury"]["percentiles"]["implied_pe"]["percentile"] == pytest.approx(25.0)
    # The equity side and the gap are NOT ranked, and say so rather than omitting the key.
    assert out["equity"]["percentile"] is None
    assert out["gap"]["percentile"] is None
    assert isinstance(out["equity"]["not_ranked_because"], str)
    assert out["equity"]["not_ranked_because"].strip() != ""


def test_a_proxy_without_a_trailing_pe_is_null_and_never_zero():
    # Measured: yfinance returns trailingPE None for ^GSPC. A zero here would render as an
    # infinite earnings yield and a gap that looks like a screaming signal.
    g = _module()
    out = g.build(10.0, "^GSPC", TREASURY, HISTORY, None)
    assert out["equity"]["trailing_pe"] is None
    assert out["equity"]["earnings_yield_pct"] is None
    assert out["gap"]["equity_earnings_yield_minus_treasury_pp"] is None
    # The disclosure no longer interpolates the symbol -- a 12-character
    # ticker budget spells SELL-STOCKS, and this sentence is the place a reader trusts most.
    # The symbol is reported in its own field instead, which is where a reader should read it.
    assert out["equity"]["unavailable_because"] == UNAVAILABLE_BECAUSE
    assert out["equity"]["proxy"] == "^GSPC"
    # The sentence is now the same bytes whatever the symbol is -- there is no slot left to
    # interpolate into. (^GSPC does appear in it, but as part of its own fixed wording, which
    # is why this is asserted structurally rather than as "the symbol is absent".)
    assert not re.search(r"\{\w*\}", g.UNAVAILABLE_BECAUSE)
    assert g.build(10.0, "BRK.B", TREASURY, HISTORY, None)["equity"]["unavailable_because"] == (
        out["equity"]["unavailable_because"]
    )
    # The Treasury side still works: half a page is better than a wrong page.
    assert out["treasury"]["implied_pe"] == pytest.approx(20.1613, abs=1e-4)


def test_read_args_defaults_and_validates():
    g = _module()
    assert g.read_args([]) == (10.0, "SPY")
    assert g.read_args(["--tenor", "30", "--proxy", "voo"]) == (30.0, "VOO")
    # A tenor with no series is rejected by name, not silently defaulted.
    # InvalidInput, not ValueError: output.run routes ScriptError subclasses to their own
    # exit_code (2) and everything else to EXIT_API_ERROR (5). A bare ValueError here would
    # exit 5 and silently break the "exit 2 = invalid input" constraint.
    with pytest.raises(g.InvalidInput, match="4.5"):
        g.read_args(["--tenor", "4.5"])
    with pytest.raises(g.InvalidInput, match="tenor"):
        g.read_args(["--tenor", "abc"])


def test_the_script_runs_and_prints_json_without_a_network():
    # A bad tenor must fail at exit 2 with JSON on stdout, before any fetch is attempted --
    # which is also how we prove the failure path needs no network.
    proc = subprocess.run(
        [sys.executable, str(GRAVITY), "--tenor", "4.5"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 2, proc.stderr
    assert "error" in json.loads(proc.stdout)


# Output.run prints {"error": <message>, ...} to stdout at exit 2 for
# every InvalidInput, and the only end-to-end test above asserted the KEY exists, never its
# content -- so a routine typo (a bad --tenor, a bad --proxy, an unrecognised flag) could print
# advisory prose to a reader and nothing would notice. Pinned the same way UNAVAILABLE_BECAUSE's
# {proxy} slot is: the fixed text in full, a format() slot for the runtime value.
# Every message below was rewritten to stop quoting the reader back.
# Validating --proxy's SHAPE alone relocated an injected sentence from exit 0 to
# exit 2 instead of removing it -- the test that certified that fix asserted the injected
# sentence appeared on stdout, and this file now asserts it does not. Three echo routes
# existed (--tenor's raw value, an unrecognised argument, the rejected --proxy
# value), plus a fourth at exit 0 inside a disclosure, because 12 characters of
# [A-Z0-9.^-] is enough to spell SELL-STOCKS. One rule replaces four validators: name the
# field, state the shape, report the value's LENGTH rather than the value.
#
# Composed from _VALUE_NOT_ECHOED here exactly as gravity.py composes them -- but from this
# file's OWN literal copy, never from the module under test, so the expectation is not
# derived from the thing it checks.
_VALUE_NOT_ECHOED = (
    "It is not repeated back here, because a message this script emits is never a place to "
    "carry words of someone else's choosing; it was {length} long."
)
ERR_TENOR_MISSING_VALUE = "--tenor needs a value in years"
ERR_TENOR_NOT_A_NUMBER = (
    "--tenor must be a number in years, such as 10 or 0.25, and what was given is not one. "
) + _VALUE_NOT_ECHOED
# {tenor:g} survives the no-echo rule: float() has already rejected everything that is not a
# number, so this renders a canonical short form of a PARSED float, not the bytes typed, and
# cannot carry prose. {choices} is built from _TENOR_SERIES_PINNED, not from input at all.
ERR_TENOR_NO_SERIES = "no Treasury series for a tenor of {tenor:g} years: {choices}"
ERR_PROXY_MISSING_VALUE = "--proxy needs a symbol"
ERR_PROXY_INVALID_SHAPE = (
    "--proxy must look like a ticker symbol (letters, digits, '.', '^', or '-', 1-12 "
    "characters), and what was given is not one. "
) + _VALUE_NOT_ECHOED
ERR_UNRECOGNISED_ARGUMENT = (
    "unrecognised argument: this script accepts --tenor and --proxy only. "
) + _VALUE_NOT_ECHOED
# \A and \Z, not ^ and $: $ also matches before a trailing newline, so
# `--proxy $'spy\n'` was accepted and the newline reached the payload. Same reasoning as
# _ISO_DATE's below. _TICKER_RE is now applied ONLY to the equity.proxy leaf inside
# _assert_whole_payload_pins -- applying it to every string leaf, which cleared a
# ticker-shaped value wherever it appeared.
_TICKER_RE = re.compile(r"\A[A-Z0-9.^-]{1,12}\Z")

_TENOR_CHOICES_TEXT = ", ".join(f"{t:g}" for t in sorted(_TENOR_SERIES_PINNED))


def test_the_invalid_input_messages_are_pinned_and_read_no_call():
    g = _module()
    assert g.ERR_TENOR_MISSING_VALUE == ERR_TENOR_MISSING_VALUE
    assert g.ERR_TENOR_NOT_A_NUMBER == ERR_TENOR_NOT_A_NUMBER
    assert g.ERR_TENOR_NO_SERIES == ERR_TENOR_NO_SERIES
    assert g.ERR_PROXY_MISSING_VALUE == ERR_PROXY_MISSING_VALUE
    assert g.ERR_PROXY_INVALID_SHAPE == ERR_PROXY_INVALID_SHAPE
    assert g.ERR_UNRECOGNISED_ARGUMENT == ERR_UNRECOGNISED_ARGUMENT
    assert g._VALUE_NOT_ECHOED == _VALUE_NOT_ECHOED
    assert g._PROXY_RE.pattern == _TICKER_RE.pattern
    for text in (
        ERR_TENOR_MISSING_VALUE,
        ERR_TENOR_NOT_A_NUMBER,
        ERR_TENOR_NO_SERIES,
        ERR_PROXY_MISSING_VALUE,
        ERR_PROXY_INVALID_SHAPE,
        ERR_UNRECOGNISED_ARGUMENT,
    ):
        lowered = text.lower()
        for word in _FORBIDDEN_WORDS:
            assert word not in lowered, f"{text!r} contains {word!r}"
    # Stated as a property rather than as six readings: the only
    # format slot any of these messages may carry is one that cannot hold the reader's
    # text. {length} is a character count, {tenor} is a parsed float, {choices} is built
    # from TENOR_SERIES. A slot named for a raw argument -- {raw}, {flag}, {proxy} -- is
    # exactly the class this round closed, so its reappearance fails here.
    for text in (
        ERR_TENOR_MISSING_VALUE,
        ERR_TENOR_NOT_A_NUMBER,
        ERR_TENOR_NO_SERIES,
        ERR_PROXY_MISSING_VALUE,
        ERR_PROXY_INVALID_SHAPE,
        ERR_UNRECOGNISED_ARGUMENT,
    ):
        slots = set(re.findall(r"\{(\w+)", text))
        assert slots <= {"length", "tenor", "choices"}, f"{text!r} has slots {slots}"


def test_the_length_helper_reports_a_count_and_never_the_value():
    # The bounded form the script emits in place of the reader's text. It is a count: there is
    # no argument to it that produces any byte of the input, which is the whole point.
    g = _module()
    assert g._length("") == "0 characters"
    assert g._length("a") == "1 character"
    assert g._length("SPY") == "3 characters"
    injected = "we recommend buying bonds and selling stocks"
    rendered = g._length(injected)
    assert rendered == f"{len(injected)} characters"
    for word in ("recommend", "buying", "selling", "bonds", "stocks"):
        assert word not in rendered


def test_read_args_raises_the_pinned_messages_verbatim():
    # Checked at EVERY raise site here, not just the two the subprocess-level
    # tests happen to exercise. ScriptError.extra is exactly what output.fail splices into the
    # emitted envelope alongside "error" and "code" -- InvalidInput(msg, hint="...") would
    # leave `excinfo.value.extra == {"hint": "..."}` and fail here at whichever site it was
    # added to, without needing five separate subprocess invocations to catch it.
    g = _module()
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--tenor"])
    assert str(excinfo.value) == ERR_TENOR_MISSING_VALUE
    assert excinfo.value.extra == {}
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--tenor", "abc"])
    assert str(excinfo.value) == ERR_TENOR_NOT_A_NUMBER.format(length="3 characters")
    assert excinfo.value.extra == {}
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--tenor", "4.5"])
    assert str(excinfo.value) == ERR_TENOR_NO_SERIES.format(tenor=4.5, choices=_TENOR_CHOICES_TEXT)
    assert excinfo.value.extra == {}
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--proxy"])
    assert str(excinfo.value) == ERR_PROXY_MISSING_VALUE
    assert excinfo.value.extra == {}
    injected = "voo. we recommend buying bonds"
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--proxy", injected])
    assert str(excinfo.value) == ERR_PROXY_INVALID_SHAPE.format(length="30 characters")
    assert injected not in str(excinfo.value)
    assert injected.upper() not in str(excinfo.value)
    assert excinfo.value.extra == {}
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--bogus"])
    assert str(excinfo.value) == ERR_UNRECOGNISED_ARGUMENT.format(length="7 characters")
    assert "--bogus" not in str(excinfo.value)
    assert excinfo.value.extra == {}


@pytest.mark.parametrize("proxy", ["SPY", "VOO", "^GSPC", "BRK.B", "RDS-A", "voo"])
def test_the_proxy_shape_still_accepts_real_tickers(proxy):
    # The shape check narrows what --proxy accepts. Confirms it does not newly reject the shapes
    # this script and its tests actually use: plain tickers, an index symbol with a caret, and
    # tickers with '.' or '-' (BRK.B, RDS-A style).
    g = _module()
    assert g.read_args(["--proxy", proxy]) == (10.0, proxy.upper())


def test_the_script_prints_the_pinned_error_message_on_stdout():
    # Confirms the pinned text reaches the reader, not merely the source: a bad --tenor really
    # does print this exact message to stdout at exit 2.
    proc = subprocess.run(
        [sys.executable, str(GRAVITY), "--tenor", "4.5"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["error"] == ERR_TENOR_NO_SERIES.format(tenor=4.5, choices=_TENOR_CHOICES_TEXT)
    assert payload["code"] == "INVALID_INPUT"
    # ScriptError accepts arbitrary **extra, and output.fail splices it
    # into the emitted dict -- InvalidInput(ERR_TENOR_MISSING_VALUE, hint="...you should sell
    # stocks and buy the 10-year") would print that hint at exit 2 today, unseen by any prior
    # test. Pinning the exact key set means a raise call that starts passing extra kwargs
    # fails here immediately.
    assert set(payload) == {"error", "code"}


# Full-text literals, not anchors: an anchor cannot see a sentence added beside intact wording,
# which is how a trade signal would arrive. Each is byte-compared to what the module emits.
#
# ARITHMETIC_MEANING and IMPLIED_PE_PERCENTILE_NOTE were rewritten (the equity side
# is not "two observable prices" the way the bond side is; the implied-P/E percentile is only
# APPROXIMATELY the yield's inverted -- see the tie/zero-day tests below for why), and
# UNAVAILABLE_BECAUSE was promoted from an unguarded inline string to a sixth pinned constant.
ARITHMETIC_MEANING = (
    "A bond yielding y with no growth costs 1/y per unit of coupon, which is a price-earnings "
    "ratio: at 5% a bond costs 20 times its coupon, at 4% it costs 25 times. That identity holds "
    "because a bond's price and its coupon are both observable, so it is arithmetic rather than "
    "a forecast. It is the sense in which a risk-free yield is the hurdle every other asset is "
    "priced against."
)

NOT_RANKED_BECAUSE = (
    "The equity earnings yield is reported for today only and is deliberately not ranked against "
    "history. Today's figure is derived from the proxy's own holdings, while the long history "
    "available for S&P earnings is as-reported index earnings, and the two measure different "
    "things. A percentile computed across that boundary would look precise and would not be, so "
    "none is given. The Treasury side is ranked, because its history comes from the same series "
    "as today's figure."
)

IMPLIED_PE_PERCENTILE_NOTE = (
    "This percentile is approximately the yield's percentile inverted, because 100/y is a "
    "monotone decreasing transform: a lower yield percentile is a higher implied-P/E percentile. "
    "The two are exact complements whenever no history value ties today's yield and every "
    "history value is strictly positive. Percentiles here count values strictly below, so a tie "
    "is counted on neither side, and non-positive yields are excluded from the P/E side but kept "
    "on the yield side, so the two percentiles can be computed over different denominators."
)

# No {proxy} slot any more. `--proxy sell-stocks` is 11 characters of
# [A-Z0-9.^-], so it passes the shape check and would land an imperative INSIDE this
# sentence at exit 0. A constant with no slot cannot carry anyone's text; equity.proxy
# carries the symbol.
UNAVAILABLE_BECAUSE = (
    "the data source reported no usable trailing P/E for the symbol in this block's proxy "
    "field, so its earnings yield is not computed. It is reported as null rather than zero, "
    "because a zero P/E would render as an infinite earnings yield and a gap that looks like "
    "a signal. A fund that tracks the index, such as SPY or VOO, commonly carries a trailing "
    "P/E; an index symbol, such as ^GSPC, commonly does not."
)

FED_MODEL_CAVEAT = (
    "Setting a nominal bond yield beside an equity earnings yield is the comparison usually "
    "called the Fed Model, and it is contested. The bond yield is nominal while corporate "
    "earnings tend to grow with inflation, so the two are not measured on the same footing; "
    "Asness (2003), Fight the Fed Model, is the standard critique, and the comparison's record "
    "as a predictor of returns is weak. The arithmetic above holds regardless: what is contested "
    "is reading a gap between the two as a signal about what to own. Nothing here is a fair "
    "value, a target, or a view on whether either asset is cheap or expensive."
)

DISCLOSURES = {
    "arithmetic": ARITHMETIC_MEANING,
    "not_ranked": NOT_RANKED_BECAUSE,
    "implied_pe_note": IMPLIED_PE_PERCENTILE_NOTE,
    "unavailable_because": UNAVAILABLE_BECAUSE,
    "fed_model": FED_MODEL_CAVEAT,
}

# \Z, not $: Python's $ matches immediately before a trailing newline too, so "2020-01-01\n"
# would pass. Not exploitable as measured (a payload date can't carry a newline plus more text
# and still match), but \Z is the correct anchor for a value that must be nothing else.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")

# The forbidden-verb list the compliance block enforces for financial actions. Shared by the
# per-constant check below and the whole-payload walk, so both apply the identical rule.
_FORBIDDEN_WORDS = ("recommend", "advise", "should", "suggest", "you buy", "you sell")


def _leaf_paths(obj, prefix=()):
    """Every (dotted path, leaf value) pair in a JSON-shaped structure, depth-unlimited.

    A key-set pin one level deep cannot see a key added inside `percentiles`, inside a
    `_ranked` block, or inside `as_of` -- and it cannot see prose concatenated onto an
    existing string value at all, since the key didn't change. This walks every depth so
    both classes of mutation are visible to a test.

    `dict.items(obj)`, not `sorted(obj)`: iterating a dict goes through `__iter__`/`keys`,
    which a dict subclass can override to hide a key that `json.dump(..., indent=2)` still
    prints -- a non-None indent routes through the pure-Python encoder, which reads
    `dct.items()`. Walking the unoverridable `dict.items` makes the pinned surface exactly
    what the reader is shown. The subprocess pins catch this too, because `json.loads`
    re-materialises a plain dict, but they only run at one tenor; these in-process pins run
    all eleven.
    """
    if isinstance(obj, dict):
        for key, val in sorted(dict.items(obj)):
            yield from _leaf_paths(val, (*prefix, str(key)))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from _leaf_paths(item, (*prefix, str(index)))
    else:
        yield ".".join(prefix), obj


def test_every_disclosure_is_emitted_verbatim():
    g = _module()
    out = g.build(10.0, "SPY", TREASURY, HISTORY, 24.81)
    assert out["assumptions"]["arithmetic"] == ARITHMETIC_MEANING
    assert out["assumptions"]["fed_model_caveat"] == FED_MODEL_CAVEAT
    assert out["equity"]["not_ranked_because"] == NOT_RANKED_BECAUSE
    assert out["treasury"]["percentiles"]["implied_pe"]["note"] == IMPLIED_PE_PERCENTILE_NOTE
    missing = g.build(10.0, "^GSPC", TREASURY, HISTORY, None)
    assert missing["equity"]["unavailable_because"] == UNAVAILABLE_BECAUSE


@pytest.mark.parametrize(
    "name", ["arithmetic", "not_ranked", "implied_pe_note", "unavailable_because", "fed_model"]
)
def test_no_disclosure_reads_as_a_call(name):
    # The skill's one unbreakable rule. "should" and "suggest" included: the compliance block
    # forbids them for financial actions, and prose that avoids "buy" while saying "you should"
    # has broken the rule in substance.
    text = DISCLOSURES[name].lower()
    for word in _FORBIDDEN_WORDS:
        assert word not in text, f"{name} contains {word!r}"


# The complete set of leaf paths, alphabetically, once per output shape. A value-level pin
# cannot see a key added at ANY depth -- inside percentiles, inside a _ranked block, inside
# as_of -- so this walks the whole payload rather than stopping one level down. An advisory
# key added anywhere (e.g. "signal" inside a _ranked block, or inside as_of, or inside the
# null-path gap dict) introduces a new path and fails here. 26 leaves happy, 27 null.
_HAPPY_PATH_LEAVES = (
    "as_of.equity",
    "as_of.treasury",
    "assumptions.arithmetic",
    "assumptions.fed_model_caveat",
    "equity.earnings_yield_pct",
    "equity.not_ranked_because",
    "equity.percentile",
    "equity.proxy",
    "equity.trailing_pe",
    "gap.equity_earnings_yield_minus_treasury_pp",
    "gap.percentile",
    "treasury.implied_pe",
    "treasury.percentiles.implied_pe.history_from",
    "treasury.percentiles.implied_pe.median",
    "treasury.percentiles.implied_pe.note",
    "treasury.percentiles.implied_pe.observations",
    "treasury.percentiles.implied_pe.percentile",
    "treasury.percentiles.implied_pe.value",
    "treasury.percentiles.yield_pct.history_from",
    "treasury.percentiles.yield_pct.median",
    "treasury.percentiles.yield_pct.observations",
    "treasury.percentiles.yield_pct.percentile",
    "treasury.percentiles.yield_pct.value",
    "treasury.series_id",
    "treasury.tenor_years",
    "treasury.yield_pct",
)

# The null path adds exactly one leaf, equity.unavailable_because, to the happy-path set.
_NULL_PATH_LEAVES = tuple(sorted((*_HAPPY_PATH_LEAVES, "equity.unavailable_because")))

# The leaf-path pin did not pin leaf TYPES, so e.g. `"series_id": 10`
# (a number, carrying no prose) survived undetected. `build()`'s as_of.equity is always None;
# `main()`'s is a string (today's date), handled by the two _MAIN variants below rather than
# by weakening this one.
_HAPPY_PATH_TYPES = {
    "as_of.equity": "NoneType",
    "as_of.treasury": "str",
    "assumptions.arithmetic": "str",
    "assumptions.fed_model_caveat": "str",
    "equity.earnings_yield_pct": "float",
    "equity.not_ranked_because": "str",
    "equity.percentile": "NoneType",
    "equity.proxy": "str",
    "equity.trailing_pe": "float",
    "gap.equity_earnings_yield_minus_treasury_pp": "float",
    "gap.percentile": "NoneType",
    "treasury.implied_pe": "float",
    "treasury.percentiles.implied_pe.history_from": "str",
    "treasury.percentiles.implied_pe.median": "float",
    "treasury.percentiles.implied_pe.note": "str",
    "treasury.percentiles.implied_pe.observations": "int",
    "treasury.percentiles.implied_pe.percentile": "float",
    "treasury.percentiles.implied_pe.value": "float",
    "treasury.percentiles.yield_pct.history_from": "str",
    "treasury.percentiles.yield_pct.median": "float",
    "treasury.percentiles.yield_pct.observations": "int",
    "treasury.percentiles.yield_pct.percentile": "float",
    "treasury.percentiles.yield_pct.value": "float",
    "treasury.series_id": "str",
    "treasury.tenor_years": "float",
    "treasury.yield_pct": "float",
}
_NULL_PATH_TYPES = {
    **_HAPPY_PATH_TYPES,
    "equity.earnings_yield_pct": "NoneType",
    "equity.trailing_pe": "NoneType",
    "equity.unavailable_because": "str",
    "gap.equity_earnings_yield_minus_treasury_pp": "NoneType",
}
# main() sets as_of.equity to date.today().isoformat() -- the one field build() cannot produce
# itself, since main() is the sole caller who knows the date.
_HAPPY_PATH_TYPES_MAIN = {**_HAPPY_PATH_TYPES, "as_of.equity": "str"}
_NULL_PATH_TYPES_MAIN = {**_NULL_PATH_TYPES, "as_of.equity": "str"}

# The type pins above are checked by IDENTITY against these, not by name.
# `type(value).__name__ == "str"` is satisfied by any class whose __name__ was set to "str",
# and such an object then slips past every `isinstance(value, str)` guard below -- so the
# forbidden-verb arm and the allowlist arm skip it entirely, while json.dump(default=str)
# renders its __str__ as prose on real stdout. Closing that class only where a
# subprocess test runs is not enough: and all seven run at tenor 10.0; a spoof gated on `tenor == 20.0`
# survived the whole suite and printed "DGS20 -- we recommend buying bonds and selling stocks"
# at exit 0. `type(v) is str` closes it at every leaf and every tenor in-process instead,
# which is strictly more than eleven more subprocess runs would buy. (`is`, not isinstance:
# a str SUBCLASS overriding __str__/__eq__ is the same attack with one extra step. bool is
# excluded from int by the same identity check.)
_REAL_TYPES = {"str": str, "float": float, "int": int, "NoneType": type(None)}


def _assert_whole_payload_pins(out, proxy, *, expected_paths, expected_types):
    """The four whole-payload pins in one place: leaf paths, leaf types, every string leaf is a
    pinned constant or a narrow allowlist value, and no string leaf reads as a call.

    Shared by build()-driven and main()-driven callers so the
    checks reach every payload-construction site identically, and `series_ids` here is
    `_SERIES_IDS`, pinned as literals at module level -- never `g.TENOR_SERIES.values()` --
    since reading the allowlist's truth from the module under test would let prose appended to
    a TENOR_SERIES value be simultaneously the mutation and the entry that clears it.

    The proxy arm checks the SHAPE, not `value == proxy` -- the prior
    version was self-clearing (any proxy string, including injected prose, trivially equals
    itself) and only ever ran with the hardcoded SPY/^GSPC test values, so it caught nothing.

    That shape check now applies at ONE path, equity.proxy, instead of
    to every string leaf. `_TICKER_RE.match(value)` as a general arm cleared a ticker-shaped
    string wherever it turned up, and UNAVAILABLE_BECAUSE no longer interpolates the symbol,
    so equity.proxy is the only leaf the reader's text may reach. Every other string leaf must
    be a pinned constant, an ISO date, or a series id -- and, pinned constants aside, must not
    contain the proxy at all, so an echo re-introduced anywhere else is visible to a test.
    (Pinned constants are exempt from the substring check for one honest reason: SPY, VOO and
    ^GSPC appear in UNAVAILABLE_BECAUSE's own fixed wording. An echo INTO a constant changes
    it, so it fails the pinned-membership check one line earlier.)

    Every leaf must be a REAL str/float/int/None -- see _REAL_TYPES. The
    name-based comparison below stays as the readable failure message; the identity loop is
    what actually rejects a spoof, at every leaf and every tenor, in-process.
    """
    leaves = list(_leaf_paths(out))
    assert tuple(sorted(path for path, _ in leaves)) == expected_paths
    assert {path: type(value).__name__ for path, value in leaves} == expected_types
    for path, value in leaves:
        assert type(value) is _REAL_TYPES[expected_types[path]], (
            f"{path} is not a real {expected_types[path]}: {type(value)!r}"
        )
    pinned_prose = {
        ARITHMETIC_MEANING,
        NOT_RANKED_BECAUSE,
        IMPLIED_PE_PERCENTILE_NOTE,
        FED_MODEL_CAVEAT,
        UNAVAILABLE_BECAUSE,
    }
    for path, value in leaves:
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        for word in _FORBIDDEN_WORDS:
            assert word not in lowered, f"{path} contains {word!r}: {value!r}"
        if path == "equity.proxy":
            assert _TICKER_RE.match(value), f"equity.proxy is not ticker-shaped: {value!r}"
            continue
        if value in pinned_prose:
            continue
        assert proxy not in value, f"{path} quotes the --proxy value back: {value!r}"
        assert _ISO_DATE.match(value) or value in _SERIES_IDS, (
            f"unaccounted-for string at {path!r}: {value!r}"
        )


def test_the_leaf_path_and_type_sets_are_exactly_these():
    g = _module()
    happy = g.build(10.0, "SPY", TREASURY, HISTORY, 24.81)
    assert tuple(sorted(path for path, _ in _leaf_paths(happy))) == _HAPPY_PATH_LEAVES
    assert {path: type(v).__name__ for path, v in _leaf_paths(happy)} == _HAPPY_PATH_TYPES
    missing = g.build(10.0, "^GSPC", TREASURY, HISTORY, None)
    assert tuple(sorted(path for path, _ in _leaf_paths(missing))) == _NULL_PATH_LEAVES
    assert {path: type(v).__name__ for path, v in _leaf_paths(missing)} == _NULL_PATH_TYPES
    # By identity here too, so the dedicated type test is not the one place in
    # the file where a class named "str" still counts as a str.
    for payload, types in ((happy, _HAPPY_PATH_TYPES), (missing, _NULL_PATH_TYPES)):
        for path, value in _leaf_paths(payload):
            assert type(value) is _REAL_TYPES[types[path]], f"{path}: {type(value)!r}"


@pytest.mark.parametrize("tenor", tuple(_TENOR_SERIES_PINNED))
@pytest.mark.parametrize("proxy,equity_pe", [("SPY", 24.81), ("^GSPC", None)])
def test_build_output_is_pinned_at_every_tenor_and_shape(tenor, proxy, equity_pe):
    # The prior version of this walk only ever exercised tenor=10.0, so
    # prose appended to any of the other ten TENOR_SERIES values (e.g. "--tenor 20") was never
    # emitted under test and so never caught. Looping every tenor closes that.
    g = _module()
    out = g.build(tenor, proxy, TREASURY, HISTORY, equity_pe)
    is_null = proxy == "^GSPC"
    _assert_whole_payload_pins(
        out,
        proxy,
        expected_paths=_NULL_PATH_LEAVES if is_null else _HAPPY_PATH_LEAVES,
        expected_types=_NULL_PATH_TYPES if is_null else _HAPPY_PATH_TYPES,
    )
    assert out["treasury"]["series_id"] == _TENOR_SERIES_PINNED[tenor]


def _stub_main(monkeypatch, *, proxy, equity_pe, argv_extra=()):
    """Drive gravity.main() end to end against fixed FRED/yfinance stand-ins, no network.

    `result["as_of"]["equity"] = date.today().isoformat()` in main() is
    the one line of payload construction OUTSIDE build(), so a key added after it (or a value
    changed on as_of.equity, which is None and thus invisible to the string-leaf allowlist
    inside build()'s own output) was never walked by any test.
    """
    g = _module()  # exec'ing gravity.py inserts the plugin's lib/ onto sys.path as a side effect
    import second_opinion.fred as fred_mod
    import second_opinion.market as market_mod

    monkeypatch.setattr(fred_mod, "latest", lambda series: dict(TREASURY))
    monkeypatch.setattr(fred_mod, "observations", lambda series, limit: HISTORY)
    monkeypatch.setattr(market_mod, "company_info", lambda symbol: {"pe_ratio": equity_pe})
    return g, g.main(["--proxy", proxy, *argv_extra])


@pytest.mark.parametrize("tenor", tuple(_TENOR_SERIES_PINNED))
@pytest.mark.parametrize("proxy,equity_pe", [("SPY", 24.81), ("^GSPC", None)])
def test_main_output_is_pinned_at_every_tenor_and_shape(monkeypatch, tenor, proxy, equity_pe):
    _, out = _stub_main(monkeypatch, proxy=proxy, equity_pe=equity_pe, argv_extra=["--tenor", str(tenor)])
    is_null = proxy == "^GSPC"
    _assert_whole_payload_pins(
        out,
        proxy,
        expected_paths=_NULL_PATH_LEAVES if is_null else _HAPPY_PATH_LEAVES,
        expected_types=_NULL_PATH_TYPES_MAIN if is_null else _HAPPY_PATH_TYPES_MAIN,
    )
    assert out["treasury"]["series_id"] == _TENOR_SERIES_PINNED[tenor]
    assert out["as_of"]["equity"] == date.today().isoformat()


def test_implied_pe_percentile_note_ties_do_not_sum_to_100():
    # The note says the two percentiles are exact complements WHENEVER there are no ties and
    # no non-positive history rows -- a sufficient condition, not a necessary one (see
    # test_..._sum_to_100_even_with_a_nonpositive_row below for the falsifier that forced that
    # wording). Measured here: a tie at today's yield is counted in NEITHER percentile
    # (percentile_of counts strictly below), so the pair understates rather than summing to 100.
    g = _module()
    tie_treasury = {"value": 2.0, "date": "2026-01-01"}
    tie_history = [
        {"value": v, "date": f"2020-01-0{i + 1}"} for i, v in enumerate([1.0, 2.0, 2.0, 3.0])
    ]
    out = g.build(10.0, "SPY", tie_treasury, tie_history, 24.81)
    yield_pctile = out["treasury"]["percentiles"]["yield_pct"]["percentile"]
    pe_pctile = out["treasury"]["percentiles"]["implied_pe"]["percentile"]
    assert yield_pctile == pytest.approx(25.0)
    assert pe_pctile == pytest.approx(25.0)
    assert yield_pctile + pe_pctile == pytest.approx(50.0)  # not 100


def test_implied_pe_percentile_note_nonpositive_rows_change_the_denominator():
    # Non-positive yields are excluded from the P/E side (implied_pe is undefined at y <= 0)
    # but kept on the yield side, so the two percentiles are computed over different-sized
    # histories (7 rows vs. 4) and need not sum to 100 even with no ties.
    g = _module()
    zero_treasury = {"value": 2.0, "date": "2026-01-01"}
    zero_history = [
        {"value": v, "date": f"2020-01-{i + 1:02d}"}
        for i, v in enumerate([0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 4.0])
    ]
    out = g.build(10.0, "SPY", zero_treasury, zero_history, 24.81)
    yield_block = out["treasury"]["percentiles"]["yield_pct"]
    pe_block = out["treasury"]["percentiles"]["implied_pe"]
    assert yield_block["observations"] == 7
    assert pe_block["observations"] == 4  # the three zero rows are excluded
    assert yield_block["percentile"] == pytest.approx(57.1)
    assert pe_block["percentile"] == pytest.approx(50.0)
    assert yield_block["percentile"] + pe_block["percentile"] == pytest.approx(107.1)  # not 100


def test_implied_pe_percentile_note_can_sum_to_100_even_with_a_nonpositive_row():
    # The note used to read "exact complements ONLY WHEN no history value
    # ties ... and every history value is strictly positive" -- a necessary-condition claim,
    # and false: a non-positive row shrinks the P/E denominator without moving either count
    # past a boundary, so the pair can still land on exactly 100. History [0.0, 1.0, 2.0] with
    # today at 5.0 is above every row on the yield side (100.0) and below every row on the P/E
    # side (0.0). The note now says "whenever", the sufficient direction, which is exactly
    # true; this test is what stops the stronger word coming back.
    g = _module()
    treasury = {"value": 5.0, "date": "2026-01-01"}
    history = [{"value": v, "date": f"2020-01-0{i + 1}"} for i, v in enumerate([0.0, 1.0, 2.0])]
    out = g.build(10.0, "SPY", treasury, history, 24.81)
    yield_block = out["treasury"]["percentiles"]["yield_pct"]
    pe_block = out["treasury"]["percentiles"]["implied_pe"]
    assert yield_block["observations"] == 3
    assert pe_block["observations"] == 2  # the zero row is excluded
    assert yield_block["percentile"] == pytest.approx(100.0)
    assert pe_block["percentile"] == pytest.approx(0.0)
    assert yield_block["percentile"] + pe_block["percentile"] == pytest.approx(100.0)
    assert "whenever no history value ties" in pe_block["note"]
    assert "only when no history value ties" not in pe_block["note"]


# Three consecutive rounds found the pinned surface was a
# subset of what reaches the reader, and the last layer is stdout itself -- the payload dict is
# not the whole of it. A bare print() inside build(), a second output.emit() ahead of the real
# payload, or a leaf whose type(v).__name__ == "str" without being a real str (json.dump's
# default=str then renders it as prose) all survive every in-process check above. Running the
# ACTUAL script as a subprocess and parsing its ACTUAL stdout closes all four at once: exactly
# one JSON document (json.loads raises "Extra data" on anything else, before or after), then
# every leaf through the same _assert_whole_payload_pins helper -- which is also a free
# json.dumps/json.loads round trip that turns any type-spoofed leaf into a genuine str, where
# the allowlist and verb checks see it like any other string.
def _seed_fred_cache(tmp_path, series_id, rows):
    """A FRED cache CSV fresh enough that fred.latest/observations read it, no network."""
    cache_dir = tmp_path / "second-opinion-data" / "fred-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lines = ["observation_date,VALUE"] + [f"{d},{v}" for d, v in rows]
    (cache_dir / f"{series_id}.csv").write_text("\n".join(lines) + "\n")
    return tmp_path / "second-opinion-data"


def _seed_yfinance_stub(tmp_path, pe_ratio, *, raises=False):
    """A minimal yfinance shim, first on PYTHONPATH, so market.company_info needs no network
    and no real yfinance install to exercise this path.

    With ``raises=True`` the shim raises ImportError on import instead, which is how an
    uninstalled yfinance reaches this script: market._yf() imports it lazily, so output.run's
    ImportError arm (exit 6) fires. The real interpreter running these tests HAS yfinance
    installed, so shadowing it on PYTHONPATH is the only way to exercise that branch.
    """
    stub_dir = tmp_path / "yfinance_stub"
    stub_dir.mkdir(exist_ok=True)
    if raises:
        (stub_dir / "yfinance.py").write_text(
            'raise ImportError("No module named \'yfinance\'", name="yfinance")\n'
        )
        return stub_dir
    pe_repr = "None" if pe_ratio is None else repr(pe_ratio)
    (stub_dir / "yfinance.py").write_text(
        "class Ticker:\n"
        "    def __init__(self, symbol):\n"
        f"        self.info = {{'trailingPE': {pe_repr}}}\n"
    )
    return stub_dir


_DEFAULT_FRED_ROWS = [
    (f"2020-01-{i + 1:02d}", v) for i, v in enumerate([1.0, 2.0, 3.0, 9.0, 4.96])
]


def _run_gravity(
    tmp_path, argv, *, series_id="DGS10", fred_rows=None, pe_ratio=24.81, no_yfinance=False
):
    data_root = _seed_fred_cache(tmp_path, series_id, fred_rows or _DEFAULT_FRED_ROWS)
    stub_dir = _seed_yfinance_stub(tmp_path, pe_ratio, raises=no_yfinance)
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(stub_dir),
        "SECOND_OPINION_DATA": str(data_root),
    }
    return subprocess.run(
        [sys.executable, str(GRAVITY), *argv], capture_output=True, text=True, env=env
    )


def _assert_stdout_reads_no_call(stdout):
    """No forbidden verb anywhere in the raw bytes the reader receives.

    The leaf-level verb check only sees leaves a parsed payload HAS, and the error
    envelopes are not payloads at all. This reads the whole document as text, so a verb in a
    key name, in an envelope field no pin names, or between two JSON documents is visible.
    """
    lowered = stdout.lower()
    for word in _FORBIDDEN_WORDS:
        assert word not in lowered, f"stdout contains {word!r}: {stdout!r}"


def test_the_success_path_emits_exactly_one_json_document_pinned_end_to_end(tmp_path):
    # Nothing before this observed the SUCCESS path's real stdout -- every
    # success test calls build()/main() in-process, where pytest captures the return value
    # directly and any stray print() never gets inspected. A leaf whose
    # type(v).__name__ == "str" but isn't a real str passes the in-process type pin AND is
    # skipped by `isinstance(value, str)` guards everywhere else; json.loads(proc.stdout)
    # removes that class for free, because the spoofed object is now a genuine string.
    proc = _run_gravity(tmp_path, ["--proxy", "SPY"], pe_ratio=24.81)
    assert proc.returncode == 0, proc.stderr
    _assert_stdout_reads_no_call(proc.stdout)
    payload = json.loads(proc.stdout)  # raises "Extra data" if stdout is not ONE JSON document
    _assert_whole_payload_pins(
        payload, "SPY", expected_paths=_HAPPY_PATH_LEAVES, expected_types=_HAPPY_PATH_TYPES_MAIN
    )


def test_the_null_path_emits_exactly_one_json_document_pinned_end_to_end(tmp_path):
    # Running only the HAPPY shape through real stdout is not enough: and the null
    # shape is the one that carries UNAVAILABLE_BECAUSE, the proxy interpolation that was
    # removed, and four null leaves. A type-spoofed unavailable_because (a class named "str"
    # with __eq__/__contains__ true and __str__ returning prose) satisfied every in-process
    # check and printed a call to real stdout at exit 0 until this test existed: json.dump's
    # default=str renders it, and json.loads turns it back into a genuine str, where the verb
    # check and the pinned-constant check both see it.
    proc = _run_gravity(tmp_path, ["--proxy", "^GSPC"], pe_ratio=None)
    assert proc.returncode == 0, proc.stderr
    _assert_stdout_reads_no_call(proc.stdout)
    payload = json.loads(proc.stdout)
    _assert_whole_payload_pins(
        payload, "^GSPC", expected_paths=_NULL_PATH_LEAVES, expected_types=_NULL_PATH_TYPES_MAIN
    )
    assert payload["equity"]["unavailable_because"] == UNAVAILABLE_BECAUSE


def test_a_zero_treasury_yield_takes_the_pinned_valueerror_path_on_real_stdout(tmp_path):
    # Reachable in production, not just by construction. DGS1MO (a tenor this
    # script offers via --tenor 0.0833) printed 0.00 on FRED on real days in 2020-21, and
    # implied_pe is called from build() with the raw fetched value -- no malformed input
    # needed, just an ordinary day for that series.
    proc = _run_gravity(
        tmp_path,
        ["--tenor", "0.0833"],
        series_id="DGS1MO",
        fred_rows=[("2020-03-24", 0.05), ("2020-03-25", 0.02), ("2020-03-26", 0.0)],
    )
    assert proc.returncode == 5, proc.stderr
    _assert_stdout_reads_no_call(proc.stdout)
    payload = json.loads(proc.stdout)
    assert payload["error"] == ERR_YIELD_NOT_POSITIVE.format(yield_pct=0.0)
    assert payload["code"] == "API_ERROR"
    # Only the exit-2 envelope was pinned before this line. This is
    # output.run's GENERIC `except Exception` arm, which emits two fields no pin named:
    # http_status, read off the exception's `status` attribute, and type, its class name. A
    # ValueError subclass carrying `status = "MUTANT: we recommend buying bonds"` printed that
    # string here at exit 5 and survived the whole suite. Both are pinned now, alongside the
    # exact key set, so an added field or a spliced value fails.
    assert set(payload) == {"error", "code", "http_status", "type"}
    assert payload["http_status"] is None
    assert payload["type"] == "ValueError"


def test_an_upstream_fred_error_takes_the_scripterror_envelope_on_real_stdout(tmp_path):
    # Correcting the brief: exit 5 has TWO envelopes, not one. ApiError
    # (what fred.py actually raises) is a ScriptError, so it takes output.run's ScriptError
    # arm -- `fail(str(e), e.code, e.exit_code, **e.extra)` -- which emits {error, code} plus
    # whatever `extra` the raise site passed, and NOT the generic arm's http_status/type. The
    # generic arm above is reached by anything that is not a ScriptError (the ValueError from
    # implied_pe). Both are live routes to a reader, so both are pinned.
    # A cache of all-non-numeric rows is how FRED's own "." (no observation) days look.
    proc = _run_gravity(tmp_path, [], fred_rows=[("2020-01-01", "."), ("2020-01-02", ".")])
    assert proc.returncode == 5, proc.stderr
    _assert_stdout_reads_no_call(proc.stdout)
    payload = json.loads(proc.stdout)
    assert set(payload) == {"error", "code"}
    assert payload["code"] == "FRED_HTTP"
    assert payload["error"] == "FRED series DGS10 has no numeric observations"


def test_a_missing_yfinance_takes_the_pinned_dependency_envelope_on_real_stdout(tmp_path):
    # Exit 6 is reachable from this script -- market._yf() imports
    # yfinance lazily, so a plugin installed without it takes output.run's ImportError arm on
    # every successful-so-far run. Exit 4 is NOT reachable: the only ConfigError raise sites
    # are config.py's SnapTrade and E*Trade credential loaders, which nothing on this script's
    # path calls, and FRED's CSV endpoint is keyless. Documented here rather than pinned.
    proc = _run_gravity(tmp_path, [], no_yfinance=True)
    assert proc.returncode == 6, proc.stderr
    _assert_stdout_reads_no_call(proc.stdout)
    payload = json.loads(proc.stdout)
    assert set(payload) == {"error", "code", "missing", "requirements", "install_log"}
    assert payload["error"] == "missing dependency: yfinance"
    assert payload["code"] == "DEPENDENCY_MISSING"
    assert payload["missing"] == "yfinance"
    # install_log is os.environ["SNAPTRADE_INSTALL_LOG"] echoed verbatim by output.py -- an
    # environment-supplied string reaching stdout, inherited by every script in the plugin.
    # Ruled out of scope for this task and recorded as a plugin-wide item; pinned here only as
    # null under this test's own env, so that its shape is at least nailed down from here.
    assert payload["install_log"] is None


# The certifying test for the proxy route, inverted. An earlier version
# asserted that the injected sentence APPEARED on stdout (inside the rejection message), which
# certified a fix that had only moved the prose from exit 0 to exit 2. What a reader must never
# see is the sentence, at any exit code -- so this asserts its ABSENCE, in both casings, on
# every route by which the reader's own argv text used to be echoed.
_ECHO_ROUTES = [
    ("tenor", ["--tenor", "ten. we recommend buying bonds and selling stocks now"]),
    ("unrecognised", ["NOTE: you should sell stocks and buy the 10-year"]),
    ("proxy", ["--proxy", "voo. we recommend buying bonds"]),
]


@pytest.mark.parametrize("name,argv", _ECHO_ROUTES, ids=[n for n, _ in _ECHO_ROUTES])
def test_no_emitted_message_quotes_back_what_the_user_typed(tmp_path, name, argv):
    # All three routes once
    # printed the reader's own sentence inside "error" at exit 2.
    injected = argv[-1]
    proc = _run_gravity(tmp_path, argv)
    assert proc.returncode == 2, proc.stderr
    _assert_stdout_reads_no_call(proc.stdout)
    assert injected not in proc.stdout
    assert injected.upper() not in proc.stdout
    # Not just the whole sentence: no run of the reader's words survives either, which is what
    # distinguishes "stopped echoing" from "echoed a truncation".
    for word in injected.replace(".", " ").replace(":", " ").split():
        if len(word) > 3:
            assert word.lower() not in proc.stdout.lower(), f"{word!r} survived on stdout"
    payload = json.loads(proc.stdout)
    assert set(payload) == {"error", "code"}
    assert payload["code"] == "INVALID_INPUT"
    expected = {
        "tenor": ERR_TENOR_NOT_A_NUMBER.format(length="53 characters"),
        "unrecognised": ERR_UNRECOGNISED_ARGUMENT.format(length="48 characters"),
        "proxy": ERR_PROXY_INVALID_SHAPE.format(length="30 characters"),
    }[name]
    assert payload["error"] == expected


def test_a_ticker_shaped_imperative_reaches_no_disclosure_at_exit_zero(tmp_path):
    # The fourth route and the sharpest one: `sell-stocks` is 11 characters
    # of [A-Z0-9.^-], so the shape check ACCEPTS it, and the old UNAVAILABLE_BECAUSE
    # interpolated it: "...no usable trailing P/E for SELL-STOCKS, so its earnings yield is
    # not computed..." -- an imperative inside a pinned disclosure, at exit 0, in the sentence
    # a reader trusts most. The symbol now appears only in its own field.
    proc = _run_gravity(tmp_path, ["--proxy", "sell-stocks"], pe_ratio=None)
    assert proc.returncode == 0, proc.stderr
    # This was the one subprocess test not running the blunt net. It
    # cannot fire here today -- "sell-stocks" is not in _FORBIDDEN_WORDS, which want a verb
    # with an object ("you sell") -- but the net is uniform across all seven now, so a future
    # route into this payload is covered by the same line as the other six.
    _assert_stdout_reads_no_call(proc.stdout)
    payload = json.loads(proc.stdout)
    _assert_whole_payload_pins(
        payload,
        "SELL-STOCKS",
        expected_paths=_NULL_PATH_LEAVES,
        expected_types=_NULL_PATH_TYPES_MAIN,
    )
    assert payload["equity"]["proxy"] == "SELL-STOCKS"
    assert payload["equity"]["unavailable_because"] == UNAVAILABLE_BECAUSE
    # Once, in one place: equity.proxy. Any other occurrence is the symbol reaching prose.
    assert proc.stdout.count("SELL-STOCKS") == 1
    assert [p for p, v in _leaf_paths(payload) if isinstance(v, str) and "SELL-STOCKS" in v] == [
        "equity.proxy"
    ]


def test_a_trailing_newline_no_longer_clears_the_proxy_shape(tmp_path):
    # _PROXY_RE used ^...$, and Python's $ also matches immediately before a
    # trailing newline, so `--proxy $'spy\n'` was accepted and the newline reached the payload.
    # \A...\Z is the correct anchor for a value that must be nothing else.
    g = _module()
    with pytest.raises(g.InvalidInput) as excinfo:
        g.read_args(["--proxy", "spy\n"])
    assert str(excinfo.value) == ERR_PROXY_INVALID_SHAPE.format(length="4 characters")
    proc = _run_gravity(tmp_path, ["--proxy", "spy\n"])
    assert proc.returncode == 2, proc.stderr
    assert json.loads(proc.stdout)["error"] == ERR_PROXY_INVALID_SHAPE.format(
        length="4 characters"
    )
