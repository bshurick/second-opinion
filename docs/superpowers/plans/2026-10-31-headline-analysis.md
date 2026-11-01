# Headline Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A validated, model-written headline card at the top of Portfolio Snapshot and Market Flows.

**Architecture:** A new stdlib module, `lib/second_opinion/summary_card.py`, validates the summary JSON and renders the card. Each `render.py` takes `--summary FILE` and fills a `{{SUMMARY}}` placeholder in its body. The model writes the text under rules in each `SKILL.md`.

**Tech Stack:** Python 3 stdlib, pytest, the `page.py` page toolkit.

**Spec:** `docs/superpowers/specs/2026-10-31-headline-analysis-design.md`

## Global Constraints

- Word limits: `headline` 20, `stands_out` 90, `look_into` 90, `for_you` 70, as named constants.
- `headline`, `stands_out` and `look_into` are required. `for_you` is optional. Unknown keys, non-strings and empty strings are rejected.
- Forbidden verbs in any field are rejected: `\b(recommend\w*|advis\w*|should|suggest\w*)\b`, case-insensitive, one shared definition.
- A broken summary exits 2 with an `error` naming the rule (`InvalidInput`).
- Without `--summary`, a page's output is unchanged apart from the new Flags id.
- All text is HTML-escaped. The only markup is `[label](target)`, in `look_into` only, to a section id the page declares.
- Links scroll with `scrollIntoView` from a click handler and never change `location.hash`.
- Pages stay self-contained and work in both themes through existing CSS variables.
- Fixtures use invented data only.

## Review Focus

1. A summary containing `<script>` or `</section>` text: it displays as literal text and cannot break the page.
2. A `--summary` path that is missing, not JSON, or a JSON list: exit 2, with no page written.
3. A link's target syntax must not count toward the word limit; only its label does.
4. `portfolio-last-check.json` missing, corrupt, `partial: true`, from yesterday, or with a UTC timestamp that crosses midnight local time: the gate compares local dates, and any doubt drops `for_you` instead of failing the render.
5. A link to a section hidden on this run, such as `compare-card`: clicking does nothing harmful.

---

### Task 1: Summary validation and card rendering

**Files:**
- Create: `lib/second_opinion/summary_card.py`
- Create: `tests/test_summary_card.py`
- Modify: `tests/test_skills_structure.py:76` (import `FORBIDDEN_VERB_RE` instead of defining it)

**Interfaces:**
- Produces, all in `second_opinion.summary_card`:
  - `FORBIDDEN_VERB_RE: re.Pattern`
  - `load(path: str, targets: Iterable[str]) -> dict[str, str]`: reads and validates; raises `InvalidInput`.
  - `card_html(summary: dict[str, str] | None) -> str`: `""` for `None`.
  - `full_read_today(now: datetime | None = None) -> bool`: reads `config.data_dir() / "portfolio-last-check.json"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_summary_card.py`

```python
GOOD = {"headline": "Tech leads a drop", "stands_out": "Tech fell 4.9%.", "look_into": "[Sectors](sec-card): the gap."}
TARGETS = ["sec-card", "flags-section"]

def test_load_returns_a_valid_summary(tmp_path): ...       # == GOOD
@pytest.mark.parametrize("missing", ["headline", "stands_out", "look_into"])
def test_load_rejects_a_missing_required_field(tmp_path, missing): ...   # InvalidInput naming the field
@pytest.mark.parametrize("field,limit", [("headline", 20), ("stands_out", 90), ("look_into", 90), ("for_you", 70)])
def test_load_enforces_word_limits_at_the_boundary(tmp_path, field, limit): ...   # limit words pass, limit+1 raises
def test_word_limit_counts_a_link_label_not_its_target(tmp_path): ...    # 89 words + "[Sectors](sec-card)" passes
@pytest.mark.parametrize("word", ["recommend", "Recommends", "advise", "adviser", "SHOULD", "suggesting"])
def test_load_rejects_forbidden_verbs_in_any_field(tmp_path, word): ...  # each of the four fields
def test_load_rejects_unknown_key_non_string_and_empty(tmp_path): ...
def test_load_rejects_a_link_to_an_undeclared_section(tmp_path): ...
def test_load_rejects_a_link_outside_look_into(tmp_path): ...
@pytest.mark.parametrize("content", ["not json", "[1]"])
def test_load_rejects_a_bad_file(tmp_path, content): ...
def test_load_rejects_a_missing_file(tmp_path): ...
def test_card_html_is_empty_for_none(): assert card_html(None) == ""
def test_card_html_escapes_text():  # "<script>x</script>" in stands_out -> "&lt;script&gt;" present, "<script>" absent
def test_card_html_renders_a_link_as_a_scroll_target():  # 'data-summary-target="sec-card"' present, no 'href="#'
def test_card_html_folds_for_you_and_omits_it_when_absent():  # "<details" and "What this means for you" only when given
def test_card_labels_the_two_paragraphs():  # "What stands out", "What to look into"
def test_card_is_exempt_from_the_page_help_button():  # 'data-help="none"' present
def test_full_read_today_true_for_a_full_read_today(monkeypatch, tmp_path): ...  # SECOND_OPINION_DATA=tmp_path
@pytest.mark.parametrize("record", [None, "not json", {"as_of": "<yesterday>", "partial": False}, {"as_of": "<today>", "partial": True}, {"partial": False}, {"as_of": "junk", "partial": False}])
def test_full_read_today_false_when_in_doubt(monkeypatch, tmp_path, record): ...
def test_full_read_today_compares_local_dates(monkeypatch, tmp_path):
    # TZ=America/Los_Angeles; as_of 2026-11-01T02:00:00+00:00 is Oct 31 locally; now = Oct 31 20:00 local -> True
    ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_summary_card.py -q`
Expected: FAIL with `ModuleNotFoundError: second_opinion.summary_card`

- [ ] **Step 3: Implement `lib/second_opinion/summary_card.py`** with the four interfaces. Link pattern: `\[([^\]]+)\]\(([a-z0-9-]+)\)`. The card is `<section class="card summary-card" data-help="none" id="summary-card">`, with the headline in a `<p class="summary-head">`, not an `h2`. Links render as `<a class="summary-link" role="button" tabindex="0" data-summary-target="ID">label</a>`.

- [ ] **Step 4: Point `tests/test_skills_structure.py` at the shared pattern**

- [ ] **Step 5: Run to verify they pass**

Run: `python3 -m pytest tests/test_summary_card.py tests/test_skills_structure.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lib/second_opinion/summary_card.py tests/test_summary_card.py tests/test_skills_structure.py
git commit -m "feat(page): validate and render the headline analysis card"
```

### Task 2: Card on Portfolio Snapshot

**Files:**
- Modify: `lib/second_opinion/page.py` (`CSS`, `JS`, docstring)
- Modify: `skills/portfolio-snapshot/scripts/render.py` (`BODY`, `build`, `main`, docstring)
- Test: `tests/test_scripts_snapshot.py`

**Interfaces:**
- Consumes: `summary_card.load`, `summary_card.card_html`.
- Produces: `build(snapshot: dict, summary: dict | None = None) -> str`; a `TARGETS` tuple in the Snapshot `render.py`: `headlines-card, accounts-card, alloc-card, sector-card, movers-card, holdings-card, events-card, compare-card, flags-section`; `id="flags-section"` on the Flags section; a delegated click handler in `page.JS` that any page with the card can use.

- [ ] **Step 1: Write the failing tests**

```python
def test_snapshot_page_shows_the_card_above_the_tiles(capsys, tmp_path): ...  # html.index('summary-card') < html.index('id="headlines-card"')
def test_snapshot_page_without_summary_has_no_card(capsys, tmp_path): ...      # 'id="summary-card"' absent, no "{{SUMMARY}}" left
def test_snapshot_page_keeps_for_you_with_no_read_check(capsys, tmp_path, monkeypatch): ...  # shown with an empty data dir
def test_snapshot_page_rejects_a_bad_summary_without_writing(capsys, tmp_path): ...  # rc == 2, out file absent
def test_page_js_scroll_handler_ignores_a_missing_target():
    # page.JS contains "data-summary-target", "scrollIntoView", and no assignment to location.hash in the handler
    ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_scripts_snapshot.py -q -k "card or summary or scroll_handler or for_you"`
Expected: FAIL (`--summary` is an unknown argument)

- [ ] **Step 3: Implement.** Add `{{SUMMARY}}` after `<div id="explain"></div>` in `BODY`, replaced in `build`. `main` loads the summary before writing. In `page.CSS`, add a left accent border with `var(--s1)` and `.summary-head`. In `page.JS`, add a delegated `click` and Enter-key listener: `const el = document.getElementById(id); if (el && !el.hidden) el.scrollIntoView({behavior: 'smooth'})`.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_scripts_snapshot.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/second_opinion/page.py skills/portfolio-snapshot/scripts/render.py tests/test_scripts_snapshot.py
git commit -m "feat(portfolio-snapshot): headline analysis card"
```

### Task 3: Card on Market Flows, with the holdings gate

**Files:**
- Modify: `skills/market-analysis/scripts/render.py`
- Test: `tests/test_scripts_market.py`

**Interfaces:**
- Consumes: `summary_card.load`, `card_html`, `full_read_today`.
- Produces: `build(flows, indices, summary=None) -> str`; a `TARGETS` tuple: `idx-card, pos-card, sec-card, etf-card, cash-card, short-card, flags-section`; a `for_you_dropped` key in the printed JSON, present only when dropped.

- [ ] **Step 1: Write the failing tests**

```python
def test_market_page_shows_the_card_above_the_tiles(...): ...          # html.index('summary-card') < html.index('id="tiles"')
def test_market_page_without_summary_has_no_card(...): ...
def test_market_page_keeps_for_you_after_a_full_read_today(...): ...   # text present, no for_you_dropped
def test_market_page_drops_for_you_without_a_full_read_today(...):
    # empty data dir: rc 0; for_you text NOT anywhere in the HTML, including embedded data;
    # out["for_you_dropped"] == "no full portfolio read today"
    ...
def test_market_page_rejects_a_link_to_a_snapshot_only_section(...): ...  # [x](holdings-card) -> rc 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_scripts_market.py -q -k "market_page"`
Expected: FAIL (`--summary` is an unknown argument)

- [ ] **Step 3: Implement.** As Task 2, with `{{SUMMARY}}` after `<div id="explain"></div>`. Add `id="flags-section"` to the Flags section. In `go`, when `for_you` is present and `full_read_today()` is false, remove it before `card_html` and set `for_you_dropped`.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_scripts_market.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/market-analysis/scripts/render.py tests/test_scripts_market.py
git commit -m "feat(market-analysis): headline analysis card, holdings only after a read today"
```

### Task 4: Skill instructions, docs and a live check

**Files:**
- Modify: `skills/market-analysis/SKILL.md`, `skills/portfolio-snapshot/SKILL.md`
- Modify: `skills/portfolio-snapshot/references/how-figures-are-built.md`, `docs/scripts.md` if it lists render flags, `CHANGELOG.md`
- Test: `tests/test_skills_structure.py`

**Interfaces:**
- Consumes: the `--summary` flag and `for_you_dropped` from Tasks 2 and 3.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("skill", ["market-analysis", "portfolio-snapshot"])
def test_summary_skills_require_the_card(skill):
    body = read_skill(skill)
    assert "--summary" in body and "What to look into" in body and "this run's script output" in body

def test_market_skill_guards_holdings_on_the_page():
    body = read_skill("market-analysis")
    assert "brief.py --no-headlines" in body and "get_artifact" in body and "for_you_dropped" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_skills_structure.py -q -k "summary_skills or guards_holdings"`
Expected: FAIL

- [ ] **Step 3: Edit both skills, using the spec's text for the shared writer rules, each page's "what to look for" list, and the chat replies.**
  - Market Flows steps: run `indices.py` and `flows.py`; run `brief.py --no-headlines`; check `get_artifact` for the page's read mode; write the summary, with `for_you` only if the read succeeded and the page is new or `owner`; render with `--summary`; publish.
  - Flows page reply: the headline replaces item 3; the sentence on what the picture cannot show stays; one line when `for_you` was left out.
  - Snapshot: the `No commentary...` rule now allows the card and only the card. The reply gains the headline line after the link, and Headlines and Flags stay.
  - Both fallbacks: the whole summary first, with its limits in the skill text.

- [ ] **Step 4: Add the CHANGELOG entry and the reference notes**

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest tests -q`
Expected: all pass

- [ ] **Step 6: Live check.** Render both pages from this session's `snapshot.json`, `flows.json` and `indices.json` with a real summary, and open them in Chrome in both themes. Confirm that the card sits at the top, stays small against the tiles, the links scroll, and the fold opens.

- [ ] **Step 7: Commit**

```bash
git add skills/market-analysis/SKILL.md skills/portfolio-snapshot/SKILL.md skills/portfolio-snapshot/references/how-figures-are-built.md docs/scripts.md CHANGELOG.md tests/test_skills_structure.py docs/superpowers/specs/2026-10-31-headline-analysis-design.md docs/superpowers/plans/2026-10-31-headline-analysis.md
git commit -m "docs(skills): write the headline analysis on both summary pages"
```
