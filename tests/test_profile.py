"""Profile library: file format, provenance, validation, summary, next steps."""

from __future__ import annotations

import json
from datetime import date

import pytest
from second_opinion import profile
from second_opinion.errors import ApiError, InvalidInput

TODAY = date(2026, 9, 10)


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def test_load_returns_none_when_absent() -> None:
    assert profile.load() is None


def test_new_profile_shape_and_roundtrip(data_dir) -> None:
    p = profile.new_profile("complete", today=TODAY)
    assert p == {
        "version": 1,
        "created": "2026-09-10",
        "updated": "2026-09-10",
        "learning": True,
        "onboarding": {"status": "complete", "at": "2026-09-10", "version": 1},
        "fields": {},
        "proposals": [],
        "declined": [],
    }
    path = profile.save(p)
    assert path == data_dir / "profile.json"
    assert json.loads(path.read_text()) == p and profile.load() == p


def test_new_profile_rejects_unknown_status() -> None:
    with pytest.raises(InvalidInput):
        profile.new_profile("later", today=TODAY)


def test_corrupt_file_raises_profile_corrupt(data_dir) -> None:
    (data_dir / "profile.json").write_text("{not json")
    with pytest.raises(ApiError) as excinfo:
        profile.load()
    assert excinfo.value.code == "PROFILE_CORRUPT" and "move or delete" in excinfo.value.extra["hint"]
    (data_dir / "profile.json").write_text(json.dumps({"fields": []}))
    with pytest.raises(ApiError) as excinfo:
        profile.load()
    assert excinfo.value.code == "PROFILE_CORRUPT"
    (data_dir / "profile.json").write_text(json.dumps({"fields": {}, "onboarding": {}, "proposals": "oops"}))
    with pytest.raises(ApiError) as excinfo:
        profile.load()
    assert excinfo.value.code == "PROFILE_CORRUPT"


def test_set_field_declared_with_provenance() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "horizon", "years", today=TODAY)
    assert p["fields"]["horizon"] == {"value": "years", "source": "declared", "at": "2026-09-10"}
    assert p["updated"] == "2026-09-10"


def test_set_field_keeps_history_on_change() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "horizon", "years", today=TODAY)
    profile.set_field(p, "horizon", "months", today=date(2026, 9, 12))
    f = p["fields"]["horizon"]
    assert (f["value"], f["source"], f["at"]) == ("months", "declared", "2026-09-12")
    assert f["history"] == [{"value": "years", "source": "declared", "at": "2026-09-10"}]


def test_set_field_confirmed_needs_proposal_id() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "trades_actively", True, source="confirmed", from_proposal="p-1", today=TODAY)
    assert p["fields"]["trades_actively"] == {"value": True, "source": "confirmed", "at": "2026-09-10", "from_proposal": "p-1"}
    with pytest.raises(InvalidInput):
        profile.set_field(p, "trades_actively", True, source="confirmed", today=TODAY)
    with pytest.raises(InvalidInput):
        profile.set_field(p, "trades_actively", True, source="inferred", today=TODAY)


@pytest.mark.parametrize(
    "field,raw,normalized",
    [
        ("approach", "Value, index", ["value", "index"]),
        ("approach", ["technical"], ["technical"]),
        ("horizon", "Years", "years"),
        ("risk_appetite", "moderate", "moderate"),
        ("experience", "beginner", "beginner"),
        ("pre_trade_check", "valuation", "valuation"),
        ("goals", "retirement, a house", ["retirement", "a house"]),
        ("trades_actively", "yes", True),
        ("uses_options", "false", False),
        ("account_roles", {"abc": "Retirement"}, {"abc": "retirement"}),
        ("account_roles", "abc=trading,def=savings", {"abc": "trading", "def": "savings"}),
    ],
)
def test_validate_value_normalizes(field, raw, normalized) -> None:
    assert profile.validate_value(field, raw) == normalized


@pytest.mark.parametrize(
    "field,raw",
    [("approach", "momentum"), ("horizon", "decades"), ("risk_appetite", "yolo"), ("pre_trade_check", "astrology"),
     ("account_roles", {"abc": "gambling"}), ("trades_actively", "sometimes"), ("nonexistent", "x"), ("approach", [])],
)
def test_validate_value_rejects(field, raw) -> None:
    with pytest.raises(InvalidInput):
        profile.validate_value(field, raw)


def test_unset_field_records_history() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "goals", "retirement", today=TODAY)
    profile.unset_field(p, "goals", today=date(2026, 9, 12))
    assert "goals" not in p["fields"]
    assert p["updated"] == "2026-09-12"
    with pytest.raises(InvalidInput):
        profile.unset_field(p, "goals", today=TODAY)


def _full_profile() -> dict:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "approach", ["value", "index"], today=TODAY)
    profile.set_field(p, "horizon", "years", today=TODAY)
    profile.set_field(p, "risk_appetite", "moderate", today=TODAY)
    profile.set_field(p, "experience", "intermediate", today=TODAY)
    profile.set_field(p, "goals", ["retirement", "house"], today=TODAY)
    profile.set_field(p, "pre_trade_check", "valuation", today=TODAY)
    profile.set_field(p, "account_roles", {"a1": "trading", "a2": "retirement"}, today=TODAY)
    return p


def test_summary_is_one_short_paragraph() -> None:
    text = profile.summary(_full_profile())
    assert text == (
        "Second Opinion profile (declared 2026-09-10): approach value, index; horizon years; "
        "risk appetite moderate; experience intermediate; goals retirement, house; "
        "pre-trade check valuation; accounts 1 trading, 1 retirement. "
        "Use it to choose which analysis to run first; never to judge a security against the person."
    )
    assert len(text.split()) < 80


def test_summary_with_no_fields() -> None:
    p = profile.new_profile("complete", today=TODAY)
    assert profile.summary(p).startswith("Second Opinion profile (declared 2026-09-10): no fields set")


def test_context_line_states() -> None:
    assert profile.context_line(None) == profile.NO_PROFILE_LINE
    assert "first finance request" in profile.NO_PROFILE_LINE and "onboarding" in profile.NO_PROFILE_LINE
    assert profile.context_line(profile.new_profile("skipped", today=TODAY)) == profile.SKIPPED_LINE
    assert "get started with Second Opinion" in profile.SKIPPED_LINE
    assert profile.context_line(_full_profile()) == profile.summary(_full_profile())


ALL_SKILLS = {
    "connect", "portfolio-snapshot", "portfolio-analysis", "dividend-income", "watchlist", "risk-analysis",
    "statement-import", "trade-review", "trade-journal", "tax-aware", "rebalancing", "retirement", "real-estate",
    "personal-finance", "valuation", "fundamental-research", "options", "trading", "market-analysis",
    "financial-education", "onboarding",
}


def test_next_steps_new_user_no_brokerage() -> None:
    out = profile.next_steps(_full_profile(), installed=ALL_SKILLS, brokerage_configured=False, connected_accounts=0, edgar_configured=False)
    assert out["setup"] == [
        "Connect a brokerage: say \"connect my brokerage\", or \"connect E*Trade\" if you have an E*Trade developer key.",
        "Set EDGAR_USER_AGENT in the plugin's .env to an app name and contact email; the SEC requires it before fundamental-research can read filings.",
    ]
    assert out["try_asking"] == [
        "Does KO pass Graham's defensive-investor tests, and what are its owner earnings?",
        "Am I on track to retire at 60?",
        "Rent vs buy on a $750k home at 6.5%, against $3,200 rent.",
    ]


def test_next_steps_connected_user_leads_with_portfolio_and_import() -> None:
    p = _full_profile()
    profile.set_field(p, "trades_actively", True, source="confirmed", from_proposal="p-1", today=TODAY)
    out = profile.next_steps(p, installed=ALL_SKILLS, brokerage_configured=True, connected_accounts=2, edgar_configured=True)
    assert out["setup"] == [
        "Import your history: say \"import my transaction history\" so tax-aware and trade-review have two years of activity.",
        "Journal your next trade: say \"journal this trade\" before you place it, so the discipline gate has a plan to check.",
    ]
    assert out["try_asking"][0] == "How is my portfolio doing today?"
    assert len(out["try_asking"]) <= 5


def test_next_steps_brokerage_configured_but_nothing_linked() -> None:
    out = profile.next_steps(_full_profile(), installed=ALL_SKILLS, brokerage_configured=True, connected_accounts=0, edgar_configured=True)
    assert out["setup"][0] == "Finish connecting: say \"connect my brokerage\" to link an account."


def test_next_steps_only_suggests_installed_skills() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "approach", "technical", today=TODAY)
    profile.set_field(p, "goals", "learning", today=TODAY)
    out = profile.next_steps(p, installed={"market-analysis", "onboarding"}, brokerage_configured=False, connected_accounts=0, edgar_configured=False)
    assert out["setup"] == []
    assert out["try_asking"] == ["How are markets doing today? What is the yield curve saying?"]


def test_next_steps_learning_only_goals_skip_the_connect_item() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "goals", "learning", today=TODAY)
    out = profile.next_steps(p, installed={"connect"}, brokerage_configured=False, connected_accounts=0, edgar_configured=False)
    assert out["setup"] == []


def test_next_steps_mixed_goals_keep_the_connect_item() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "goals", ["learning", "retirement"], today=TODAY)
    out = profile.next_steps(p, installed={"connect"}, brokerage_configured=False, connected_accounts=0, edgar_configured=False)
    assert out["setup"][0].startswith("Connect a brokerage")


def test_next_steps_unsure_approach_points_to_education() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "approach", "unsure", today=TODAY)
    out = profile.next_steps(p, installed=ALL_SKILLS, brokerage_configured=False, connected_accounts=0, edgar_configured=False)
    assert "Quiz me to find my level, then teach me one concept." in out["try_asking"]


def test_summary_bounds_long_goal_lists() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "approach", "value", today=TODAY)
    profile.set_field(p, "horizon", "years", today=TODAY)
    long_goal = "x" * 60
    profile.set_field(p, "goals", ["retirement", "house", long_goal, "travel", "income", "education", "hobby", "experience"], today=TODAY)
    text = profile.summary(p)
    # Verify 4 goals rendered plus "and 4 more"
    assert "and 4 more" in text
    # Verify the long goal is truncated to 39 chars + …
    assert "x" * 39 + "…" in text
    # Verify total word count is still under 80
    assert len(text.split()) < 80


def test_summary_word_bound_with_wordy_goals() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "approach", ["value", "index"], today=TODAY)
    profile.set_field(p, "horizon", "years", today=TODAY)
    profile.set_field(p, "risk_appetite", "moderate", today=TODAY)
    profile.set_field(p, "experience", "intermediate", today=TODAY)
    wordy_goals = [
        "save enough money to retire comfortably someday soon",
        "buy a bigger house for my growing family unit",
        "generate steady reliable income from dividend paying stocks",
        "grow long term wealth through diversified index investing",
    ]
    profile.set_field(p, "goals", wordy_goals, today=TODAY)
    profile.set_field(p, "pre_trade_check", "valuation", today=TODAY)
    profile.set_field(p, "account_roles", {"a1": "trading", "a2": "retirement"}, today=TODAY)
    text = profile.summary(p)
    assert len(text.split()) < 80


def test_summary_renders_booleans_as_yes_no() -> None:
    p = profile.new_profile("complete", today=TODAY)
    profile.set_field(p, "trades_actively", True, today=TODAY)
    profile.set_field(p, "uses_options", False, today=TODAY)
    text = profile.summary(p)
    assert "trades actively yes" in text
    assert "uses options no" in text


def test_context_line_complete_profile_with_no_fields_returns_no_fields_summary() -> None:
    p = profile.new_profile("complete", today=TODAY)
    # Profile exists and is complete, but has no fields set
    line = profile.context_line(p)
    # Should return the "no fields set" summary, not the skipped line
    assert "no fields set" in line
    assert "onboarding was skipped" not in line
