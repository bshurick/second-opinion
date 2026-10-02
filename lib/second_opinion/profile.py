"""The user's Second Opinion profile: what they declared about how they invest.

Two files under the plugin data directory (see ``config.data_dir``):

``profile.json``
    {"version": 1, "created", "updated", "learning": true,
     "onboarding": {"status": "complete"|"skipped", "at", "version"},
     "fields": {name: {"value", "source": "declared"|"confirmed", "at",
                       "from_proposal"?, "history"?: [{value, source, at}]}},
     "proposals": [...], "declined": [...]}        # written by the phase-2 review

``usage.jsonl``
    one ``{"at", "skill", "script", "symbol"?}`` object per line, appended by
    the phase-2 observer hook. Reserved here so paths live in one place.

Every value written to ``fields`` passes ``validate_value`` (closed
vocabularies) and carries its provenance. There is no ``inferred`` source: an
inference is a proposal until the user confirms it. Stdlib only, so the
session-start hook can run this before the virtualenv exists.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from second_opinion import config
from second_opinion.errors import ApiError, InvalidInput

PROFILE_FILE = "profile.json"
USAGE_FILE = "usage.jsonl"
INTERVIEW_VERSION = 1

APPROACHES = ("value", "growth", "dividend", "index", "technical", "unsure")
HORIZONS = ("years", "months", "weeks", "mixed")
RISK = ("low", "moderate", "high")
EXPERIENCE = ("beginner", "intermediate", "experienced")
PRE_TRADE_CHECKS = ("valuation", "fundamentals", "chart", "none")
ACCOUNT_ROLES = ("trading", "retirement", "savings")
ONBOARDING_STATUSES = ("complete", "skipped")
SOURCES = ("declared", "confirmed")

# field -> kind. Kinds: "choice" (one of a tuple), "choices" (list from a
# tuple), "text_list", "bool", "roles" (account_id -> role).
FIELDS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "approach": ("choices", APPROACHES),
    "horizon": ("choice", HORIZONS),
    "risk_appetite": ("choice", RISK),
    "experience": ("choice", EXPERIENCE),
    "goals": ("text_list", None),
    "pre_trade_check": ("choice", PRE_TRADE_CHECKS),
    "account_roles": ("roles", ACCOUNT_ROLES),
    "trades_actively": ("bool", None),
    "uses_options": ("bool", None),
}

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def profile_path() -> Path:
    return config.data_dir() / PROFILE_FILE


def usage_path() -> Path:
    return config.data_dir() / USAGE_FILE


def _today(today: date | None) -> str:
    return (today or date.today()).isoformat()


def _corrupt(path: Path, why: str) -> ApiError:
    return ApiError(f"profile at {path} {why}", code="PROFILE_CORRUPT", hint=f"move or delete {path}")


def load() -> dict[str, Any] | None:
    """The profile, or None when no file exists. Raises PROFILE_CORRUPT on damage."""
    path = profile_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise _corrupt(path, "is not valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict) or not isinstance(data.get("onboarding"), dict):
        raise _corrupt(path, "has an unexpected shape")
    if "proposals" in data and not isinstance(data["proposals"], list):
        raise _corrupt(path, "has an unexpected shape")
    if "declined" in data and not isinstance(data["declined"], list):
        raise _corrupt(path, "has an unexpected shape")
    if "learning" in data and not isinstance(data["learning"], bool):
        raise _corrupt(path, "has an unexpected shape")
    if "version" in data and not isinstance(data["version"], int):
        raise _corrupt(path, "has an unexpected shape")
    data.setdefault("proposals", [])
    data.setdefault("declined", [])
    data.setdefault("learning", True)
    return data


def save(profile: dict[str, Any]) -> Path:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=1) + "\n")
    return path


def new_profile(status: str, today: date | None = None) -> dict[str, Any]:
    if status not in ONBOARDING_STATUSES:
        raise InvalidInput(f"onboarding status must be one of {', '.join(ONBOARDING_STATUSES)}")
    day = _today(today)
    return {
        "version": 1,
        "created": day,
        "updated": day,
        "learning": True,
        "onboarding": {"status": status, "at": day, "version": INTERVIEW_VERSION},
        "fields": {},
        "proposals": [],
        "declined": [],
    }


def _as_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(s).strip() for s in raw]
    else:
        raise InvalidInput("expected a list or a comma-separated string")
    items = [s for s in items if s]
    if not items:
        raise InvalidInput("expected at least one item")
    return items


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise InvalidInput(f"expected yes or no, got {raw!r}")


def validate_value(field: str, raw: Any) -> Any:
    """Normalize ``raw`` for ``field`` or raise InvalidInput naming the allowed values."""
    if field not in FIELDS:
        raise InvalidInput(f"unknown field {field!r}; fields are {', '.join(FIELDS)}")
    kind, allowed = FIELDS[field]
    if kind == "choice":
        v = str(raw).strip().lower()
        if v not in allowed:  # type: ignore[operator]
            raise InvalidInput(f"{field} must be one of {', '.join(allowed)}")  # type: ignore[arg-type]
        return v
    if kind == "choices":
        items = [s.lower() for s in _as_list(raw)]
        bad = [s for s in items if s not in allowed]  # type: ignore[operator]
        if bad:
            raise InvalidInput(f"{field} values must be from {', '.join(allowed)}; got {', '.join(bad)}")  # type: ignore[arg-type]
        return list(dict.fromkeys(items))
    if kind == "text_list":
        return _as_list(raw)
    if kind == "bool":
        return _as_bool(raw)
    # roles
    if isinstance(raw, str):
        pairs = {}
        for part in _as_list(raw):
            if "=" not in part:
                raise InvalidInput("account_roles must be id=role pairs")
            k, v = part.split("=", 1)
            pairs[k.strip()] = v.strip()
        raw = pairs
    if not isinstance(raw, dict) or not raw:
        raise InvalidInput("account_roles must be a non-empty map of account id to role")
    out = {}
    for k, v in raw.items():
        role = str(v).strip().lower()
        if role not in ACCOUNT_ROLES:
            raise InvalidInput(f"account role must be one of {', '.join(ACCOUNT_ROLES)}; got {v!r}")
        out[str(k)] = role
    return out


def set_field(
    profile: dict[str, Any],
    field: str,
    raw: Any,
    *,
    source: str = "declared",
    from_proposal: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Write ``field`` with provenance, moving any previous value into ``history``."""
    if source not in SOURCES:
        raise InvalidInput(f"source must be one of {', '.join(SOURCES)}")
    if source == "confirmed" and not from_proposal:
        raise InvalidInput("a confirmed field needs the proposal id it came from")
    value = validate_value(field, raw)
    day = _today(today)
    entry: dict[str, Any] = {"value": value, "source": source, "at": day}
    if from_proposal:
        entry["from_proposal"] = from_proposal
    prev = profile["fields"].get(field)
    if prev is not None:
        history = list(prev.get("history") or [])
        history.append({"value": prev["value"], "source": prev["source"], "at": prev["at"]})
        entry["history"] = history
    profile["fields"][field] = entry
    profile["updated"] = day
    return profile


def unset_field(profile: dict[str, Any], field: str, *, today: date | None = None) -> dict[str, Any]:
    if field not in FIELDS:
        raise InvalidInput(f"unknown field {field!r}; fields are {', '.join(FIELDS)}")
    if field not in profile["fields"]:
        raise InvalidInput(f"{field} is not set")
    del profile["fields"][field]
    profile["updated"] = _today(today)
    return profile


# ── derived text ──────────────────────────────────────────────────────────

NO_PROFILE_LINE = (
    "No Second Opinion profile exists. Before completing the user's first finance request, "
    "run the onboarding skill's questions (or record 'skip for now'), then finish the request."
)
SKIPPED_LINE = (
    "Second Opinion profile: onboarding was skipped. Say 'get started with Second Opinion' "
    "any time to set it up; do not raise it unprompted."
)
_STEER_NOTE = "Use it to choose which analysis to run first; never to judge a security against the person."

_LABELS = {
    "approach": "approach",
    "horizon": "horizon",
    "risk_appetite": "risk appetite",
    "experience": "experience",
    "goals": "goals",
    "pre_trade_check": "pre-trade check",
    "trades_actively": "trades actively",
    "uses_options": "uses options",
}


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _truncate_goals(goals: list[str]) -> str:
    """Format up to 4 goals, truncating each to 39 chars, with 'and N more' if needed."""
    if not goals:
        return ""
    truncated = [g[:39] + "…" if len(g) > 40 else g for g in goals[:4]]
    result = ", ".join(truncated)
    if len(goals) > 4:
        result += f" and {len(goals) - 4} more"
    return result


def summary(profile: dict[str, Any]) -> str:
    """One paragraph of the declared and confirmed fields, for session context."""
    fields = profile.get("fields") or {}
    parts = []
    for k in _LABELS:
        if k not in fields:
            continue
        if k == "goals":
            goals = fields[k]["value"]
            parts.append(f"goals {_truncate_goals(goals)}")
        else:
            parts.append(f"{_LABELS[k]} {_fmt(fields[k]['value'])}")
    roles = fields.get("account_roles", {}).get("value") if "account_roles" in fields else None
    if roles:
        counts: dict[str, int] = {}
        for role in roles.values():
            counts[role] = counts.get(role, 0) + 1
        parts.append("accounts " + ", ".join(f"{n} {role}" for role, n in counts.items()))
    body = "; ".join(parts) if parts else "no fields set"
    words = body.split()
    if len(words) > 60:
        body = " ".join(words[:60]) + " …"
    return f"Second Opinion profile (declared {profile.get('created')}): {body}. {_STEER_NOTE}"


def context_line(profile: dict[str, Any] | None) -> str:
    if profile is None:
        return NO_PROFILE_LINE
    if profile.get("onboarding", {}).get("status") == "skipped" and not profile.get("fields"):
        return SKIPPED_LINE
    return summary(profile)


# ── next steps ────────────────────────────────────────────────────────────

_CONNECT = 'Connect a brokerage: say "connect my brokerage", or "connect E*Trade" if you have an E*Trade developer key.'
_FINISH_CONNECT = 'Finish connecting: say "connect my brokerage" to link an account.'
_IMPORT = 'Import your history: say "import my transaction history" so tax-aware and trade-review have two years of activity.'
_EDGAR = (
    "Set EDGAR_USER_AGENT in the plugin's .env to an app name and contact email; "
    "the SEC requires it before fundamental-research can read filings."
)
_JOURNAL = 'Journal your next trade: say "journal this trade" before you place it, so the discipline gate has a plan to check.'
_LEARNING_ONLY_WORDS = ("learn", "education", "understand", "study")

# (condition key, required skill, needs connected accounts, question)
_QUESTIONS: tuple[tuple[str, str, bool, str], ...] = (
    ("accounts", "portfolio-snapshot", True, "How is my portfolio doing today?"),
    ("approach:value", "valuation", False, "Does KO pass Graham's defensive-investor tests, and what are its owner earnings?"),
    ("approach:growth", "valuation", False, "What's a fair price for NVDA, and what growth is the market pricing in?"),
    ("approach:dividend", "dividend-income", True, "How much dividend income will I earn this year, and in which months?"),
    ("approach:technical", "trading", False, "Chart AMD's trend. Where are support and resistance?"),
    ("approach:index", "rebalancing", True, "I'm targeting 60/40. How far off am I?"),
    ("approach:unsure", "financial-education", False, "Quiz me to find my level, then teach me one concept."),
    ("goal:retire", "retirement", False, "Am I on track to retire at 60?"),
    ("goal:house", "real-estate", False, "Rent vs buy on a $750k home at 6.5%, against $3,200 rent."),
    ("goal:income", "dividend-income", True, "How much dividend income will I earn this year, and in which months?"),
    ("goal:learn", "financial-education", False, "Quiz me to find my level, then teach me one concept."),
    ("always", "market-analysis", False, "How are markets doing today? What is the yield curve saying?"),
)
_GOAL_KEYS = {"retire": ("retire",), "house": ("house", "home", "condo", "property"), "income": ("income",), "learn": ("learn", "education")}


def next_steps(
    profile: dict[str, Any],
    *,
    installed: set[str],
    brokerage_configured: bool,
    connected_accounts: int,
    edgar_configured: bool,
) -> dict[str, list[str]]:
    """Deterministic setup actions and starter questions from the profile, connection state and installed skills."""
    fields = profile.get("fields") or {}
    approach = set(fields.get("approach", {}).get("value") or [])
    goal_list = fields.get("goals", {}).get("value") or []
    goals = " ".join(goal_list).lower()
    trades = bool(fields.get("trades_actively", {}).get("value"))
    learning_only = bool(goal_list) and all(any(w in g.lower() for w in _LEARNING_ONLY_WORDS) for g in goal_list)

    setup: list[str] = []
    if not learning_only and "connect" in installed and not brokerage_configured:
        setup.append(_CONNECT)
    elif not learning_only and "connect" in installed and brokerage_configured and connected_accounts == 0:
        setup.append(_FINISH_CONNECT)
    if connected_accounts > 0 and "statement-import" in installed:
        setup.append(_IMPORT)
    if "value" in approach and "fundamental-research" in installed and not edgar_configured:
        setup.append(_EDGAR)
    if trades and "trade-journal" in installed:
        setup.append(_JOURNAL)

    conditions = {"always"}
    if connected_accounts > 0:
        conditions.add("accounts")
    conditions.update(f"approach:{a}" for a in approach)
    for key, words in _GOAL_KEYS.items():
        if any(w in goals for w in words):
            conditions.add(f"goal:{key}")

    asks: list[str] = []
    for cond, skill, needs_accounts, question in _QUESTIONS:
        if cond not in conditions or skill not in installed or question in asks:
            continue
        if needs_accounts and connected_accounts == 0:
            continue
        if cond == "always" and asks:
            continue  # the market question is the fallback, not a filler
        asks.append(question)
        if len(asks) == 5:
            break
    return {"setup": setup, "try_asking": asks}
