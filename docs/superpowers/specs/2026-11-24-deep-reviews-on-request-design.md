# Deep reviews run on request only

Date: 2026-11-24. Size: a small change (wording in the depth rule, four skills and the docs; no script changes).

## Intent

A deep review costs 5 to 10 research subagents and up to an hour, and its result is a description with no next step: by rule it never says what to do. The plugin pushes it anyway. On 2026-11-24 a morning brief at deep depth reported "rerun due" because one fund had been sold, and the depth rule called for a new hour-long run. The plugin stops pushing deep reviews. They stay available to a person who asks for one by name.

This applies to all four deep reviews: portfolio-analysis (shared bets), real-estate (one property or market), tax-aware (multi-year plans) and trade-review (skill against luck).

## Goals

- No skill and no session rule starts a deep review, or a deep review re-check, unless the person asks for it.
- No reply offers a deep review unprompted.
- The docs describe deep reviews in one place, labelled as on request.

## Non-goals

- Deep valuations, the deep picker and pick re-checks keep their current behaviour at both depths.
- No script changes beyond one constant: `DEEP_PATHS` in `lib/second_opinion/settings.py` lists the skills that follow depth, so it drops the four review skills. `exposure.py`, `review_store.py`, `case_store.py`, `plan_store.py`, `decision_store.py` and the renderers stay as they are, including `rerun_due` in their output.
- No new setting. Depth stays `standard` or `deep`.
- Saved reviews stay on disk and can still be re-checked on request.

## Anti-goals

- Removing the feature. A person who types "run a deep review of my portfolio" gets the same run as today.
- A softer pitch in place of the old one ("you may want to refresh…"). The re-check states facts and stops.

## Approaches

1. **On request only (picked).** Remove the push in the depth rule, the offer lines and the rerun pitch; keep every script. Cheapest, reversible, and it matches the complaint: the cost comes from unprompted runs, not from the code existing.
2. **A separate `reviews` setting.** Split depth into valuations and reviews so a person can opt back in to automatic reviews. Rejected: it adds a setting and a get-started question for behaviour nobody has asked to keep.
3. **Remove the deep reviews.** Rejected: it deletes four tested flows and their saved results, and the open question is their value, which on-request use can still answer.

## The change

**Depth rule (`hooks/depth-deep.md`).**
- Delete the line "Portfolio, property, trade and tax-plan questions: give the scripted answer, then the saved deep review's re-check; run a new deep review when none is saved or a rerun is due."
- Add to the "Not covered" line that portfolio, property, trade and tax-plan deep reviews run only when the person asks for one by name, at either depth.

**The four skills** (`skills/portfolio-analysis`, `real-estate`, `tax-aware`, `trade-review`, each `SKILL.md`).
- Delete the standard-depth offer line ("a deep review is available and sends about N research subagents").
- Reword the run condition to: run this only when the person asks for a deep review by name. Drop "or for depth" and "or when the session's depth rule makes the deep review the default".
- portfolio-analysis: "what do I really depend on" without the words "deep review" is answered from the holdings case.
- tax-aware and trade-review: a question only the deep review can answer (comparing multi-year plans; skill against luck) gets one line saying so with the run's size, and one question before starting. This is the builder's call, not something the owner decided.
- Re-check step 4: when `rerun_due` is true, give `rerun_reasons` as what changed since the review, and stop. No sentence about what a new review would do.
- The cost line at the start of a run (subagents, searches, time) stays.
- Frontmatter descriptions keep "deep review" so a request by name still routes to the skill.

**get-started (`skills/get-started/SKILL.md`).** The depth question and the cost statement cover valuations and picks only. Remove "reviews" and "a portfolio review can take up to an hour".

**Docs.**
- `docs/configuration.md`: the Reviews row reads "deep run on request" at both depths; the paragraph under it loses any claim that reviews follow depth.
- `README.md` and `docs/examples.md`: remove deep-review rows and example prompts. `docs/deep-research.md` keeps them under one heading that says they run on request only.
- `CHANGELOG.md`: one entry.

**Tests.** Update `tests/test_hook.py` and any test that asserts the removed wording; add an assertion that the depth rule holds no instruction to run a review.

## Left to the builder

Exact wording, within the plugin's writing rules. Whether any other file repeats the removed wording (grep for "deep review is available", "depth rule makes the deep review" and "Reviews (portfolio").
