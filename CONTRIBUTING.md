# Contributing

Issues and pull requests are welcome. For anything larger than a fix, open an issue first so we can agree on the shape before you write it.

## Development setup

```bash
git clone https://github.com/bshurick/second-opinion
cd second-opinion
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests -q
```

To try your checkout in Claude Code without installing it: `claude --plugin-dir "$PWD"`.

The installer is TypeScript under `installer/`; `install.js` is its committed build output so users can clone and run it without `npm install`. After any change under `installer/src`:

```bash
cd installer && npm ci && npm run check   # typecheck, tests, rebuild ../install.js
```

CI fails if the committed `install.js` does not match a fresh build.

## Ground rules

- **Numbers come from scripts.** Each skill's calculations live in Python under `skills/<name>/scripts/`, print one JSON object, and use the exit codes in [docs/scripts.md](docs/scripts.md). The model explains results; it does not compute them.
- **Analysis, not advice.** Skills never tell the user to buy, sell, or hold. `tests/test_skills_structure.py` checks the compliance block in every SKILL.md.
- **Orders need a human yes.** Never weaken the preview-then-confirm protocol or the PreToolUse gate in `hooks/gate.sh`.
- **No real personal data.** Fixtures, screenshots, and examples must be invented. The README screenshots come from `docs/samples/`.
- **Skill structure.** Every SKILL.md follows one layout (background, scripts, steps, reply format, rules), written so a small model can follow it. [docs/skill-style.md](docs/skill-style.md) is the guide and `skills/watchlist/SKILL.md` the example; `tests/test_skills_structure.py` enforces it. New scripts are executable (`chmod +x`).
