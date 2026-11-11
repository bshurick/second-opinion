import json
from datetime import date

import pytest

from second_opinion import settings
from second_opinion.errors import ApiError, InvalidInput


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def test_defaults_when_no_file(tmp_data):
    doc = settings.load()
    assert doc["schema"] == 2 and doc["depth"] == "standard"
    assert settings.get("guardrails.pre_buy_check") is True
    assert settings.get("replies.follow_ups") is False and settings.get("replies.pages") is True
    assert not (tmp_data / "settings.json").exists()


def test_set_value_writes_atomically_and_records_history(tmp_data):
    settings.set_value("depth", "deep", today=date(2026, 11, 10))
    raw = json.loads((tmp_data / "settings.json").read_text())
    assert raw["depth"] == "deep"
    assert raw["history"][-1] == {"date": "2026-11-10", "key": "depth", "value": "deep"}
    assert oct((tmp_data / "settings.json").stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_data.iterdir()] == ["settings.json"]


def test_dynamic_account_key(tmp_data):
    settings.set_value("accounts.abc-1.role", "retirement")
    assert settings.account_role("abc-1", "INDIVIDUAL") == "retirement"
    assert settings.account_role("zzz", "ROTH IRA") == "retirement"
    assert settings.account_role("zzz", "INDIVIDUAL") == "trading"


@pytest.mark.parametrize("key,raw", [("depth", "extreme"), ("deep.ask_above", "0"),
    ("accounts.a.role", "spending"), ("plan.sleeves.PICKS.target", "1.5"), ("nope", "x")])
def test_bad_values_are_bad_input(tmp_data, key, raw):
    with pytest.raises(InvalidInput):
        settings.set_value(key, settings.parse(key, raw))


def test_targets_must_sum_to_one(tmp_data):
    with pytest.raises(InvalidInput):
        settings.set_value("plan.targets", {"VTI": 0.6, "BND": 0.3})
    settings.set_value("plan.targets", {"VTI": 0.6, "BND": 0.4})
    assert settings.get("plan.targets") == {"VTI": 0.6, "BND": 0.4}


def test_corrupt_file_is_never_overwritten(tmp_data):
    (tmp_data / "settings.json").write_text("{not json")
    with pytest.raises(ApiError) as e:
        settings.load()
    # the codebase carries hints in .extra (see profile.py), not as an attribute
    assert e.value.code == "SETTINGS_CORRUPT" and "settings.json" in e.value.extra["hint"]
    with pytest.raises(ApiError):
        settings.set_value("depth", "deep")
    assert (tmp_data / "settings.json").read_text() == "{not json"


def test_invalid_stored_value_is_corrupt(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps({"schema": 1, "depth": "extreme"}))
    with pytest.raises(ApiError) as e:
        settings.load()
    assert e.value.code == "SETTINGS_CORRUPT"
    (tmp_data / "settings.json").write_text("[1]")
    with pytest.raises(ApiError) as e:
        settings.load()
    assert e.value.code == "SETTINGS_CORRUPT"


def test_newer_schema_is_read_only(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps({"schema": 3, "depth": "deep", "future": {"x": 1}}))
    assert settings.get("depth") == "deep"
    assert settings.load()["future"] == {"x": 1}
    with pytest.raises(ApiError) as e:
        settings.set_value("depth", "standard")
    assert e.value.code == "SETTINGS_NEWER"


def test_file_values_win_and_defaults_fill_in(tmp_data):
    (tmp_data / "settings.json").write_text(json.dumps({"schema": 1, "plan": {"bands": {"absolute": 0.1}}}))
    assert settings.get("plan.bands.absolute") == 0.1
    assert settings.get("plan.bands.relative") == 0.25
    assert settings.get("plan.sleeves.PICKS.glide") is None


def test_parse_bools_and_members(tmp_data):
    assert settings.parse("replies.follow_ups", "on") is True
    assert settings.parse("lessons", "No") is False
    with pytest.raises(InvalidInput):
        settings.parse("lessons", "maybe")
    assert settings.parse("plan.sleeves.EMPLOYER.members", "none") == []
    assert settings.parse("plan.sleeves.EMPLOYER.members", "amzn, adbe") == ["AMZN", "ADBE"]
    assert settings.get("plan.sleeves.EMPLOYER.members") is None
    settings.set_value("plan.sleeves.EMPLOYER.members", [])
    assert settings.get("plan.sleeves.EMPLOYER.members") == []


def test_other_validation(tmp_data):
    assert settings.parse("plan.sleeves.PICKS.target", "0.25") == 0.25
    assert settings.parse("plan.sleeves.PICKS.target", "none") is None
    assert settings.parse("plan.sleeves.PICKS.glide", '{"to": 0.2, "by": "2027-06-30"}') == {"to": 0.2, "by": "2027-06-30"}
    assert settings.parse("plan.sleeves.EMPLOYER.policy", "sell_on_arrival") == "sell_on_arrival"
    assert settings.parse("plan.sleeves.PICKS.weighting", "equal") == "equal"
    assert settings.parse("accounts.a.margin", "yes") is True
    assert settings.parse("taxes.short_term_gain_policy", "hold") == "hold"
    for key, raw in [("taxes.long_term_rate", "1"), ("taxes.short_term_gain_policy", "never"),
                     ("plan.sleeves.PICKS.weighting", "random"), ("deep.ask_above", "x"),
                     ("accounts.a.margin", "2")]:
        with pytest.raises(InvalidInput):
            settings.parse(key, raw)


def test_is_tax_advantaged_reexported_from_global_plan():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "portfolio-plan" / "scripts"))
    import global_plan
    assert global_plan.is_tax_advantaged is settings.is_tax_advantaged
    assert settings.is_tax_advantaged("Roth IRA") and not settings.is_tax_advantaged(None)


def _stored(tmp_data, doc):
    (tmp_data / "settings.json").write_text(json.dumps(doc))


def test_stored_infinity_is_corrupt(tmp_data):
    (tmp_data / "settings.json").write_text('{"schema": 1, "deep": {"ask_above": 1e999}}')
    for call in (settings.load, lambda: settings.get("deep.ask_above")):
        with pytest.raises(ApiError) as e:
            call()
        assert e.value.code == "SETTINGS_CORRUPT"


@pytest.mark.parametrize("raw", ["inf", "nan", "-inf"])
def test_non_finite_text_is_bad_input(tmp_data, raw):
    for key in ("deep.ask_above", "taxes.long_term_rate", "plan.sleeves.PICKS.target"):
        with pytest.raises(InvalidInput):
            settings.parse(key, raw)


def test_bad_target_weights(tmp_data):
    for weights in ({"VTI": float("nan"), "BND": 1.0}, {"VTI": 1.5, "BND": -0.5}):
        with pytest.raises(InvalidInput):
            settings.set_value("plan.targets", weights)


@pytest.mark.parametrize("bad", [{"history": "x"}, {"guardrails": 5}, {"meta": "x"}, {"deep": "x"},
                                 {"accounts": []}, {"plan": {"sleeves": {"PICKS": 1}}},
                                 {"meta": {"migrated_from": "x"}}, {"accounts": {"a": 1}}])
def test_wrong_structure_is_corrupt(tmp_data, bad):
    _stored(tmp_data, {"schema": 1, **bad})
    for call in (settings.load, lambda: settings.get("guardrails.pre_buy_check"),
                 lambda: settings.set_value("depth", "deep")):
        with pytest.raises(ApiError) as e:
            call()
        assert e.value.code == "SETTINGS_CORRUPT"


def test_newer_schema_refused_before_touching_the_document(tmp_data):
    text = json.dumps({"schema": 3, "history": "x"})
    (tmp_data / "settings.json").write_text(text)
    with pytest.raises(ApiError) as e:
        settings.set_value("depth", "deep")
    assert e.value.code == "SETTINGS_NEWER"
    assert (tmp_data / "settings.json").read_text() == text


# --- depth (phase 2) ---

from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def test_depth_defaults_to_standard(tmp_data):
    assert settings.depth() == "standard" and settings.is_deep() is False


def test_depth_reads_saved_value(tmp_data):
    settings.set_value("depth", "deep")
    assert settings.depth() == "deep" and settings.is_deep() is True


def test_depth_raises_on_corrupt_settings(tmp_data):
    settings.path().write_text("{not json")
    with pytest.raises(ApiError) as e:
        settings.depth()
    assert e.value.code == "SETTINGS_CORRUPT"


def test_deep_paths_cover_every_skill_with_deep_references():
    found = {p.parent.parent.name for p in SKILLS.glob("*/references/*.md")
             if p.name.startswith("deep-") or p.name == "picker-roles.md"}
    assert set(settings.DEEP_PATHS) == found



# --- schema 2 sleeves (phase 3) ---


def test_sleeve_target_prefers_global_targets(tmp_data):
    settings.set_value("plan.sleeves.PICKS.target", 0.1)
    assert settings.sleeve_target(settings.load(), "PICKS") == 0.1
    settings.set_value("plan.targets", {"VTI": 0.8, "PICKS": 0.2})
    assert settings.sleeve_target(settings.load(), "PICKS") == 0.2


def test_glide_target(tmp_data):
    from datetime import date as d
    settings.set_value("plan.sleeves.PICKS.target", 0.1)
    settings.set_value("plan.sleeves.PICKS.glide", {"to": 0.2, "by": "2027-06-30"})
    doc = settings.load()
    assert settings.glide_target(doc, "PICKS", d(2026, 11, 10)) == 0.2
    settings.set_value("plan.sleeves.PICKS.glide", None)
    assert settings.glide_target(settings.load(), "PICKS", d(2026, 11, 10)) == 0.1


@pytest.mark.parametrize("bad", ['{"to": 1.5, "by": "2027-01-01"}', '{"to": 0.2}', '{"to": 0.2, "by": "soon"}', '"x"'])
def test_glide_rejects_bad_shapes(tmp_data, bad):
    with pytest.raises(InvalidInput):
        settings.parse("plan.sleeves.PICKS.glide", bad)


def test_schema_is_2():
    assert settings.SCHEMA == 2 and settings.DEFAULTS["schema"] == 2
