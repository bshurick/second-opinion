# Streamline Phase 1: One Settings File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scattered settings (installed.json extras, core-satellite.json, targets.json, profile account roles) with one `settings.json` behind one reader, migrate existing data without loss, and give the plugin a version that moves with an update notice.

**Architecture:** A new `lib/second_opinion/settings.py` owns `settings.json` (load, validate, atomic save, history, schema). A sibling `settings_migrate.py` builds the first `settings.json` from the old files the first time `load()` finds none. Every existing reader is switched to the module; the core-satellite and rebalancing scripts keep their own logic and only change where they read and write. A CLI in the setup skill shows and changes settings and reports the version; hooks read on/off switches from the new file.

**Tech Stack:** Python 3.10+ standard library, pytest; bash hooks; the TypeScript installer (`installer/`, vitest, esbuild build of `install.js`).

**Spec:** `docs/superpowers/specs/2026-11-10-streamline-refactor-design.md`, sections "One settings file", "Migration", "Updating". Phases 2 to 6 get their own plans after this one ships.

## Global Constraints

- Data directory is `config.data_dir()`; never read `CLAUDE_PLUGIN_DATA`. Tests rely on `SECOND_OPINION_DATA` (set by `tests/conftest.py`).
- Keys stay in `.env`. The profile stays in `profile.json`. `installed.json` keeps `skills`, `source_path`, `source_commit`, `installer_version`, `installed_at`, `mode`.
- Old files are renamed to `<name>.migrated`, never deleted. `installed.json` and `profile.json` are never renamed.
- A settings change runs only after the person answers in their own words (existing rule; the CLI does not enforce it, the skill text does).
- `settings.json` carries `schema: 1`. A file whose `schema` is higher than the code's is read-only: reads work, writes raise.
- Writes go through a temp file and `os.replace`, mode 0600, `json.dumps(..., indent=1)`.
- Exit codes follow the plugin's convention: 0 ok, 2 bad input, 5 unreadable store.
- New version after this phase: `1.1.0`, in both `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.

## Review Focus

1. A corrupt or hand-edited `settings.json` (invalid JSON, wrong types): every reader must raise the store error with a hint naming the file, and nothing may overwrite it. Test in Task 1.
2. Migration running twice, or with `settings.json` already present and an old file reappearing: migration must not run again and must not clobber `settings.json`. Test in Task 2.
3. A corrupt old file during migration (bad `core-satellite.json`): migration must keep the readable parts, leave the corrupt file in place un-renamed, and record a `migration_warnings` entry, not crash every script. Test in Task 2.
4. A downgrade (`schema: 2` on disk): `show` and `get` work, `set` exits 5 with a message saying the file is from a newer version. Test in Tasks 1 and 3.
5. A marketplace install with no `installed.json` at all: switches fall back to their defaults (`pre_buy_check` on, `follow_ups` off, `lessons` off, `pages` on). Test in Tasks 1 and 5.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `lib/second_opinion/settings.py` | The only reader and writer of `settings.json` |
| Create `lib/second_opinion/settings_migrate.py` | Builds the first document from old files; renames them |
| Create `skills/setup/scripts/settings.py` | CLI: `show`, `get`, `set`, `version`, `notice` |
| Modify `lib/second_opinion/config.py:127-148` | `extra_enabled` reads settings |
| Modify `lib/second_opinion/profile.py` | `account_roles` reads and writes settings |
| Modify `skills/core-satellite/scripts/settings.py:40-84` | Store adapter over `settings.json` |
| Modify `skills/core-satellite/scripts/run.py:133-143` | `_roles` from settings |
| Modify `skills/rebalancing/scripts/plan.py:338-352` | Targets and tax rates from settings |
| Modify `lib/second_opinion/headlines/sources.py:103` | Readiness check on `plan.targets` |
| Modify `hooks/common.sh`, `hooks/session-start.sh`, `hooks/core-satellite-summary.sh` | Switches from settings, migration, update notice, pages rule |
| Create `hooks/pages-off.md` | Session rule when pages are off |
| Modify `installer/src/engine/materialize.ts`, `extras.ts` | Installer writes switches to `settings.json` |
| Create `scripts/check-version.sh`; modify `.github/workflows/ci.yml` | Version must move when shipped files change |
| Docs and skill text | README, `docs/install.md`, `docs/configuration.md`, five SKILL.md files, CHANGELOG |

---

### Task 1: The settings module

**Files:**
- Create: `lib/second_opinion/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `SCHEMA: int = 1`, `FILE: str = "settings.json"`
  - `path() -> Path` — `config.data_dir() / FILE`
  - `load() -> dict` — the document with defaults filled in; runs `settings_migrate.migrate()` (Task 2) when the file is absent; raises `ApiError(code="SETTINGS_CORRUPT")` on bad JSON, a non-dict, or a value failing validation
  - `get(key: str) -> Any` — dotted key, e.g. `get("replies.follow_ups")`; unknown key raises `InvalidInput`
  - `set_value(key: str, value: Any, *, today: date | None = None) -> dict` — validates, writes, appends `{"date", "key", "value"}` to `history`, returns the document
  - `save(doc: dict) -> Path` — atomic; raises `ApiError(code="SETTINGS_NEWER")` when `doc["schema"] > SCHEMA`
  - `parse(key: str, raw: str) -> Any` — CLI text to a typed value, same validation as `set_value`
  - `account_role(account_id: str, raw_type: str | None) -> str` — saved role, else `"retirement"` when the raw type looks tax-advantaged, else `"trading"`
  - `KEYS: dict[str, Key]` where `Key` is a frozen dataclass `(default, label, meaning, parse)`; dynamic keys `accounts.<id>.role|margin` and `plan.sleeves.<NAME>.*` are matched by pattern

The document and its defaults (copy exactly):

```json
{
 "schema": 1,
 "depth": "standard",
 "deep": {"ask_above": 3},
 "accounts": {},
 "plan": {"targets": {}, "classes": {}, "cash_reserve": null,
          "bands": {"absolute": 0.05, "relative": 0.25},
          "sleeves": {"PICKS": {"ceiling": null, "weighting": null, "include_light": null,
                                "increases": [], "step_up": null},
                      "EMPLOYER": {"members": null}}},
 "taxes": {"short_term_rate": 0.24, "long_term_rate": 0.15, "short_term_gain_policy": null},
 "guardrails": {"pre_buy_check": true},
 "replies": {"follow_ups": false, "pages": true},
 "lessons": false,
 "meta": {"seen_version": null, "migrated_from": [], "migration_warnings": []},
 "history": []
}
```

Validation: `depth` in {standard, deep}; `deep.ask_above` int ≥ 1; `accounts.<id>.role` in {trading, retirement, savings}; `accounts.<id>.margin` bool; `plan.targets` values numbers summing to 1 ± 0.001 (empty allowed); `plan.sleeves.PICKS.ceiling` in (0, 1] or null; `weighting` in {equal, market_cap, valuation, size} or null; `EMPLOYER.members` list of tickers (`brokerage.validate_symbol`), `[]` meaning none, null meaning unset; tax rates in [0, 1); `short_term_gain_policy` in {hold, allow} or null; switches bool. `parse` accepts `on/off/true/false/yes/no` for bools and `none` for `EMPLOYER.members`.

- [ ] **Step 1: Write the failing tests**

```python
def test_defaults_when_no_file(tmp_data):
    doc = settings.load()
    assert doc["schema"] == 1 and doc["depth"] == "standard"
    assert settings.get("guardrails.pre_buy_check") is True
    assert settings.get("replies.follow_ups") is False and settings.get("replies.pages") is True

def test_set_value_writes_atomically_and_records_history(tmp_data):
    settings.set_value("depth", "deep", today=date(2026, 11, 10))
    raw = json.loads((tmp_data / "settings.json").read_text())
    assert raw["depth"] == "deep"
    assert raw["history"][-1] == {"date": "2026-11-10", "key": "depth", "value": "deep"}
    assert oct((tmp_data / "settings.json").stat().st_mode & 0o777) == "0o600"

def test_dynamic_account_key(tmp_data):
    settings.set_value("accounts.abc-1.role", "retirement")
    assert settings.account_role("abc-1", "INDIVIDUAL") == "retirement"
    assert settings.account_role("zzz", "ROTH IRA") == "retirement"
    assert settings.account_role("zzz", "INDIVIDUAL") == "trading"

@pytest.mark.parametrize("key,raw", [("depth", "extreme"), ("deep.ask_above", "0"),
    ("accounts.a.role", "spending"), ("plan.sleeves.PICKS.ceiling", "1.5"), ("nope", "x")])
def test_bad_values_are_bad_input(tmp_data, key, raw):
    with pytest.raises(InvalidInput):
        settings.set_value(key, settings.parse(key, raw))

def test_targets_must_sum_to_one(tmp_data):
    with pytest.raises(InvalidInput):
        settings.set_value("plan.targets", {"VTI": 0.6, "BND": 0.3})

def test_corrupt_file_is_never_overwritten(tmp_data):
    (tmp_data / "settings.json").write_text("{not json")
    with pytest.raises(ApiError) as e:
        settings.load()
    assert e.value.code == "SETTINGS_CORRUPT" and "settings.json" in e.value.hint
    with pytest.raises(ApiError):
        settings.set_value("depth", "deep")
    assert (tmp_data / "settings.json").read_text() == "{not json"

def test_newer_schema_is_read_only(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps({"schema": 2, "depth": "deep"}))
    assert settings.get("depth") == "deep"
    with pytest.raises(ApiError) as e:
        settings.set_value("depth", "standard")
    assert e.value.code == "SETTINGS_NEWER"
```

`tmp_data` is a fixture in the test file: `monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))`, returns `tmp_path`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL, `ModuleNotFoundError: second_opinion.settings`

- [ ] **Step 3: Implement `lib/second_opinion/settings.py`**

Defaults are deep-merged under the file's values on load (file wins, unknown keys kept so a newer file round-trips). Until Task 2 lands, call `settings_migrate.migrate` through a guarded import so this task's tests pass alone. Reuse `account_role`'s tax-advantaged test from `skills/rebalancing/scripts/plan.py`'s `is_tax_advantaged` by moving that function into this module and re-exporting it from `plan.py`.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_settings.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add lib/second_opinion/settings.py tests/test_settings.py skills/rebalancing/scripts/plan.py
git commit -m "feat(settings): one settings.json with validation, history and schema"
```

---

### Task 2: Migration from the old files

**Files:**
- Create: `lib/second_opinion/settings_migrate.py`
- Test: `tests/test_settings_migrate.py`
- Create: `tests/fixtures/settings-migrate/` (one directory per case below)

**Interfaces:**
- Consumes: `settings.SCHEMA`, the defaults document, `settings.save`
- Produces: `migrate(data_dir: Path, *, env: Mapping[str, str] | None = None) -> dict | None` — returns the new document after saving it, or `None` when there was nothing to migrate (no old file holds a setting). Called only by `settings.load()` when `settings.json` is absent.

Mapping (copy exactly):

| Old | New |
|---|---|
| `installed.json` `extras.follow_ups` | `replies.follow_ups` |
| `installed.json` `extras["trade-journal"]` | `guardrails.pre_buy_check` |
| `installed.json` `extras["financial-education"]` | `lessons` |
| `core-satellite.json` `ceiling`, `weighting`, `include_light`, `increases` | `plan.sleeves.PICKS.<same>` |
| `core-satellite.json` `plan` | `plan.sleeves.PICKS.step_up` |
| `core-satellite.json` `employer_symbol` | `plan.sleeves.EMPLOYER.members`: `"none"` → `[]`, ticker → `[ticker]`, null → null |
| `core-satellite.json` `short_term_gain_policy` | `taxes.short_term_gain_policy` |
| `core-satellite.json` `decisions` | `history`, each key rewritten to its new dotted key |
| `targets.json` `targets`, `classes` | `plan.targets`, `plan.classes` |
| `profile.json` `fields.account_roles.value` `{id: role}` | `accounts.<id>.role` |
| `BROKER_ACCOUNT_TYPES` / `SNAPTRADE_ACCOUNT_TYPES` (via `config.env_value`) `id=margin` | `accounts.<id>.margin = true` |

After saving: rename `core-satellite.json` and `targets.json` to `.migrated`; append each source name to `meta.migrated_from`. Leave `installed.json`, `profile.json` and `.env` in place. A source that fails to parse is skipped, not renamed, and adds `"<file>: <reason>"` to `meta.migration_warnings`.

- [ ] **Step 1: Write the failing tests**

```python
def test_full_migration(tmp_data):          # fixture "full": every source populated, ceiling 1.0, plan null
    doc = settings.load()
    assert doc["plan"]["sleeves"]["PICKS"]["ceiling"] == 1.0
    assert doc["plan"]["sleeves"]["PICKS"]["weighting"] == "valuation"
    assert doc["plan"]["sleeves"]["PICKS"]["step_up"] is None
    assert doc["plan"]["sleeves"]["EMPLOYER"]["members"] == ["AMZN"]
    assert doc["taxes"]["short_term_gain_policy"] == "allow"
    assert doc["guardrails"]["pre_buy_check"] is True and doc["replies"]["follow_ups"] is False
    assert {"date": "2026-10-29", "key": "plan.sleeves.PICKS.ceiling", "value": 1.0} in doc["history"]
    assert (tmp_data / "core-satellite.json.migrated").is_file()
    assert not (tmp_data / "core-satellite.json").exists()
    assert (tmp_data / "installed.json").is_file() and (tmp_data / "profile.json").is_file()

def test_employer_none_becomes_empty_list(tmp_data): ...   # members == []
def test_targets_and_roles(tmp_data): ...                  # plan.targets, accounts.<id>.role
def test_margin_from_env(tmp_data, monkeypatch):
    monkeypatch.setenv("BROKER_ACCOUNT_TYPES", "acct-9=margin,acct-2=cash")
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    assert settings.load()["accounts"]["acct-9"]["margin"] is True
    assert "acct-2" not in settings.load()["accounts"] or settings.load()["accounts"]["acct-2"].get("margin") is False

def test_nothing_to_migrate_writes_nothing(tmp_data):
    settings.load()
    assert not (tmp_data / "settings.json").exists()

def test_runs_once(tmp_data):
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    settings.load()
    (tmp_data / "targets.json").write_text('{"targets": {"BND": 1.0}}')   # an older plugin wrote it again
    assert settings.get("plan.targets") == {"VTI": 1.0}

def test_corrupt_source_is_kept_and_reported(tmp_data):
    (tmp_data / "core-satellite.json").write_text("{bad")
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    doc = settings.load()
    assert doc["plan"]["targets"] == {"VTI": 1.0}
    assert (tmp_data / "core-satellite.json").read_text() == "{bad"
    assert any(w.startswith("core-satellite.json") for w in doc["meta"]["migration_warnings"])
```

Write each fixture case as files under `tests/fixtures/settings-migrate/<case>/`, copied into `tmp_data` by a helper. The "full" case mirrors the real shape seen in a current install: `core-satellite.json` with `ceiling: 1.0`, `weighting: valuation`, `include_light: null`, `short_term_gain_policy: allow`, `employer_symbol: AMZN`, four `decisions`, `increases: []`, `plan: null`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_settings_migrate.py -q`
Expected: FAIL, `ModuleNotFoundError: second_opinion.settings_migrate`

- [ ] **Step 3: Implement `migrate` in `lib/second_opinion/settings_migrate.py`; drop the guarded import in `settings.py`**

- [ ] **Step 4: Run both settings test files**

Run: `python -m pytest tests/test_settings.py tests/test_settings_migrate.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add lib/second_opinion/settings_migrate.py lib/second_opinion/settings.py tests/test_settings_migrate.py tests/fixtures/settings-migrate
git commit -m "feat(settings): migrate extras, core-satellite, targets and roles into settings.json"
```

---

### Task 3: The settings CLI

**Files:**
- Create: `skills/setup/scripts/settings.py`
- Test: `tests/test_scripts_settings.py`

**Interfaces:**
- Consumes: Task 1's `load`, `get`, `set_value`, `parse`, `KEYS`
- Produces (used by hooks in Task 5 and skill text in Task 7):
  - `settings.py show` → JSON `{"groups": [{"group", "rows": [{"key", "label", "value", "default", "is_default", "meaning", "changed_on"}]}], "warnings": [...]}`. Groups in this order: Depth, Accounts, Portfolio plan, Taxes, Guardrails, Replies, Lessons. `changed_on` is the latest `history` date for the key, or null. `warnings` is `meta.migration_warnings`.
  - `settings.py get KEY` → JSON `{"key", "value"}`; with `--plain`, prints the bare value (`on`/`off` for bools) for hooks
  - `settings.py set KEY VALUE` → JSON `{"key", "value", "previous"}`
  - `settings.py version` → JSON `{"installed", "latest", "seen", "updated", "update_command"}`. `installed` from `PLUGIN_ROOT/.claude-plugin/plugin.json`. `latest` from `~/.claude/plugins/marketplaces/second-opinion/.claude-plugin/plugin.json` when readable, else null (no network). `updated` is `seen is not None and seen != installed`. `update_command` is the marketplace commands for a marketplace install, else `git pull && node install.js` with `source_path` from `installed.json`.
  - `settings.py notice` → plain text, always exit 0: when `seen` is null, records `installed` silently and prints nothing; when `updated`, prints `Second Opinion updated to X (was Y). What changed: CHANGELOG.md in the plugin folder.` and records `installed` as seen; otherwise prints nothing.
- Every subcommand takes hidden `--today YYYY-MM-DD` for tests, like the core-satellite CLI.

- [ ] **Step 1: Write the failing tests** (run the script with `scripts_util.run_script`, as other `test_scripts_*` files do)

```python
def test_show_groups_in_order(tmp_data):
    out = run(["show"])
    assert [g["group"] for g in out["groups"]] == ["Depth", "Accounts", "Portfolio plan", "Taxes", "Guardrails", "Replies", "Lessons"]

def test_set_then_get_plain(tmp_data):
    assert run(["set", "replies.follow_ups", "on"])["previous"] is False
    assert run_text(["get", "replies.follow_ups", "--plain"]).strip() == "on"

def test_set_bad_value_exits_2(tmp_data):
    assert run_code(["set", "depth", "extreme"]) == 2

def test_set_on_newer_schema_exits_5(tmp_data):
    (tmp_data / "settings.json").write_text('{"schema": 2}')
    assert run_code(["set", "depth", "deep"]) == 5

def test_notice_first_run_silent_then_update(tmp_data, fake_plugin_version):
    fake_plugin_version("1.1.0"); assert run_text(["notice"]) == ""
    fake_plugin_version("1.2.0"); assert "updated to 1.2.0 (was 1.1.0)" in run_text(["notice"])
    assert run_text(["notice"]) == ""
```

`fake_plugin_version` patches the path the script reads `plugin.json` from through an env var `SECOND_OPINION_PLUGIN_JSON` (test-only, documented in the script's docstring).

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_scripts_settings.py -q`
Expected: FAIL, script not found

- [ ] **Step 3: Implement `skills/setup/scripts/settings.py`** with the same header, `sys.path` insert and `output` error handling as `skills/core-satellite/scripts/settings.py`.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_scripts_settings.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add skills/setup/scripts/settings.py tests/test_scripts_settings.py
git commit -m "feat(setup): settings show/get/set and version report"
```

---

### Task 4: Switch the readers

**Files:**
- Modify: `lib/second_opinion/config.py:127-148`, `lib/second_opinion/profile.py`, `skills/core-satellite/scripts/settings.py:40-84`, `skills/core-satellite/scripts/run.py:133-143`, `skills/rebalancing/scripts/plan.py:338-352`, `lib/second_opinion/headlines/sources.py:103`
- Test: `tests/test_config.py`, `tests/test_profile.py`, `tests/test_scripts_core_satellite.py`, `tests/test_scripts_rebalancing.py`, `tests/test_headlines_rebalancing_tax.py`, `tests/test_scripts_gate.py`

**Interfaces:**
- Consumes: Task 1's `get`, `set_value`, `account_role`
- Produces:
  - `config.extra_enabled(key)` keeps its signature; maps `follow_ups` → `replies.follow_ups`, `trade-journal` → `guardrails.pre_buy_check`, `financial-education` → `lessons`. The `record` parameter and `EXTRAS_ON_BY_DEFAULT` are removed; update callers.
  - `profile.set_field(..., "account_roles", value)` writes each pair to `accounts.<id>.role` and no longer stores the field in the profile; `profile.summary` and `context_line` read roles from settings.
  - Core-satellite `settings.load() -> dict` and `save(store) -> Path` keep the exact flat shape of `EMPTY` (so `sleeves.py`, `run.py` and its tests are unchanged), translating to and from the Task 2 mapping. `store_path()` returns `settings.path()`.
  - Rebalancing `plan.py`: with no `--target` and no `--targets`, read `plan.targets`/`plan.classes`; empty targets keeps today's "no targets" bad-input message, reworded to name `settings.json`. `--save` calls `set_value("plan.targets", ...)` and `set_value("plan.classes", ...)`. `--short-term`/`--long-term` defaults become `taxes.short_term_rate`/`taxes.long_term_rate`.
  - Headlines rebalancing source: ready when `settings.get("plan.targets")` is non-empty, reason `"no saved targets"`.

- [ ] **Step 1: Update tests to the new store first.** In each listed test file, replace fixtures that write `targets.json`, `core-satellite.json`, `installed.json` extras or profile `account_roles` with `settings.set_value(...)` calls, keep one test per file that writes the old file and asserts the migrated result is read. Add:

```python
def test_extra_enabled_defaults_without_any_record(tmp_data):
    assert config.extra_enabled("trade-journal") is True
    assert config.extra_enabled("follow_ups") is False
    assert config.extra_enabled("financial-education") is False

def test_rebalance_save_writes_settings(tmp_data, fake_hub):
    run_plan(["--target", "VTI=0.6", "--target", "BND=0.4", "--save"])
    assert settings.get("plan.targets") == {"VTI": 0.6, "BND": 0.4}
    assert not (tmp_data / "targets.json").exists()

def test_core_satellite_decide_round_trips(tmp_data):
    run_cs_settings(["decide", "employer_symbol", "none"])
    assert settings.get("plan.sleeves.EMPLOYER.members") == []
    assert run_cs_settings(["show"])["employer_symbol"] == "none"
```

- [ ] **Step 2: Run to verify the new and changed tests fail**

Run: `python -m pytest tests/test_config.py tests/test_profile.py tests/test_scripts_core_satellite.py tests/test_scripts_rebalancing.py tests/test_headlines_rebalancing_tax.py tests/test_scripts_gate.py -q`
Expected: failures in the tests above only

- [ ] **Step 3: Implement the reader changes listed under Produces**

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add lib skills tests
git commit -m "refactor(settings): read extras, roles, targets and core-satellite decisions from settings.json"
```

---

### Task 5: Hooks

**Files:**
- Modify: `hooks/common.sh` (`so_extra_on`), `hooks/session-start.sh`, `hooks/core-satellite-summary.sh:14`
- Create: `hooks/pages-off.md`
- Test: `tests/test_hook.py`

**Interfaces:**
- Consumes: Task 3's `get --plain` and `notice`
- Produces: `so_setting_on KEY` in `common.sh` replacing `so_extra_on`. It runs `"$PY" "$PLUGIN_ROOT/skills/setup/scripts/settings.py" get KEY --plain` and returns 0 on `on`. With no usable python, or any failure, it returns the key's default (`replies.follow_ups` off, `replies.pages` on). Callers resolve `PY` first, as `core-satellite-summary.sh` already does; move that resolution block into `common.sh` as `so_resolve_python` and use it in all four hooks.

`session-start.sh` changes, after the virtualenv step:
1. Run `settings.py notice` and print its output.
2. Print `hooks/follow-ups.md` when `so_setting_on replies.follow_ups`.
3. Print `hooks/pages-off.md` when not `so_setting_on replies.pages`.

`hooks/pages-off.md` (copy exactly):

```
Second Opinion replies (applies to every second-opinion skill in this session):
- The person has turned report pages off. Give every result in chat using the skill's markdown fallback, and do not publish an Artifact unless they ask for a page in this conversation.
```

`core-satellite-summary.sh:14`: replace the `core-satellite.json` existence test with a test for `settings.json` or `core-satellite.json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_follow_ups_from_settings(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    (data / "settings.json").write_text(json.dumps({"schema": 1, "replies": {"follow_ups": True}}))
    proc, _ = _run(tmp_path)
    assert "Second Opinion follow-ups" in proc.stdout

def test_pages_off_rule(tmp_path): ...            # replies.pages false -> "turned report pages off" in stdout
def test_no_settings_defaults(tmp_path): ...      # no files: no follow-ups block, no pages-off block
def test_update_notice_once(tmp_path): ...        # meta.seen_version "1.0.0" -> "updated to 1.1.0" once, then silent
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_hook.py -q`
Expected: the four new tests fail

- [ ] **Step 3: Implement the hook changes**

- [ ] **Step 4: Run hook tests and shellcheck if available**

Run: `python -m pytest tests/test_hook.py tests/test_hook_gate.py -q && (command -v shellcheck >/dev/null && shellcheck hooks/*.sh || true)`
Expected: all pass, no new shellcheck warnings

- [ ] **Step 5: Commit**

```bash
git add hooks tests/test_hook.py
git commit -m "feat(hooks): read switches from settings.json, update notice, pages-off rule"
```

---

### Task 6: Installer writes settings.json

**Files:**
- Modify: `installer/src/engine/materialize.ts:16-18,46-62,113-150`, `installer/src/engine/extras.ts:24-37`
- Test: `installer/test/` (the existing materialize and extras test files)
- Rebuild: `install.js`

**Interfaces:**
- Produces: `writeSettingsSwitches(dir: string, extras: Record<string, boolean>): void` in `materialize.ts`. It reads `dir/settings.json` if present (keeping every other key), refuses with an `InstallError` naming the file when its `schema` is above 1 or it is not valid JSON, sets `replies.follow_ups`, `guardrails.pre_buy_check`, `lessons` from the extras map (same key mapping as Task 4), sets `schema: 1` when absent, and writes through a temp file and rename at mode 0600.
- `writeConfig` calls it and stops writing `extras` into `installed.json`.
- `nonSkillDefaults` and the "previous selection" reader read switches from `settings.json` first, then a legacy `installed.json` `extras`.

- [ ] **Step 1: Write the failing vitest cases**

```ts
it("writes switches into settings.json and keeps other keys", () => {
  fs.writeFileSync(path.join(dir, "settings.json"), JSON.stringify({ schema: 1, depth: "deep" }));
  writeSettingsSwitches(dir, { follow_ups: true, "trade-journal": false, "financial-education": false });
  const s = JSON.parse(fs.readFileSync(path.join(dir, "settings.json"), "utf8"));
  expect(s.depth).toBe("deep");
  expect(s.replies.follow_ups).toBe(true);
  expect(s.guardrails.pre_buy_check).toBe(false);
});
it("refuses a settings.json from a newer version", () => { /* schema 2 -> throws InstallError */ });
it("no longer writes extras into installed.json", () => { /* writeConfig -> record has no extras */ });
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd installer && npm ci && npx vitest run`
Expected: the three new cases fail

- [ ] **Step 3: Implement**

- [ ] **Step 4: Check and rebuild**

Run: `cd installer && npm run check && cd .. && git diff --stat -- install.js`
Expected: check passes; `install.js` changed

- [ ] **Step 5: Commit**

```bash
git add installer/src installer/test install.js
git commit -m "feat(installer): keep optional switches in settings.json"
```

---

### Task 7: Version, CI check, docs and skill text

**Files:**
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (version `1.1.0`), `CHANGELOG.md`, `.github/workflows/ci.yml`
- Create: `scripts/check-version.sh`
- Modify: `README.md` (Install, "Settings and upgrades"), `docs/install.md`, `docs/configuration.md`, `skills/setup/SKILL.md`, `skills/onboarding/SKILL.md`, `skills/core-satellite/SKILL.md`, `skills/rebalancing/SKILL.md`, `skills/portfolio-analysis/SKILL.md`, `docs/scripts.md`
- Test: `tests/test_skills_structure.py`, new `tests/test_version.py`

**Interfaces:**
- Consumes: Task 3's CLI commands, by name, in skill text.

Content decisions:
- `scripts/check-version.sh`: finds the latest `v*` tag; with none, exits 0. Otherwise, if any of `skills/ lib/ hooks/ install.js .claude-plugin/` changed since the tag and `plugin.json`'s version equals the tag's version, prints `version not bumped since <tag>` and exits 1. CI runs it after the pytest step with `fetch-depth: 0` on checkout.
- README "Install": keep the marketplace block first, add directly under it an **Update** line with the marketplace update command and "then `/reload-plugins`", and a note that the next session prints "Second Opinion updated to X". Before writing the command, confirm the current Claude Code syntax for updating a marketplace plugin (`/plugin` help or the claude-code-guide agent); do not guess it.
- README "Settings and upgrades" and `docs/configuration.md`: describe `settings.json`, its groups, "show my settings", and that `core-satellite.json`/`targets.json` become `.migrated`.
- `skills/setup/SKILL.md`: new cases "Show my settings" (`settings.py show`, reply as one table per group, defaults marked), "Change a setting" (`settings.py set` after the person's own words), "Check my setup / is there an update" (`settings.py version`, report installed, latest, update command; nothing updates itself). The "Turn an optional extra on or off" case uses `settings.py set` for `follow_ups`, `pre_buy_check` and `lessons`, no installer run, and says it applies from the next session.
- `skills/onboarding/SKILL.md` step 7 and Background: roles saved to settings via `settings.py set accounts.<id>.role ROLE`.
- `skills/core-satellite/SKILL.md` "Saved settings": the decisions now live in `settings.json` under the portfolio plan; `settings.py` commands unchanged.
- `skills/rebalancing/SKILL.md` and `skills/portfolio-analysis/SKILL.md`: `targets.json` → "the saved targets in settings.json".
- CHANGELOG `## 1.1.0`: one settings file, migration (and which files are renamed), "show my settings", update notice, pages switch.

- [ ] **Step 1: Write the failing tests**

```python
def test_versions_match_and_changelog_has_entry():
    v = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    m = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"]
    assert v == m == "1.1.0"
    assert f"## {v}" in (ROOT / "CHANGELOG.md").read_text()

def test_no_skill_names_retired_files():                      # in test_skills_structure.py
    for skill in (ROOT / "skills").glob("*/SKILL.md"):
        text = skill.read_text()
        assert "targets.json" not in text and "core-satellite.json" not in text, skill
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_version.py tests/test_skills_structure.py -q`
Expected: FAIL on the version and the retired file names

- [ ] **Step 3: Make the version, script, CI, docs and skill text changes above**

- [ ] **Step 4: Run everything**

Run: `python -m pytest tests -q && bash scripts/check-version.sh && (cd installer && npm run check)`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin CHANGELOG.md .github scripts README.md docs skills tests
git commit -m "docs: settings.json, updating, version 1.1.0"
```

---

## Verification against a real data directory

After Task 7, before merging: copy the real data directory to a scratch path, point `SECOND_OPINION_DATA` at the copy, and run `settings.py show`, `core-satellite/scripts/settings.py show` and `core-satellite/scripts/run.py mix --partial` (a read; neither script places orders). Expected: the migrated values match the original `core-satellite.json` and `installed.json` extras, `core-satellite.json.migrated` exists in the copy, and the original directory is untouched.
