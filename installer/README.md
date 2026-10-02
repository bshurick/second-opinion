# Installer source

`../install.js` is built from this directory. Users never touch this folder; they run the committed bundle with `node install.js`.

The installer has two modes:

- **Copy** (a git checkout): copies the chosen skills and the shared library to `~/.claude/plugins/second-opinion`, links it into `~/.claude/skills`, and writes settings to the data dir.
- **Configure** (a `/plugin marketplace` install, detected when the plugin root is under `~/.claude/plugins/cache/` or `~/.claude/plugins/marketplaces/`, or forced with `--configure`): Claude Code owns the files and ships every skill, so the run writes only the data dir (`.env`, `installed.json`, venv), never copies or links, and missing brokerage keys are a warning, not an error.

Both modes write `.env` (0600) and `installed.json` to the data dir, `~/.claude/plugins/data/second-opinion` (or `$SECOND_OPINION_DATA`), which survives plugin updates. They still read the older locations (`<target>/.env`, `<target>/installed.json`, and the pre-rename `~/.claude/plugins/finance-analyst/`), move the pre-rename data dir `~/.claude/plugins/data/finance-analyst` once, and with `--yes` (or the guided review) remove the pre-rename copy and its `~/.claude/skills/finance-analyst` link so skills do not load twice.

What the guided interface looks like on a fresh checkout:

```
╭──────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✻ Second Opinion  for Claude Code • installer 1.0.0                                              │
│                                                                                                  │
│ Finance skills that work with your brokerage accounts, SEC filings and market data from local    │
│ Python scripts.                                                                                  │
│ This installer writes to exactly three places:                                                   │
│   plugin   ~/.claude/plugins/second-opinion                                                      │
│   data     ~/.claude/plugins/data/second-opinion                                                 │
│   link     ~/.claude/skills/second-opinion                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Stack

- TypeScript, Node 20+
- [Ink](https://github.com/vadimdemedes/ink) 6 + React 19 for the terminal interface (the same rendering model Claude Code uses)
- esbuild bundles everything, Ink and React included, into one ESM file with no runtime dependencies
- vitest + ink-testing-library for tests

## Layout

```
src/
  main.tsx          entry: parse flags, choose the guided interface or the plain driver
  cli.ts            flag parsing (node:util parseArgs) → Options
  engine/           everything that touches disk or spawns processes; no UI
    catalog.ts      skills.json + first sentence of each SKILL.md description
    selection.ts    dependency resolution (select adds deps, deselect drops dependents)
    env.ts          .env parse/render, precedence env < older .env files < data-dir .env < --env-file < flags
    python.ts       find a Python ≥ 3.10 with the venv module
    runner.ts       Runner interface; ProcessRunner spawns and logs; tests use a fake
    deps.ts         venv + pip with the requirements stamp shared with hooks/session-start.sh
    materialize.ts  build the target in a sibling dir and swap atomically; write .env + installed.json
    link.ts         ~/.claude/skills symlink and uninstall
    legacy.ts       find and remove the pre-rename finance-analyst copy and link
    paths.ts        install, link and data paths; marketplace detection; one-time data-dir move
    smoke.ts        imports / dcf / connect-status checks
    installer.ts    plan → execute, emitting step events
  drivers/plain.ts  line output for --json, --plain, CI, or a non-terminal
  ui/               Ink components and screens; App.tsx is the state machine
test/               one file per module; helpers.ts has the mini plugin root and FakeRunner
```

The engine emits `step:start / step:log / step:done / step:skip / step:fail / warning` events. The Progress screen and the plain driver are both consumers, so the two front ends cannot drift.

## Commands

```bash
npm install          # once
npm test             # vitest, network-free, ~1s
npm run typecheck
npm run build        # writes ../install.js — commit it with your change
npm run check        # all three
```

Run the source without building: `npx tsx src/main.tsx` is not wired up; build and run `node ../install.js` instead (the build takes under a second). `npm run dev` rebuilds on every save.

## Conventions

- Secrets never appear in output, logs, `--json`, or test fixtures beyond obvious placeholders.
- Every failure is an `InstallError(message, hint)`; drivers print `install.js: <message> — <hint>` and exit 1. Bad flags exit 2.
- Anything that spawns a process goes through `Runner` so tests can substitute `FakeRunner`.
- The install contract (paths, `installed.json`, `.env` handling, JSON summary shape, exit codes) is what `skills/setup/SKILL.md`, `hooks/common.sh` and `lib/second_opinion/config.py` depend on; change it deliberately.
- Extras are opt-in everywhere: only `"<key>": true` in `installed.json` turns one on; a missing record means off.
- Environment overrides: `SECOND_OPINION_DATA` (fallback `FINANCE_ANALYST_DATA`) and `SECOND_OPINION_PYTHON` (fallbacks `FINANCE_ANALYST_PYTHON`, `PROFICI_PYTHON`).
