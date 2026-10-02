"""scripts/rates.py: percentile ranks, the implied path, and the import path."""

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RATES = PLUGIN_ROOT / "skills" / "fixed-income" / "scripts" / "rates.py"

# Recorded FRED values, kept for context only — the tests below build their
# curve by hand and never touch the network (F10 deleted the fake_fred fixture,
# which monkeypatched nothing):
#   DGS1MO 3.96, DGS3MO 4.14, DGS6MO 4.22, DGS1 4.45, DGS2 4.74, DGS3 4.82,
#   DGS5 4.86, DGS7 4.94, DGS10 5.01, DGS20 5.39, DGS30 5.35, DFII10 2.68,
#   T10YIE 2.33, THREEFYTP10 0.96, BAA10Y 1.43, DFF 3.63, FEDTARMDLR 3.20


def test_percentile_ranks_a_value_against_its_history():
    sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "fixed-income" / "scripts"))
    import rates

    hist = [{"date": "2020-01-01", "value": v} for v in [1.0, 2.0, 3.0, 4.0]]
    assert rates.percentile_of(2.5, hist) == pytest.approx(50.0)
    assert rates.percentile_of(0.5, hist) == pytest.approx(0.0)
    assert rates.percentile_of(9.0, hist) == pytest.approx(100.0)
    assert rates.percentile_of(2.0, hist) == pytest.approx(25.0)  # ties are excluded


def test_implied_short_rate_path_uses_forwards():
    sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "fixed-income" / "scripts"))
    import rates
    from second_opinion import bondmath

    tenors = [0.5, 1, 2, 5, 10, 30]
    pars = [0.0422, 0.0445, 0.0474, 0.0486, 0.0501, 0.0535]
    curve = bondmath.bootstrap(tenors, pars)
    path = rates.short_rate_path(curve, horizon_years=6)
    assert len(path) == 6
    assert all(0 < row["rate_pct"] < 15 for row in path)
    # An upward-sloping curve implies rising short rates
    assert path[-1]["rate_pct"] > path[0]["rate_pct"]
    # Pin the actual forwards, not just their shape: a spot-zero-rate
    # substitution, a dropped *100 and a removed short-end guard all satisfy
    # len/band/ordering while publishing a different quantity.
    assert path[0]["rate_pct"] == pytest.approx(4.685, abs=2e-3)
    assert path[1]["rate_pct"] == pytest.approx(5.046, abs=2e-3)


def test_the_script_imports_second_opinion_with_no_pythonpath():
    # F19: SKILL.md runs a script with no PYTHONPATH from an unrelated cwd. Import
    # the real file (its __main__ guard means nothing is fetched) so a missing
    # sys.path bootstrap fails here instead of on a user's machine.
    probe = (
        "import importlib.util; "
        f"spec = importlib.util.spec_from_file_location('rates_probe', {str(RATES)!r}); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},  # no PYTHONPATH — that is the point
        cwd="/",
    )
    assert proc.returncode == 0, proc.stderr
    assert "No module named 'second_opinion'" not in proc.stderr


def test_the_documented_output_contract_names_every_key_build_returns():
    """M4: the docstring's contract omitted two keys the script emits -- the top-level
    ``note`` and ``implied_average_short_rate_pct``, which SKILL.md calls the one-number
    summary. Derived from the source rather than re-listed, so the two cannot drift apart
    again, and no network is touched."""
    import ast
    import re

    source = RATES.read_text()
    tree = ast.parse(source)
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build")
    returns = [n for n in ast.walk(build) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assert len(returns) == 1
    emitted = [key.value for key in returns[0].value.keys]
    contract = ast.get_docstring(tree).split("Output JSON contract (stdout)::", 1)[1]
    documented = re.findall(r'^      "([a-z_0-9]+)":', contract, re.M)
    assert documented == emitted


# The breakeven disclosure, pinned as a test-local full-text literal rather than an anchor or a
# length: an anchor cannot see a sentence added beside intact wording, and this text is the only
# thing standing between two percentile figures and a reader who reads them as a call.
BREAKEVEN_MEANING = (
    "percentiles.real_yield_10y is the 10-year TIPS yield and percentiles.breakeven_10y is the "
    "10-year breakeven, which is the difference between the nominal 10-year yield and that real "
    "yield: nominal is approximately real plus breakeven. The breakeven is the inflation rate at "
    "which a TIPS and a nominal Treasury come out even, so inflation realised above it favours "
    "the TIPS and below it favours the nominal. It is a market price rather than a forecast, and "
    "it carries an inflation risk premium as well as an expectation, so it is not the market's "
    "central estimate of inflation. Neither figure is a view on whether either instrument is "
    "cheap or expensive."
)


def test_the_breakeven_disclosure_is_emitted_verbatim():
    """The skill reports a real yield and a breakeven but never said how they relate, which is the
    one thing a reader needs to use them. Parsed from the source rather than run, because build()
    needs the network; the literal above is the whole emitted string, so an insertion anywhere
    inside it fails here."""
    import ast

    tree = ast.parse(RATES.read_text())
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build")
    returns = [n for n in ast.walk(build) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assumptions = next(
        v for k, v in zip(returns[0].value.keys, returns[0].value.values) if k.value == "assumptions"
    )
    emitted = {
        k.value: v.value
        for k, v in zip(assumptions.keys, assumptions.values)
        if isinstance(v, ast.Constant) and isinstance(v.value, str)
    }
    assert emitted["breakeven_meaning"] == BREAKEVEN_MEANING
    # It must not turn into a call: the skill may rank today against history, never advise.
    lowered = BREAKEVEN_MEANING.lower()
    for word in ("recommend", "advise", "should", "suggest", "buy", "sell"):
        assert word not in lowered
