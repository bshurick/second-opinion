# How skills are written

Every `skills/<name>/SKILL.md` follows one layout, so that a small model can follow it as easily as a large one. `skills/watchlist/SKILL.md` is the reference example. `tests/test_skills_structure.py` enforces the parts marked **(tested)**.

## Contents
- Layout
- Frontmatter
- Writing rules
- What belongs in a reference file
- What to leave out

## Layout

Loose information first, then exactly what to do, in order. These level-2 headings, in this order, and no others **(tested)**:

| Heading | Holds | Required |
|---|---|---|
| (opening line, no heading) | One or two sentences: what the skill does and where it stops. | yes |
| `## Background` | What the model has to know before acting: where data lives, what the scripts fetch, units, terms the scripts use, limits, which other skill owns the neighbouring work. Facts, not actions. | when there is any |
| `## Scripts` | The commands in one fenced `bash` block **(tested)**, then a table of what each does, then a table of exit codes. | when the skill has scripts |
| `## Steps` | The procedure. Numbered, one action per step, in the order to do them. When requests differ, one bold case line per kind of request, each with its own numbered steps. | yes **(tested)** |
| `## Reply format` | The shape of the answer: ordered sections, field names from the script output, number formats. | when the skill has a fixed reply |
| `## Rules` | Hard rules: the skill's own first, then the shared compliance bullets verbatim. Always last **(tested)**. | yes **(tested)** |

Use `###` headings or bold lead-ins inside a section when it needs parts. Do not add other `##` headings.

## Frontmatter

- `name`: the directory name.
- `description`: third person, what the skill does and when to use it, with the words a user would say. It must contain "Use when" **(tested)**, stay at or under 260 characters **(tested)**, and contain no colon followed by a space **(tested)** (it breaks strict YAML). Name the neighbouring skill only when the two are easily confused.

## Writing rules

- One idea per bullet or step. No line of prose over 400 characters **(tested)**; tables and code blocks are exempt.
- Put choices in a table ("the user says" → "flag"; "exit code" → "what to show"), not in a sentence with semicolons.
- A step says what to run or write. The reason, when it is needed, is one short sentence after it.
- A condition comes first: "If `flags` is not empty, …".
- Name script output fields in backticks exactly as the script prints them.
- Use one term for one thing throughout the file.
- Commands go in fenced `bash` blocks, each starting with `"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/` **(tested)**.
- No section tags such as `<protocol>`. The one exception is `<research_dating>`, which the tests look for by name; it sits inside `## Rules`.
- No dates, "measured on", "as of this year", or release history. A figure that goes stale belongs in a reference file with a "verify the current figure" note.

## What belongs in a reference file

Move material to `skills/<name>/references/<topic>.md` when it is long and only needed for some requests: formulas and their derivations, worked examples, a taxonomy, a long question-and-answer list.

- Link it from `SKILL.md` with the condition for reading it: "Read `references/x.md` before answering anything about Y."
- One level deep: a reference file never sends the reader to another reference file.
- Over 100 lines, it starts with a `## Contents` list naming every `##` section **(tested)**.
- Register it in `REFERENCE_FILES` in `tests/test_skills_structure.py` **(tested)**.

## What to leave out

- What any capable model already knows: what a P/E ratio is, how a library works, why diversification matters.
- A "role" paragraph that restates the description.
- The same rule said twice in different words.
- Advice about tone that the shared compliance bullets already cover.

Keep everything that is specific to this plugin: script behaviour, field names, flags, thresholds, traps found in real use, the order things must happen in, and every safety rule.
