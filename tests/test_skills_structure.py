"""Structure tests for the plugin finance skills.

From the repository root:

    python -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PLUGIN_ROOT / "skills"
PLUGIN_JSON = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

SKILL_NAMES = [
    "onboarding",
    "valuation",
    "portfolio-analysis",
    "trading",
    "market-analysis",
    "personal-finance",
    "connect",
    "portfolio-snapshot",
    "dividend-income",
    "statement-import",
    "trade-review",
    "options",
    "real-estate",
    "financial-education",
    "tax-aware",
    "rebalancing",
    "retirement",
    "risk-analysis",
    "fundamental-research",
    "trade-journal",
    "watchlist",
    "debt-tracker",
    "spending",
    "fixed-income",
    "stock-screener",
]

TRADING_PROTOCOL_SKILLS = {"trading", "portfolio-analysis"}

# Every references/*.md file, registered so each one is checked for a link from its SKILL.md and a TOC.
REFERENCE_FILES = [
    "valuation/references/dcf-methods.md",
    "valuation/references/value-investing.md",
    "portfolio-analysis/references/portfolio-research.md",
    "portfolio-snapshot/references/how-figures-are-built.md",
    "trading/references/momentum-research.md",
    "financial-education/references/curriculum.md",
    "personal-finance/references/account-rules.md",
    "fundamental-research/references/due-diligence.md",
    "fixed-income/references/bond-math.md",
    "fixed-income/references/treasuries.md",
]

# The verbs the compliance block bans for financial actions. A reference file is prose the model
# reads and paraphrases back to the user, so it is the same surface as script output and gets the
# same net. Stems, so "recommends"/"recommendation"/"adviser"/"suggesting" are caught too.
FORBIDDEN_VERB_RE = re.compile(r"\b(recommend\w*|advis\w*|should|suggest\w*)\b", re.IGNORECASE)

# Which registered references the net is enforced over, by skill.
#
# Scoped, not global, and deliberately so. The other six registered references predate this guard
# and between them carry 19 occurrences -- almost all of them methodological ("the DCF-derived
# price should be treated as a range"), none of them reviewed against this rule. Parametrising the
# net over all eight would either fail the suite or ship a 19-line bless-list that reads as
# coverage while blessing prose nobody checked. Widening it is a real piece of work (read all 19,
# reword or justify each) and belongs in its own change, not in a fix wave.
#
# There is no allowance list here, and that is the point: fixed-income's references are clean of
# all four verbs outright, including in safe negations. `treasuries.md` used to end the phantom-
# income section with "not a view on where anyone SHOULD hold one" -- a true negation, and still
# the banned word in a sentence about holding an instrument. It was reworded rather than
# allowlisted, so the net can stay absolute and needs no judgement call at the boundary.
VERB_GUARDED_REFERENCE_SKILLS = ("fixed-income",)
GUARDED_REFERENCES = [
    rel for rel in REFERENCE_FILES if rel.split("/")[0] in VERB_GUARDED_REFERENCE_SKILLS
]

MAX_SKILL_BODY_LINES = 500
TOC_REQUIRED_OVER_LINES = 100
TOC_HEADING = "## Contents"


def _skill_md_path(name: str) -> Path:
    return SKILLS_ROOT / name / "SKILL.md"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "SKILL.md must start with a frontmatter block"
    end = text.index("\n---", 4)
    frontmatter_raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    frontmatter: dict[str, str] = {}
    for line in frontmatter_raw.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_skill_md_exists(skill_name: str) -> None:
    assert _skill_md_path(skill_name).is_file(), f"missing SKILL.md for {skill_name}"


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_frontmatter_has_name_and_description_no_allowed_tools(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    frontmatter, _ = _parse_frontmatter(text)
    assert frontmatter.get("name"), f"{skill_name}: frontmatter missing name"
    assert frontmatter.get("description"), f"{skill_name}: frontmatter missing description"
    assert "allowed-tools" not in frontmatter, f"{skill_name}: allowed-tools must be dropped"


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_body_contains_compliance_rule(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    assert "Never provide buy, sell, or hold recommendations" in text, (
        f"{skill_name}: missing compliance rule text"
    )


@pytest.mark.parametrize("skill_name", sorted(TRADING_PROTOCOL_SKILLS))
def test_trading_and_portfolio_skills_require_confirm(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    assert "--confirm" in text, f"{skill_name}: must document the --confirm requirement"


def test_plugin_json_exists() -> None:
    assert PLUGIN_JSON.is_file(), f"missing plugin.json at {PLUGIN_JSON}"


def test_plugin_json_parses() -> None:
    text = PLUGIN_JSON.read_text()
    data = json.loads(text)
    assert isinstance(data, dict), "plugin.json must contain a JSON object"


def test_plugin_json_has_required_fields() -> None:
    data = json.loads(PLUGIN_JSON.read_text())
    assert "name" in data, "plugin.json missing 'name'"
    assert "version" in data, "plugin.json missing 'version'"
    assert data.get("name") == "second-opinion", "plugin.json name must be 'second-opinion'"


@pytest.mark.parametrize("rel_plugin", GUARDED_REFERENCES)
def test_guarded_reference_file_uses_no_forbidden_verb(rel_plugin: str) -> None:
    """No "recommend"/"advise"/"should"/"suggest" anywhere in a guarded reference file.

    Final-review M-6: `treasuries.md` shipped 164 lines of user-visible prose with no automated
    guard of any kind, while the script output beside it carries a full-text verb net. Prose the
    model is told to read before answering is the same surface as a string the script prints, and
    it was the only one of the two nothing checked.
    """
    path = SKILLS_ROOT / rel_plugin
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        hit = FORBIDDEN_VERB_RE.search(line)
        assert hit is None, (
            f"{path.relative_to(PLUGIN_ROOT)}:{lineno} uses the forbidden verb "
            f"{hit.group(0)!r} -- reword it; the net has no allowance list, "
            f"not even for negations. Line: {line.strip()!r}"
        )


def test_verb_guard_covers_every_reference_of_every_guarded_skill() -> None:
    """A new fixed-income reference cannot join the tree outside the net.

    GUARDED_REFERENCES is derived from REFERENCE_FILES, and
    test_every_plugin_reference_file_is_registered already forces every reference file into that
    list, so this only has to confirm the guarded skills actually contribute files -- an empty
    parametrisation would make the test above vacuously green.
    """
    for skill in VERB_GUARDED_REFERENCE_SKILLS:
        on_disk = sorted(p.name for p in (SKILLS_ROOT / skill / "references").glob("*.md"))
        guarded = sorted(rel.split("/")[-1] for rel in GUARDED_REFERENCES if rel.startswith(skill))
        assert on_disk and on_disk == guarded, f"{skill}: {on_disk} guarded as {guarded}"


def test_every_plugin_reference_file_is_registered() -> None:
    """A new references/*.md without a REFERENCE_FILES entry would silently skip the link and TOC checks."""
    found = sorted(str(p.relative_to(SKILLS_ROOT)) for p in SKILLS_ROOT.glob("*/references/*.md"))
    registered = sorted(REFERENCE_FILES)
    assert found == registered, f"unregistered reference files: {set(found) - set(registered)}"


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_skill_md_body_under_500_lines(skill_name: str) -> None:
    _, body = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    n = len(body.splitlines())
    assert n < MAX_SKILL_BODY_LINES, f"{skill_name}: body is {n} lines (limit {MAX_SKILL_BODY_LINES})"


@pytest.mark.parametrize("rel_plugin", REFERENCE_FILES)
def test_reference_file_linked_from_skill_md(rel_plugin: str) -> None:
    ref = SKILLS_ROOT / rel_plugin
    _, body = _parse_frontmatter((ref.parent.parent / "SKILL.md").read_text())
    assert f"references/{ref.name}" in body, (
        f"{ref.parent.parent.name}: SKILL.md does not link references/{ref.name}"
    )


@pytest.mark.parametrize("rel_plugin", REFERENCE_FILES)
def test_long_reference_file_has_table_of_contents(rel_plugin: str) -> None:
    lines = (SKILLS_ROOT / rel_plugin).read_text().splitlines()
    if len(lines) <= TOC_REQUIRED_OVER_LINES:
        return
    assert TOC_HEADING in lines[:40], f"{rel_plugin}: missing '{TOC_HEADING}' in the first 40 lines"
    toc_start = lines.index(TOC_HEADING)
    heading_indices = [i for i in range(toc_start + 1, len(lines)) if lines[i].startswith("## ")]
    assert heading_indices, f"{rel_plugin}: no '## ' section heading follows the TOC"
    toc_end = heading_indices[0]
    toc_entries = {ln[len("- ") :].strip() for ln in lines[toc_start:toc_end] if ln.startswith("- ")}
    for heading in (ln[3:].strip() for ln in lines[toc_end:] if ln.startswith("## ")):
        assert heading in toc_entries, f"{rel_plugin}: TOC is missing section {heading!r}"


INVOCATION = '"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/'

SAFETY_RULES = [
    "Never run a script with `--confirm` until the preview output has been shown in the chat and the user has explicitly said yes in their own message.",
    "One order per confirmation. Never chain a sell into a buy on a single yes.",
    "Check the account's `supports_trading` flag from `accounts.py` before previewing.",
    "If the account is cash or unknown, warn when the order size exceeds the balance script's `cash` figure, and never infer margin from buying power.",
    "Do not place an order when `place-order.py` returned exit 3, 4, 5, or 6. Show the error and stop.",
]

RESEARCH_DATING_SKILLS = {"market-analysis", "trading", "valuation", "trade-review", "portfolio-analysis"}

# The dating protocol for web-sourced news, pinned verbatim: search snippets blend years, and an
# undated analyst note once got presented as the cause of a move that happened a year later.
RESEARCH_DATING_RULES = [
    "Search-result snippets blend years; the dateline on the article is the date.",
    "A hit that matches the month and day but not the year is a different year's event: leave it out, or label it \"background (DATE)\".",
    "A cause offered for a price move is dated inside the move window.",
    "no dated catalyst found for WINDOW",
]


@pytest.mark.parametrize("skill_name", sorted(RESEARCH_DATING_SKILLS))
def test_news_skills_carry_the_research_dating_block(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    assert "<research_dating>" in text and "</research_dating>" in text, f"{skill_name}: missing <research_dating> block"
    for rule in RESEARCH_DATING_RULES:
        assert rule in text, f"{skill_name}: missing research-dating rule: {rule}"


# Cash-account settlement discipline, pinned so the
# plugin cannot silently lose it again.
SETTLEMENT_RULES = [
    "Trust this field — it is DECLARED, not detected",
    "do NOT conclude \"margin\" because buying power exceeds cash",
    "**Freeriding** — buying a security and then paying for it with proceeds from selling that same security.",
    "**Good faith violation**",
    "**Cash liquidation violation**",
    "sell first and let the proceeds settle (T+1) before buying",
    "Do not refuse the trade",
]


def test_portfolio_analysis_carries_settlement_rules() -> None:
    text = _skill_md_path("portfolio-analysis").read_text()
    assert "Settlement rules" in text, "portfolio-analysis: missing settlement rules section"
    for rule in SETTLEMENT_RULES:
        assert rule in text, f"portfolio-analysis: missing settlement rule: {rule}"


GATE_STEP = "Only when the trade-journal skill is installed (it is an optional extra): running the trading skill's `gate.py <symbol> <BUY|SELL> <qty> [--limit X]` and showing its `decision` and `reasons`."


@pytest.mark.parametrize("skill_name", sorted(TRADING_PROTOCOL_SKILLS))
def test_trading_protocol_starts_with_the_discipline_gate(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    assert GATE_STEP in text, f"{skill_name}: trading protocol is missing the gate step"
    assert text.index(GATE_STEP) < text.index("Running the trading skill's `preview-order.py"), f"{skill_name}: the gate step must come before preview"


FORBIDDEN_TERMS = ["Cognito", "refresh token", "/api/v1/brokerage", ".sh"]


def _all_python_scripts() -> list[Path]:
    return sorted(SKILLS_ROOT.glob("*/scripts/*.py"))


@pytest.mark.parametrize("script", _all_python_scripts(), ids=lambda p: str(p.relative_to(SKILLS_ROOT)))
def test_python_script_contract(script: Path) -> None:
    text = script.read_text()
    assert text.lstrip().startswith(('"""', '#!/usr/bin/env python3')), f"{script}: missing shebang/docstring"
    doc_start = text.index('"""')
    doc = text[doc_start + 3 : text.index('"""', doc_start + 3)]
    assert doc.lstrip().startswith("Usage:") or "stdin" in doc, f"{script}: docstring must start with Usage: or describe stdin"
    assert 'if __name__ == "__main__":' in text, f"{script}: missing main guard"
    assert script.stat().st_mode & stat.S_IXUSR, f"{script} is not executable"
    assert subprocess.run([sys.executable, "-m", "py_compile", str(script)], capture_output=True).returncode == 0


SCRIPTLESS_SKILLS: set[str] = set()


@pytest.mark.parametrize("skill_name", [n for n in SKILL_NAMES if n not in SCRIPTLESS_SKILLS])
def test_skill_md_uses_invocation_contract(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    assert INVOCATION + skill_name + "/scripts/" in text, f"{skill_name}: must invoke scripts via the SNAPTRADE_PY contract"


@pytest.mark.parametrize("skill_name", sorted(TRADING_PROTOCOL_SKILLS))
def test_safety_rules_verbatim(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    for rule in SAFETY_RULES:
        assert rule in text, f"{skill_name}: missing safety rule: {rule}"


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_no_hosted_app_infrastructure_references(skill_name: str) -> None:
    text = _skill_md_path(skill_name).read_text()
    for term in FORBIDDEN_TERMS:
        assert term not in text, f"{skill_name}: still references {term!r}"


def test_no_shell_wrapper_scripts() -> None:
    assert not list(SKILLS_ROOT.glob("*/scripts/*.sh")), "shell wrappers must be removed"


MAX_DESCRIPTION_CHARS = 260


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_description_fits_the_routing_budget(skill_name: str) -> None:
    """Every description is always in context; short ones keep the skill listing under budget."""
    frontmatter, _ = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    n = len(frontmatter["description"])
    assert n <= MAX_DESCRIPTION_CHARS, f"{skill_name}: description is {n} chars (limit {MAX_DESCRIPTION_CHARS})"


CATALOG = PLUGIN_ROOT / "skills.json"
ALWAYS_INSTALLED_SKILLS = {"setup"}


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text())["skills"]


def test_catalog_exists_and_parses() -> None:
    assert CATALOG.is_file(), "missing skills.json catalog"
    assert isinstance(_catalog(), list)


def test_catalog_names_match_skill_directories() -> None:
    on_disk = sorted(p.name for p in SKILLS_ROOT.iterdir() if (p / "SKILL.md").is_file())
    on_disk = [n for n in on_disk if n not in ALWAYS_INSTALLED_SKILLS]
    listed = sorted(s["name"] for s in _catalog())
    assert listed == on_disk, f"catalog/disk mismatch: {set(listed) ^ set(on_disk)}"


def test_catalog_entries_are_well_formed() -> None:
    names = {s["name"] for s in _catalog()}
    for s in _catalog():
        assert s["family"], f"{s['name']}: empty family"
        assert set(s["requires"]) <= {"brokerage", "edgar"}, f"{s['name']}: bad requires {s['requires']}"
        for dep in s["depends_on"]:
            assert dep in names, f"{s['name']} depends on unknown skill {dep}"
            assert dep != s["name"], f"{s['name']} depends on itself"


def test_catalog_brokerage_flag_matches_router_imports() -> None:
    """A skill hard-requires the brokerage Hub iff the catalog says so.

    ``router.load(`` raises when nothing is configured, so a script calling it
    cannot run without brokerage credentials. A script that only imports
    ``router`` for ``router.try_load()`` (best-effort, degrades to Yahoo) does
    not make its skill brokerage-backed.
    """
    for s in _catalog():
        scripts = list((SKILLS_ROOT / s["name"] / "scripts").glob("*.py"))
        requires_router = any("router.load(" in p.read_text() for p in scripts)
        assert requires_router == ("brokerage" in s["requires"]), (
            f"{s['name']}: catalog requires={s['requires']} but router.load( use is {requires_router}"
        )


SETUP_SKILL = SKILLS_ROOT / "setup" / "SKILL.md"


def test_setup_skill_frontmatter_and_no_secrets_rule() -> None:
    assert SETUP_SKILL.is_file(), "missing skills/setup/SKILL.md"
    frontmatter, body = _parse_frontmatter(SETUP_SKILL.read_text())
    assert frontmatter.get("name") == "setup"
    assert frontmatter.get("description") and len(frontmatter["description"]) <= MAX_DESCRIPTION_CHARS
    assert "allowed-tools" not in frontmatter
    assert "install.js" in body and "--json" in body
    assert "install.py" not in body
    assert "never" in body.lower() and "secret" in body.lower(), "setup skill must forbid secrets in chat"


def test_install_script_is_a_self_contained_node_bundle() -> None:
    """install.js is generated from installer/src and must run with nothing but Node."""
    path = PLUGIN_ROOT / "install.js"
    assert path.is_file() and os.access(path, os.X_OK)
    text = path.read_text()
    head = text.splitlines()[:6]
    assert head[0] == "#!/usr/bin/env node"
    assert any("GENERATED FILE" in line for line in head)
    # A bundle imports only Node built-ins; a bare package import means the build was not bundled.
    imports = re.findall(r'^import\s+(?:[^;]*?\bfrom\s+)?"([^"]+)"', text, re.MULTILINE)
    bare = {m for m in imports if not m.startswith("node:")}
    assert not bare, f"install.js must be self-contained: found imports of {sorted(bare)}"
    assert not (PLUGIN_ROOT / "install.py").exists(), "install.py was replaced by install.js"


def test_installer_bundle_carries_the_package_version() -> None:
    pkg = json.loads((PLUGIN_ROOT / "installer" / "package.json").read_text())
    assert pkg["version"] in (PLUGIN_ROOT / "install.js").read_text()


def test_debt_tracker_flags_are_documented_in_skill_md() -> None:
    """Every debtpicture.py FLAG_ORDER name must be explained in plain words in SKILL.md,
    so a new flag can't ship without being documented for the model that reads them."""
    import importlib.util

    script_path = SKILLS_ROOT / "debt-tracker" / "scripts" / "debtpicture.py"
    spec = importlib.util.spec_from_file_location("debtpicture_flag_check", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    flags = module.FLAG_ORDER
    assert flags, "debtpicture.py FLAG_ORDER is empty"

    plugin_text = _skill_md_path("debt-tracker").read_text()
    for flag in flags:
        assert flag in plugin_text, f"debt-tracker: SKILL.md is missing flag {flag!r}"


def test_order_protocols_run_the_gate_only_with_the_journal_extra() -> None:
    for name in ("portfolio-analysis", "trading"):
        lines = (SKILLS_ROOT / name / "SKILL.md").read_text().splitlines()
        step = next(line for line in lines if "gate.py <symbol>" in line and line.lstrip().startswith("1."))
        assert "trade-journal" in step and "installed" in step and "SKIP" in step, name
    for rule in (SKILLS_ROOT / "trade-journal" / "SKILL.md", SKILLS_ROOT / "financial-education" / "SKILL.md", PLUGIN_ROOT / "hooks" / "follow-ups.md"):
        text = rule.read_text()
        assert "optional extra" in text and "turn off" in text, rule
    setup = SETUP_SKILL.read_text()
    assert "--extras" in setup and "follow_ups" in setup and "twenty-one" not in setup


# ---------------------------------------------------------------------------
# One layout for every skill (docs/skill-style.md): background, then what to do, in order.
# ---------------------------------------------------------------------------

ALL_SKILLS = SKILL_NAMES + ["setup"]
SECTION_ORDER = ["## Background", "## Scripts", "## Steps", "## Reply format", "## Rules"]
MAX_PROSE_LINE = 400
ALLOWED_TAGS = {"<research_dating>", "</research_dating>"}


def _prose_lines(body: str) -> list[tuple[int, str]]:
    """(line number, line) for every line outside a code fence that is not a table row."""
    out, fenced = [], False
    for n, line in enumerate(body.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced and not line.lstrip().startswith("|"):
            out.append((n, line))
    return out


@pytest.mark.parametrize("skill_name", ALL_SKILLS)
def test_sections_run_from_background_to_rules(skill_name: str) -> None:
    _, body = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    headings = [line for _, line in _prose_lines(body) if line.startswith("## ")]
    unknown = [h for h in headings if h not in SECTION_ORDER]
    assert not unknown, f"{skill_name}: only {SECTION_ORDER} are allowed at level 2, found {unknown}"
    assert headings == [h for h in SECTION_ORDER if h in headings], f"{skill_name}: sections out of order or repeated: {headings}"
    assert "## Steps" in headings and headings[-1] == "## Rules", f"{skill_name}: needs ## Steps, and ## Rules last"
    assert body.strip() and not body.lstrip().startswith("#"), f"{skill_name}: open with a plain sentence saying what the skill does"


@pytest.mark.parametrize("skill_name", ALL_SKILLS)
def test_no_wall_of_text(skill_name: str) -> None:
    _, body = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    long = [(n, len(line)) for n, line in _prose_lines(body) if len(line) > MAX_PROSE_LINE]
    assert not long, f"{skill_name}: lines over {MAX_PROSE_LINE} characters (line, length): {long}; split into bullets, steps or a table"


@pytest.mark.parametrize("skill_name", ALL_SKILLS)
def test_no_section_tags(skill_name: str) -> None:
    _, body = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    tags = [line.strip() for _, line in _prose_lines(body) if re.fullmatch(r"</?[a-z_]+>", line.strip())]
    assert set(tags) <= ALLOWED_TAGS, f"{skill_name}: use the standard headings, not tags: {sorted(set(tags) - ALLOWED_TAGS)}"


@pytest.mark.parametrize("skill_name", ALL_SKILLS)
def test_commands_are_in_bash_fences(skill_name: str) -> None:
    _, body = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    loose = [n for n, line in _prose_lines(body) if line.lstrip().startswith('"${SNAPTRADE_PY')]
    assert not loose, f"{skill_name}: commands outside a fenced block at lines {loose}"


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_compliance_bullets_sit_in_rules(skill_name: str) -> None:
    _, body = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    assert body.index("## Rules") < body.index("Never provide buy, sell, or hold recommendations"), f"{skill_name}: the compliance bullets belong under ## Rules"


@pytest.mark.parametrize("skill_name", ALL_SKILLS)
def test_description_says_what_and_when_in_the_third_person(skill_name: str) -> None:
    frontmatter, _ = _parse_frontmatter(_skill_md_path(skill_name).read_text())
    description = frontmatter["description"]
    assert "Use when" in description, f"{skill_name}: description must say when to use the skill ('Use when ...')"
    assert ": " not in description, f"{skill_name}: a colon followed by a space breaks strict YAML"
    assert len(description) <= MAX_DESCRIPTION_CHARS, f"{skill_name}: description is {len(description)} characters"
    assert not re.match(r"(I|You|We)\b", description), f"{skill_name}: write the description in the third person"
