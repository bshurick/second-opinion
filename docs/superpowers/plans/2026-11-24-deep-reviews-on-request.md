# Deep Reviews On Request Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No session rule, skill or doc starts or offers a deep review; the four reviews run only when the person asks for one by name.

**Architecture:** Wording changes in the depth rule, four `SKILL.md` files, get-started and the docs, plus one constant (`DEEP_PATHS`). Structure tests pin the new wording. No review script changes.

**Tech Stack:** Markdown skill files, Python 3, pytest (`python3 -m pytest`).

**Spec:** `docs/superpowers/specs/2026-11-24-deep-reviews-on-request-design.md`

## Global Constraints

- The four reviews: portfolio-analysis, real-estate, tax-aware, trade-review.
- Deep valuations, the deep picker and pick re-checks keep their behaviour.
- `exposure.py`, the four `*_store.py` scripts and the renderers are not edited; `rerun_due` stays in their output.
- No new setting.
- No softer pitch replaces the old one: a re-check states what changed and stops.
- Plugin writing rules apply to every edited line: active voice, sentences under about 25 words, no "recommend", "advise", "should" or "suggest" for financial actions.
- Commit only when the owner asks. Each task ends at passing tests, not at a commit.

## Review Focus

- A person at deep depth asks "how is my portfolio": the reply holds the brief and no review re-check. Pinned by Task 1's hook test.
- A person asks "run a deep review of my portfolio": the run still starts, with its cost line. Pinned by Task 2's test that the run steps remain.
- A person asks "re-check my deep review" and `rerun_due` is true: the reply gives the reasons and no pitch. Pinned by Task 2.
- `settings.py show` at deep depth lists only the skills that follow depth. Pinned by Task 1's `DEEP_PATHS` test.
- A person asks tax-aware to compare multi-year plans without the words "deep review": one line with the size, one question, no silent run. Pinned by Task 2.

---

### Task 1: The depth rule and `DEEP_PATHS`

**Files:**
- Modify: `hooks/depth-deep.md`
- Modify: `lib/second_opinion/settings.py:38-46`
- Test: `tests/test_hook.py` (after `test_depth_rule_wording`), `tests/test_settings.py:197-200`

- [ ] **Step 1: Write the failing tests**

In `tests/test_hook.py`:

```python
def test_depth_rule_starts_no_review() -> None:
    text = DEPTH_RULE.read_text()
    assert "run a new deep review" not in text and "deep review's re-check" not in text
    assert "runs only when the person asks for one by name" in text
```

In `tests/test_settings.py`, replace `test_deep_paths_cover_every_skill_with_deep_references`:

```python
ON_REQUEST_REVIEWS = {"portfolio-analysis", "real-estate", "tax-aware", "trade-review"}


def test_deep_paths_are_the_deep_skills_that_follow_depth():
    found = {p.parent.parent.name for p in SKILLS.glob("*/references/*.md")
             if p.name.startswith("deep-") or p.name == "picker-roles.md"}
    assert ON_REQUEST_REVIEWS <= found
    assert set(settings.DEEP_PATHS) == found - ON_REQUEST_REVIEWS == {"valuation", "stock-screener"}
```

- [ ] **Step 2: Run them and see both fail**

Run: `python3 -m pytest tests/test_hook.py::test_depth_rule_starts_no_review tests/test_settings.py -q`

- [ ] **Step 3: Edit `hooks/depth-deep.md`**

Delete the line that begins "- Portfolio, property, trade and tax-plan questions:". Replace the "Not covered" line with:

```
- Not covered: quotes, ratios, filing sections, option chains and a screen's candidate list are the same as in standard depth. A portfolio, property, trade or tax-plan deep review runs only when the person asks for one by name, at either depth, and so does its re-check. A skill with no deep path answers as it always has.
```

- [ ] **Step 4: Edit `DEEP_PATHS`**

Keep the `valuation` and `stock-screener` entries only. Change the comment above it to: `# Skills that follow the depth setting, and what deep means in each. The four deep reviews run on request at either depth.`

- [ ] **Step 5: Run the hook, settings and settings-script tests**

Run: `python3 -m pytest tests/test_hook.py tests/test_settings.py tests/test_scripts_settings.py -q`
Expected: all pass.

### Task 2: The four review skills

**Files:**
- Modify: `skills/portfolio-analysis/SKILL.md` (lines 312-314, 345)
- Modify: `skills/real-estate/SKILL.md` (lines 77, 102, 127)
- Modify: `skills/tax-aware/SKILL.md` (lines 84, 107-109, 130)
- Modify: `skills/trade-review/SKILL.md` (lines 79, 95-97, 120)
- Test: `tests/test_skills_structure.py` (after `test_deep_skills_name_the_depth_rule`)

- [ ] **Step 1: Write the failing test**

```python
REVIEW_SKILLS = ("portfolio-analysis", "real-estate", "tax-aware", "trade-review")


def test_deep_reviews_run_on_request_only():
    for name in REVIEW_SKILLS:
        text = _skill_md_path(name).read_text()
        assert "a deep review is available" not in text, name
        assert "depth rule makes the deep review the default" not in text, name
        assert "say a new deep review would" not in text, name
        assert "Run this only when the person asks for a deep review by name." in text, name
        assert "give `rerun_reasons` as what changed since the review. Add nothing about a new review." in text, name
        assert "Tell the person it has started and what it costs" in text or "subagents" in text, name
    for name in ("tax-aware", "trade-review"):
        assert "say so in one line with the run's size, and ask once before starting" in _skill_md_path(name).read_text(), name
```

- [ ] **Step 2: Run it and see it fail**

Run: `python3 -m pytest tests/test_skills_structure.py::test_deep_reviews_run_on_request_only -q`

- [ ] **Step 3: Edit the run condition in each skill**

| Skill | Heading becomes | Line under it becomes |
|---|---|---|
| portfolio-analysis | `**The user asks for a deep review**` | `Run this only when the person asks for a deep review by name. Answer any other question, including what they depend on most, from the holdings case.` |
| real-estate | unchanged | `Run this only when the person asks for a deep review by name.` |
| tax-aware | `**The user asks for a deep review**` | `Run this only when the person asks for a deep review by name. When they ask to compare multi-year plans without naming it, only this review can answer: say so in one line with the run's size, and ask once before starting.` |
| trade-review | `**The user asks for a deep review of their decisions**` | `Run this only when the person asks for a deep review by name. When they ask which trades were skill and which were luck without naming it, only this review can answer: say so in one line with the run's size, and ask once before starting.` |

- [ ] **Step 4: Delete the three standalone offer lines**

`skills/real-estate/SKILL.md:77`, `skills/tax-aware/SKILL.md:84`, `skills/trade-review/SKILL.md:79`, each with its surrounding blank line. The portfolio-analysis offer went with Step 3.

- [ ] **Step 5: Replace re-check step 4 in all four skills**

`4. If `rerun_due` is true, give `rerun_reasons` as what changed since the review. Add nothing about a new review.`

- [ ] **Step 6: Run the structure tests**

Run: `python3 -m pytest tests/test_skills_structure.py -q`
Expected: all pass, including `test_deep_skills_name_the_depth_rule`, which now loops over two skills.

### Task 3: get-started

**Files:**
- Modify: `skills/get-started/SKILL.md:199`, `:264`
- Test: `tests/test_skills_structure.py:667`

- [ ] **Step 1: Change the test first**

Replace `assert "research subagents" in table and "up to an hour" in table` with:

```python
    assert "research subagents" in table and "review" not in table[table.index("| Depth |"):table.index("| Approach |")]
```

Run: `python3 -m pytest tests/test_skills_structure.py -q -k started` and see it fail.

- [ ] **Step 2: Edit the Depth row (line 199)**

Question: `"How thorough should valuations and stock picks be?"`. Deep choice: `**Deep**: every valuation and pick sends 5 to 40 research subagents through filings and news; a run takes minutes, with far more of your Claude usage; it asks first before starting more than 3 deep valuations.` The Standard choice and the saved command stay.

- [ ] **Step 3: Edit line 264**

Remove ` (a portfolio review can take up to an hour)`.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_skills_structure.py -q`. Expected: all pass.

### Task 4: Docs and changelog

**Files:**
- Modify: `docs/configuration.md:50`, `:53`
- Modify: `README.md:149-160`, `:196`
- Modify: `docs/deep-research.md` (intro, modes table, re-checks)
- Modify: `docs/examples.md:14`, `:22`, `:31`
- Modify: `CHANGELOG.md` (Unreleased)

- [ ] **Step 1: `docs/configuration.md`**

Row: `| Reviews (portfolio, property, trades, tax plans) | Deep run on request only | Deep run on request only |`. In the paragraph, replace the "Six skills have a deep path (…); the others answer as before." sentence with: `Two skills follow depth (valuation, stock-screener). The four deep reviews (portfolio-analysis, real-estate, tax-aware, trade-review) run only when you ask for one by name, at either depth. The other skills answer as before.`

- [ ] **Step 2: `README.md`**

"Six modes" becomes "Two modes". Delete the Portfolio review, Property review, Decision review and Tax plan comparison rows. Line 196 becomes `- [Deep research](docs/deep-research.md): deep valuation, the deep picker, their re-checks, and the reviews that run on request`.

- [ ] **Step 3: `docs/deep-research.md`**

- Intro: "Six modes" becomes "Two modes".
- Move the four review rows out of "The modes" into a new section placed after "Re-checks", headed `## Reviews on request`, with this lead-in: `Four reviews run only when you ask for one by name. No reply offers one and no setting starts one. Each takes 5 to 10 research subagents and up to an hour, and it describes what it finds without saying what to do.`
- Move the Portfolio, Property, Trades and Tax plans rows of the re-checks table under the same section, with the lead-in `A saved review can be re-measured on request, with no new research.`
- Under "Re-checks", the sentence "Each check says when a new run is due." applies to picks only; reword to `The picks check says when a new run is due.`
- "No calls" bullet stays.

- [ ] **Step 4: `docs/examples.md`**

Remove the three "Run a deep review…" prompts and "Re-check my deep review." from lines 14, 22 and 31, keeping the `·` separators well formed.

- [ ] **Step 5: `CHANGELOG.md`, top of Unreleased**

`- deep reviews: the portfolio, property, trade and tax-plan deep reviews run only when asked for by name. The depth setting now governs valuations and picks alone, no reply offers a review, and a re-check reports what changed without proposing a new run.`

- [ ] **Step 6: Find leftovers**

Run: `git grep -n -i "deep review is available\|depth rule makes the deep review\|Six modes\|six modes\|Deep run is the default" -- . ':!docs/superpowers'`
Expected: no output.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: all pass (`tests/test_readme_samples.py` reads the README).
