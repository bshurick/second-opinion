import json
import shutil
from pathlib import Path

import pytest

from second_opinion import settings, settings_migrate

FIXTURES = Path(__file__).parent / "fixtures" / "settings-migrate"


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.delenv("BROKER_ACCOUNT_TYPES", raising=False)
    monkeypatch.delenv("SNAPTRADE_ACCOUNT_TYPES", raising=False)
    return tmp_path


def _case(tmp_data, name):
    for f in (FIXTURES / name).iterdir():
        shutil.copy(f, tmp_data / f.name)


def test_full_migration(tmp_data):
    _case(tmp_data, "full")
    doc = settings.load()
    assert doc["schema"] == 2
    assert doc["plan"]["sleeves"]["PICKS"]["target"] is None  # ceiling 1.0: the sleeve's size is unmanaged
    assert doc["plan"]["sleeves"]["PICKS"]["weighting"] == "valuation"
    assert doc["plan"]["sleeves"]["PICKS"]["glide"] is None
    assert "ceiling" not in doc["plan"]["sleeves"]["PICKS"]
    assert doc["meta"]["retired"]["plan.sleeves.PICKS.ceiling"] == 1.0
    assert doc["plan"]["sleeves"]["EMPLOYER"]["members"] == ["AMZN"]
    assert doc["taxes"]["short_term_gain_policy"] == "allow"
    assert doc["guardrails"]["pre_buy_check"] is True and doc["replies"]["follow_ups"] is False
    assert doc["lessons"] is False
    assert {"date": "2026-10-29", "key": "plan.sleeves.PICKS.target", "value": None} in doc["history"]
    assert {"date": "2026-10-29", "key": "plan.sleeves.EMPLOYER.members", "value": ["AMZN"]} in doc["history"]
    assert {"date": "2026-10-29", "key": "taxes.short_term_gain_policy", "value": "allow"} in doc["history"]
    assert len(doc["history"]) == 4
    assert doc["plan"]["targets"] == {"VTI": 0.6, "BND": 0.4}
    assert doc["accounts"]["acct-1"]["role"] == "retirement"
    assert (tmp_data / "core-satellite.json.migrated").is_file()
    assert (tmp_data / "targets.json.migrated").is_file()
    assert not (tmp_data / "core-satellite.json").exists() and not (tmp_data / "targets.json").exists()
    assert (tmp_data / "installed.json").is_file() and (tmp_data / "profile.json").is_file()
    assert "core-satellite.json" in doc["meta"]["migrated_from"] and "targets.json" in doc["meta"]["migrated_from"]
    assert json.loads((tmp_data / "settings.json").read_text())["plan"]["targets"] == {"VTI": 0.6, "BND": 0.4}


def test_extras_map(tmp_data):
    (tmp_data / "installed.json").write_text('{"extras": {"follow_ups": true, "trade-journal": false, "financial-education": true}}')
    doc = settings.load()
    assert doc["replies"]["follow_ups"] is True
    assert doc["guardrails"]["pre_buy_check"] is False
    assert doc["lessons"] is True
    assert (tmp_data / "installed.json").is_file()


def test_employer_none_becomes_empty_list(tmp_data):
    _case(tmp_data, "employer-none")
    doc = settings.load()
    assert doc["plan"]["sleeves"]["EMPLOYER"]["members"] == []
    assert {"date": "2026-10-01", "key": "plan.sleeves.EMPLOYER.members", "value": []} in doc["history"]


def test_employer_null_stays_null(tmp_data):
    (tmp_data / "core-satellite.json").write_text('{"ceiling": 0.2, "employer_symbol": null}')
    assert settings.load()["plan"]["sleeves"]["EMPLOYER"]["members"] is None


def test_targets_and_roles(tmp_data):
    _case(tmp_data, "targets-and-roles")
    doc = settings.load()
    assert doc["plan"]["targets"] == {"VTI": 0.7, "BND": 0.3}
    assert doc["plan"]["classes"] == {"VXUS": "VTI"}
    assert doc["accounts"]["acct-1"]["role"] == "retirement"
    assert doc["accounts"]["acct-2"]["role"] == "savings"


def test_step_up_plan_without_a_target_is_retired(tmp_data):
    plan = {"status": "active", "next_due": "2026-11-01"}
    (tmp_data / "core-satellite.json").write_text(json.dumps({"plan": plan, "increases": [{"date": "2026-10-01", "amount": 5}]}))
    doc = settings.load()
    assert doc["plan"]["sleeves"]["PICKS"]["glide"] is None
    assert doc["meta"]["retired"]["plan.sleeves.PICKS.step_up"] == plan
    assert doc["meta"]["retired"]["plan.sleeves.PICKS.increases"] == [{"date": "2026-10-01", "amount": 5}]


def test_step_up_plan_with_a_target_becomes_a_glide(tmp_data):
    plan = {"target": 0.18, "by_date": "2027-04-30", "cadence": "monthly", "status": "active"}
    (tmp_data / "core-satellite.json").write_text(json.dumps({"ceiling": 0.2, "plan": plan}))
    doc = settings.load()
    assert doc["plan"]["sleeves"]["PICKS"]["glide"] == {"to": 0.18, "by": "2027-04-30"}
    assert doc["plan"]["sleeves"]["PICKS"]["target"] == 0.2
    assert doc["meta"]["retired"]["plan.sleeves.PICKS.step_up"] == plan


def test_margin_from_env(tmp_data, monkeypatch):
    monkeypatch.setenv("BROKER_ACCOUNT_TYPES", "acct-9=margin,acct-2=cash")
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    doc = settings.load()
    assert doc["accounts"]["acct-9"]["margin"] is True
    assert doc["accounts"].get("acct-2", {}).get("margin", False) is False


def test_margin_from_snaptrade_var_and_env_mapping(tmp_data):
    doc = settings_migrate.migrate(tmp_data, env={"SNAPTRADE_ACCOUNT_TYPES": "a1=margin"})
    assert doc["accounts"]["a1"]["margin"] is True
    assert (tmp_data / "settings.json").is_file()


def test_nothing_to_migrate_writes_nothing(tmp_data):
    settings.load()
    assert not (tmp_data / "settings.json").exists()
    assert settings_migrate.migrate(tmp_data, env={}) is None


def test_runs_once(tmp_data):
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    settings.load()
    (tmp_data / "targets.json").write_text('{"targets": {"BND": 1.0}}')
    assert settings.get("plan.targets") == {"VTI": 1.0}


def test_corrupt_source_is_kept_and_reported(tmp_data):
    (tmp_data / "core-satellite.json").write_text("{bad")
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    doc = settings.load()
    assert doc["plan"]["targets"] == {"VTI": 1.0}
    assert (tmp_data / "core-satellite.json").read_text() == "{bad"
    assert any(w.startswith("core-satellite.json") for w in doc["meta"]["migration_warnings"])


def test_invalid_value_is_dropped_and_reported(tmp_data):
    (tmp_data / "core-satellite.json").write_text('{"ceiling": 5, "weighting": "size"}')
    doc = settings.load()
    assert doc["plan"]["sleeves"]["PICKS"]["target"] is None
    assert doc["plan"]["sleeves"]["PICKS"]["weighting"] == "size"
    assert any("ceiling" in w for w in doc["meta"]["migration_warnings"])


def test_bad_role_dropped(tmp_data):
    (tmp_data / "profile.json").write_text('{"fields": {"account_roles": {"value": {"a": "bogus", "b": "trading"}}}}')
    doc = settings.load()
    assert "a" not in doc["accounts"] and doc["accounts"]["b"]["role"] == "trading"
    assert any(w.startswith("profile.json") for w in doc["meta"]["migration_warnings"])


def test_lone_corrupt_source_is_recorded(tmp_data):
    (tmp_data / "core-satellite.json").write_text("{bad")
    doc = settings.load()
    assert any(w.startswith("core-satellite.json") for w in doc["meta"]["migration_warnings"])
    assert (tmp_data / "core-satellite.json").read_text() == "{bad"
    assert (tmp_data / "settings.json").is_file()
    settings.set_value("depth", "deep")
    assert any(w.startswith("core-satellite.json") for w in settings.load()["meta"]["migration_warnings"])


def test_rename_failure_is_a_warning(tmp_data, monkeypatch):
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    real = Path.rename

    def boom(self, target):
        if self.name == "targets.json":
            raise PermissionError("nope")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", boom)
    doc = settings.load()
    assert (tmp_data / "targets.json").is_file()
    assert any(w.startswith("targets.json") and "renamed" in w for w in doc["meta"]["migration_warnings"])
    assert any(w.startswith("targets.json") for w in json.loads((tmp_data / "settings.json").read_text())["meta"]["migration_warnings"])


def test_nothing_renamed_when_save_fails(tmp_data, monkeypatch):
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')

    def fail(doc, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(settings, "save", fail)
    with pytest.raises(OSError):
        settings.load()
    assert (tmp_data / "targets.json").is_file() and not (tmp_data / "targets.json.migrated").exists()


def test_existing_backup_is_not_overwritten(tmp_data):
    (tmp_data / "targets.json.migrated").write_text("old backup")
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    settings.load()
    assert (tmp_data / "targets.json.migrated").read_text() == "old backup"
    assert (tmp_data / "targets.json.migrated.1").is_file()


def test_missing_extras_keys_fall_back_to_skills_list(tmp_data):
    (tmp_data / "installed.json").write_text('{"skills": ["trade-journal", "financial-education"], "extras": {}}')
    doc = settings.load()
    assert doc["guardrails"]["pre_buy_check"] is True and doc["lessons"] is True
    assert doc["replies"]["follow_ups"] is False


def test_missing_extras_keys_and_skills_off(tmp_data):
    (tmp_data / "installed.json").write_text('{"skills": ["spending"], "extras": {}}')
    doc = settings.load()
    assert doc["guardrails"]["pre_buy_check"] is False and doc["lessons"] is False


def test_defaults_with_no_old_files(tmp_data):
    assert settings.get("guardrails.pre_buy_check") is True
    assert settings.get("replies.follow_ups") is False and settings.get("lessons") is False
    assert settings.get("replies.pages") is True
    assert not (tmp_data / "settings.json").exists()


def test_reappearing_core_satellite_changes_nothing(tmp_data):
    (tmp_data / "core-satellite.json").write_text('{"ceiling": 0.2}')
    settings.load()
    (tmp_data / "core-satellite.json").write_text('{"ceiling": 0.9}')
    assert settings.get("plan.sleeves.PICKS.target") == 0.2


def test_installed_json_falls_back_to_the_plugin_root(tmp_data, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "installed.json").write_text(json.dumps({"skills": [], "extras": {"follow_ups": True}}))
    monkeypatch.setattr(settings_migrate.config, "PLUGIN_ROOT", root)
    assert settings.load()["replies"]["follow_ups"] is True
    assert (root / "installed.json").exists()  # never renamed


# ---- a settings.json that exists but was never migrated (an installer wrote it first) ----

INSTALLER_SHAPED = {"schema": 1, "replies": {"follow_ups": True}, "guardrails": {"pre_buy_check": False}, "lessons": False}


def test_installer_shaped_file_still_migrates_and_keeps_its_switches(tmp_data):
    _case(tmp_data, "full")
    (tmp_data / "settings.json").write_text(json.dumps(INSTALLER_SHAPED))
    doc = settings.load()
    assert doc["plan"]["sleeves"]["PICKS"]["target"] is None
    assert doc["plan"]["sleeves"]["PICKS"]["weighting"] == "valuation"
    assert doc["plan"]["sleeves"]["EMPLOYER"]["members"] == ["AMZN"]
    assert doc["taxes"]["short_term_gain_policy"] == "allow"
    assert doc["plan"]["targets"] == {"VTI": 0.6, "BND": 0.4}
    assert doc["accounts"]["acct-1"]["role"] == "retirement" and doc["accounts"]["acct-2"]["role"] == "trading"
    assert len(doc["history"]) == 4
    # the installer's switches win over the old installed.json extras
    assert doc["replies"]["follow_ups"] is True and doc["guardrails"]["pre_buy_check"] is False and doc["lessons"] is False
    assert (tmp_data / "core-satellite.json.migrated").is_file() and (tmp_data / "targets.json.migrated").is_file()
    assert not (tmp_data / "core-satellite.json").exists() and not (tmp_data / "targets.json").exists()
    saved = json.loads((tmp_data / "settings.json").read_text())
    assert saved["meta"]["migrated_at"] and saved["plan"]["sleeves"]["PICKS"]["target"] is None
    assert saved["replies"]["follow_ups"] is True and "core-satellite.json" in saved["meta"]["migrated_from"]


def test_migration_marker_stops_a_second_run(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps(INSTALLER_SHAPED))
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    assert settings.get("plan.targets") == {"VTI": 1.0}
    (tmp_data / "targets.json").write_text('{"targets": {"BND": 1.0}}')
    assert settings.get("plan.targets") == {"VTI": 1.0}
    assert (tmp_data / "targets.json").is_file()


def test_marked_file_is_never_migrated(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps({"schema": 1, "meta": {"migrated_at": "2026-11-01"}}))
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    assert settings.get("plan.targets") == {}
    assert (tmp_data / "targets.json").is_file()


def test_existing_history_and_meta_are_kept_beside_the_migrated_ones(tmp_data):
    _case(tmp_data, "full")
    (tmp_data / "settings.json").write_text(json.dumps({
        "schema": 1, "history": [{"date": "2026-11-09", "key": "depth", "value": "deep"}], "depth": "deep",
        "meta": {"seen_version": "1.1.0", "migrated_from": [], "migration_warnings": ["x: earlier"]}}))
    doc = settings.load()
    assert doc["depth"] == "deep" and doc["meta"]["seen_version"] == "1.1.0"
    assert len(doc["history"]) == 5 and doc["history"][-1]["key"] == "depth"
    assert "core-satellite.json" in doc["meta"]["migrated_from"]
    assert doc["meta"]["migration_warnings"][0] == "x: earlier"


def test_set_value_with_nothing_to_migrate_marks_the_file(tmp_data):
    settings.set_value("depth", "deep")
    assert json.loads((tmp_data / "settings.json").read_text())["meta"]["migrated_at"]
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    assert settings.get("plan.targets") == {}


def test_newer_schema_file_is_not_migrated(tmp_data):
    (tmp_data / "settings.json").write_text('{"schema": 3}')
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    settings.load()
    assert json.loads((tmp_data / "settings.json").read_text()) == {"schema": 3}
    assert (tmp_data / "targets.json").is_file()


def test_first_migration_never_clobbers_a_file_that_appeared(tmp_data, monkeypatch):
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    other = {"schema": 2, "plan": {"targets": {"BND": 1.0}}, "meta": {"migrated_at": "2026-11-10"}}
    real = settings_migrate._margin

    def racing(b, env):
        real(b, env)
        (tmp_data / "settings.json").write_text(json.dumps(other))  # another process won the race

    monkeypatch.setattr(settings_migrate, "_margin", racing)
    doc = settings.load()
    assert doc["plan"]["targets"] == {"BND": 1.0}
    assert json.loads((tmp_data / "settings.json").read_text()) == other
    assert (tmp_data / "targets.json").is_file()  # the winner renames, not us
    assert not list(tmp_data.glob(".settings-*.tmp"))


# ---- schema 1 -> 2 (phase 3) ----

SCHEMA1 = {"schema": 1, "meta": {"migrated_at": "2026-11-01", "migrated_from": [], "migration_warnings": []},
           "plan": {"sleeves": {"PICKS": {"ceiling": 0.2, "weighting": "equal", "include_light": None,
                                          "increases": [{"date": "2026-10-01", "amount": 500}],
                                          "step_up": {"target": 0.25, "by_date": "2027-06-30", "cadence": "monthly"}},
                                "EMPLOYER": {"members": ["AMZN"]}}},
           "history": [{"date": "2026-10-01", "key": "plan.sleeves.PICKS.ceiling", "value": 0.2}]}


def test_schema1_upgrades_ceiling_to_target(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps(SCHEMA1))
    doc = settings.load()
    picks = doc["plan"]["sleeves"]["PICKS"]
    assert doc["schema"] == 2 and picks["target"] == 0.2 and picks["glide"] == {"to": 0.25, "by": "2027-06-30"}
    assert set(picks) == {"target", "glide", "weighting", "include_light"}
    saved = json.loads((tmp_data / "settings.json").read_text())
    assert saved["schema"] == 2 and "schema 1" in saved["meta"]["migrated_from"]


def test_schema1_ceiling_one_is_no_target(tmp_data):
    old = json.loads(json.dumps(SCHEMA1))
    old["plan"]["sleeves"]["PICKS"].update(ceiling=1.0, step_up=None, increases=[])
    (tmp_data / "settings.json").write_text(json.dumps(old))
    picks = settings.load()["plan"]["sleeves"]["PICKS"]
    assert picks["target"] is None and picks["glide"] is None


def test_retired_values_kept(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps(SCHEMA1))
    retired = settings.load()["meta"]["retired"]
    assert retired["plan.sleeves.PICKS.ceiling"] == 0.2
    assert retired["plan.sleeves.PICKS.increases"] == [{"date": "2026-10-01", "amount": 500}]
    assert retired["plan.sleeves.PICKS.step_up"]["cadence"] == "monthly"


def test_schema1_history_is_kept_verbatim(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps(SCHEMA1))
    assert {"date": "2026-10-01", "key": "plan.sleeves.PICKS.ceiling", "value": 0.2} in settings.load()["history"]
