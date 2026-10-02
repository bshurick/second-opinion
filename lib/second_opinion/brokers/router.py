"""Hub: every configured broker behind one object, dispatching by account id."""
from __future__ import annotations

from typing import Any

from second_opinion import config
from second_opinion.brokerage import OrderSpec
from second_opinion.brokers import registry as registry_mod
from second_opinion.brokers.base import DIRECT_INSTITUTIONS, Broker, apply_account_types
from second_opinion.brokers.snaptrade import SnapTradeBroker
from second_opinion.errors import ApiError, ConfigError, InvalidInput, ScriptError


def _shadow_key(row: dict[str, Any]) -> str:
    return str(row.get("account_number") or "").strip().lstrip("0")


def _last4(number: str) -> str:
    return "".join(c for c in number if c.isdigit())[-4:]


def _last4_hit(by_number: dict[tuple[str, str], str], broker: str, key: str) -> str | None:
    """Masked or truncated SnapTrade numbers ("****5188") still name a direct account."""
    tail = _last4(key)
    if len(tail) < 4:
        return None
    for (b, number), account_id in by_number.items():
        if b != broker:
            continue
        if key.isdigit() and len(key) >= len(number):
            continue  # a full number that simply differs is a different account
        if _last4(number) == tail:
            return account_id
    return None


def merge_accounts(direct: list[dict[str, Any]], snaptrade: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Direct rows first; SnapTrade rows for the same brokerage account are shadowed.

    Returns (kept, shadowed, warnings). A SnapTrade row at an institution a
    direct adapter serves, whose number matches none of that adapter's accounts,
    is kept but flagged POSSIBLE_DUPLICATE rather than silently hidden.
    """
    by_number: dict[tuple[str, str], str] = {}
    by_id: dict[tuple[str, str], str] = {}
    for r in direct:
        by_number[(r["broker"], _shadow_key(r))] = r["account_id"]
        by_id[(r["broker"], str(r["account_id"]))] = r["account_id"]  # SnapTrade reports E*Trade's accountIdKey as the number
    served = {r["broker"] for r in direct}
    kept: list[dict[str, Any]] = list(direct)
    shadowed: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for r in snaptrade:
        inst = str(r.get("institution_name") or "").upper()
        hit = None
        institution_of = None
        for broker, needles in DIRECT_INSTITUTIONS.items():
            if broker not in served or not any(n in inst for n in needles):
                continue
            institution_of = broker
            key = _shadow_key(r)
            raw_number = str(r.get("account_number") or "").strip()
            hit = by_number.get((broker, key)) or by_id.get((broker, raw_number)) or _last4_hit(by_number, broker, key)
            if hit:
                shadowed.append({"snaptrade_account_id": r["account_id"], "direct_account_id": hit, "broker": broker})
                break
        if not hit:
            kept.append(r)
            if institution_of is not None:
                warnings.append({"snaptrade_account_id": r["account_id"], "broker": institution_of, "code": "POSSIBLE_DUPLICATE"})
    return kept, shadowed, warnings


def holdings_source(accounts: list[dict[str, Any]]) -> str | None:
    """The broker name behind a set of account rows, "mixed", or None for no rows."""
    names = {str(a.get("broker") or "snaptrade") for a in accounts}
    if not names:
        return None
    return "mixed" if len(names) > 1 else names.pop()


PARTIAL_FLAG = "--partial"


def _login_required(code: str | None) -> bool:
    """A broker outage the user can fix in chat by logging in (E*Trade's daily token)."""
    return bool(code) and code.endswith("_REAUTH")


class Hub:
    def __init__(self, brokers: list[Broker], account_types: dict[str, str], registry: registry_mod.Registry | None, partial: bool = False) -> None:
        if not brokers:
            raise ConfigError("no brokerage credentials configured", hint=config.NO_BROKER_HINT)
        self.brokers = brokers
        self.account_types = account_types
        self.registry = registry
        # False: a broker that only needs a login stops the listing with the login URL,
        # so the user is asked to sign in before any partial result is shown. True (the
        # scripts' --partial flag): run without that broker and carry a BROKER_UNAVAILABLE flag.
        self.partial = partial
        self.shadowed: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.broker_errors: list[dict[str, Any]] = []
        self._memory: dict[str, str] = {}
        self._rows: list[dict[str, Any]] = []  # every row of the last list_accounts, shadowed ones included

    # ── accounts ──────────────────────────────────────────────────────────
    def for_broker(self, name: str) -> Broker:
        for b in self.brokers:
            if b.name == name:
                return b
        hint = config.SETUP_HINT if name == "snaptrade" else config.ETRADE_SETUP_HINT if name == "etrade" else config.NO_BROKER_HINT
        raise ConfigError(f"{name} is not configured", hint=hint)

    def list_accounts(self, include_closed: bool = False, include_shadowed: bool = False) -> list[dict[str, Any]]:
        """One broker's outage never hides the others: it lands in ``broker_errors``.

        The exception is a broker that only needs a login (``*_REAUTH``): unless the hub
        is ``partial``, that raises with the login URL so the user is asked to sign in
        before anything partial is shown.
        """
        direct: list[dict[str, Any]] = []
        snap: list[dict[str, Any]] = []
        self.broker_errors = []
        first_error: ScriptError | None = None
        login_needed: tuple[Broker, ScriptError] | None = None
        for b in self.brokers:
            try:
                rows = b.list_accounts(include_closed=include_closed)
            except (ConfigError, ApiError) as e:
                first_error = first_error or e
                if login_needed is None and _login_required(e.code):
                    login_needed = (b, e)
                self.broker_errors.append({
                    "broker": b.name,
                    "code": e.code,
                    "message": str(e),
                    **{k: v for k, v in e.extra.items() if k in ("url", "hint", "sandbox")},
                })
                continue
            (snap if b.name == "snaptrade" else direct).extend(rows)
        if login_needed is not None and not self.partial:
            raise self._login_error(*login_needed)
        if first_error is not None and len(self.broker_errors) == len(self.brokers):
            raise first_error  # every broker is down: never print an empty account list
        merged, self.shadowed, self.warnings = merge_accounts(direct, snap)
        all_rows = direct + snap
        apply_account_types(all_rows, self.account_types)
        shadowed_by = {s["snaptrade_account_id"]: s["direct_account_id"] for s in self.shadowed}
        self._rows = all_rows
        for r in all_rows:
            self._memory[r["account_id"]] = r["broker"]
            if r["account_id"] in shadowed_by:
                r["shadowed_by"] = shadowed_by[r["account_id"]]
        if self.registry is not None:
            self.registry.save(all_rows, preserve_brokers=tuple(e["broker"] for e in self.broker_errors))
        return all_rows if include_shadowed else merged

    def _login_error(self, broker: Broker, err: ScriptError) -> ConfigError:
        """``err`` with the broker's login URL (when it can be issued) and the way to skip the login."""
        extra = {k: v for k, v in err.extra.items() if k in ("url", "hint", "sandbox")}
        start = getattr(broker, "login_url", None)
        if "url" not in extra and callable(start):
            try:
                extra["url"] = start()
            except ScriptError:
                pass  # the login is still the fix; the connect skill can issue the URL itself
        return ConfigError(str(err), code=err.code, **extra, partial=PARTIAL_FLAG)

    # ── surfaces for scripts ──────────────────────────────────────────────
    def unavailable_flags(self) -> list[dict[str, Any]]:
        """One flag per broker that failed the last ``list_accounts``."""
        return [
            {"code": "BROKER_UNAVAILABLE", "message": f"{e['broker']}: {e['message']}; its accounts are excluded from this run"}
            for e in self.broker_errors
        ]

    def _error_for_failed_broker(self, ids: list[str]) -> dict[str, Any] | None:
        """The recorded error of a failed broker one of ``ids`` is known to belong to."""
        if not self.broker_errors:
            return None
        by_broker = {e["broker"]: e for e in self.broker_errors}
        cached = self.registry.load() if self.registry is not None else {}
        for account_id in ids:
            name = self._memory.get(account_id)
            if name is None:
                row = cached.get(account_id)
                name = row.get("broker") if isinstance(row, dict) else None
            if name in by_broker:
                return by_broker[name]
        return None

    def _numbered_as(self, account_id: str) -> dict[str, Any] | None:
        """The listed row whose ``account_number`` is ``account_id``.

        SnapTrade reports an E*Trade account's ``accountIdKey`` — the id the direct
        adapter uses — as its account_number, so a direct id pasted into a hub without
        that adapter configured names the SnapTrade twin's number, not any account_id.
        """
        for r in self._rows:
            if str(r.get("account_number") or "").strip() == account_id and r.get("account_id") != account_id:
                return r
        return None

    def _twin_notes(self, ids: list[str]) -> str:
        notes = []
        for account_id in ids:
            row = self._numbered_as(account_id)
            if row is None:
                continue
            inst = str(row.get("institution_name") or "").upper()
            direct = next((b for b, needles in DIRECT_INSTITUTIONS.items() if any(n in inst for n in needles)), None)
            why = f"; the direct {direct} adapter, whose account ids look like this, is not configured here" if direct and direct not in {b.name for b in self.brokers} else ""
            notes.append(f" (note: {account_id} is the account_number of {row.get('broker')} account {row['account_id']}, not an account_id — use {row['account_id']}{why})")
        return "".join(notes)

    def unknown_account_error(self, account_ids: str | list[str]) -> ScriptError:
        """Ids unknown only because their own broker could not be listed report that broker's error.

        A typo is still exit 2 with the accounts.py hint; a broker that is down is
        mentioned there but never blamed for an id that was never its own. An id that
        is really a listed account's ``account_number`` names that account.
        """
        ids = [account_ids] if isinstance(account_ids, str) else list(account_ids)
        joined = ", ".join(ids)
        owner = self._error_for_failed_broker(ids)
        if owner is not None:
            extra = {k: v for k, v in owner.items() if k in ("url", "hint", "sandbox")}
            return ConfigError(f"account id(s) {joined} could not be checked — {owner['broker']}: {owner['message']}", code=owner["code"], **extra)
        note = "".join(f" (note: {e['broker']} is unavailable: {e['message']})" for e in self.broker_errors[:1])
        return InvalidInput(f"unknown account id(s): {joined}; run accounts.py to list them{note}{self._twin_notes(ids)}")

    def unknown_account_flags(self, account_ids: list[str]) -> list[dict[str, Any]]:
        """One UNKNOWN_ACCOUNT flag per id a script skipped, worded like ``unknown_account_error``."""
        flags = []
        for account_id in account_ids:
            owner = self._error_for_failed_broker([account_id])
            if owner is not None:
                message = f"account id {account_id} could not be checked — {owner['broker']}: {owner['message']}; it is excluded from this run"
            else:
                message = f"unknown account id {account_id}; run accounts.py to list them{self._twin_notes([account_id])}; it is excluded from this run"
            flags.append({"code": "UNKNOWN_ACCOUNT", "message": message})
        return flags

    def duplicate_flags(self) -> list[dict[str, Any]]:
        return [
            {"code": "POSSIBLE_DUPLICATE", "message": f"SnapTrade account {w['snaptrade_account_id']} is at a brokerage {w['broker']} also serves directly but no account number matched; it may be counted twice"}
            for w in self.warnings
        ]

    def _broker_for(self, account_id: str) -> Broker:
        if len(self.brokers) == 1:
            return self.brokers[0]
        name = self._memory.get(account_id) or (self.registry.broker_of(account_id) if self.registry else None)
        if name is None:
            self.list_accounts(include_closed=True, include_shadowed=True)
            name = self._memory.get(account_id)
        if name is None:
            raise InvalidInput(f"account {account_id!r} belongs to no configured broker", code="UNKNOWN_ACCOUNT", hint="run accounts.py and use one of its account_id values")
        return self.for_broker(name)

    def _shadowed_by(self, account_id: str) -> str | None:
        for s in self.shadowed:
            if s["snaptrade_account_id"] == account_id:
                return str(s["direct_account_id"])
        if self.registry is not None:
            row = self.registry.load().get(account_id)
            if isinstance(row, dict) and row.get("shadowed_by"):
                return str(row["shadowed_by"])
        return None

    def _guard_shadowed(self, account_id: str) -> None:
        """A shadowed SnapTrade account is a second door to an account traded directly."""
        direct = self._shadowed_by(account_id)
        if direct:
            raise InvalidInput(
                f"account {account_id!r} is the SnapTrade copy of an account served directly; orders must go through the direct account",
                code="SHADOWED_ACCOUNT",
                hint=f"use the direct account {direct}",
            )

    # ── account-scoped calls ──────────────────────────────────────────────
    def get_portfolio(self, account_id: str) -> dict[str, Any]:
        return self._broker_for(account_id).get_portfolio(account_id)

    def get_balance(self, account_id: str) -> dict[str, Any]:
        return self._broker_for(account_id).get_balance(account_id)

    def list_orders(self, account_id: str, status: str | None = None, symbol: str | None = None, count: int = 25) -> list[dict[str, Any]]:
        return self._broker_for(account_id).list_orders(account_id, status=status, symbol=symbol, count=count)

    def list_transactions(self, account_id: str, start: str | None = None, end: str | None = None, count: int = 50) -> dict[str, Any]:
        return self._broker_for(account_id).list_transactions(account_id, start=start, end=end, count=count)

    def preview_order(self, spec: OrderSpec) -> dict[str, Any]:
        broker = self._broker_for(spec.account_id)
        self._guard_shadowed(spec.account_id)
        return broker.preview_order(spec)

    def place_order(self, spec: OrderSpec) -> dict[str, Any]:
        broker = self._broker_for(spec.account_id)
        self._guard_shadowed(spec.account_id)
        return broker.place_order(spec)

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        broker = self._broker_for(account_id)
        self._guard_shadowed(account_id)
        return broker.cancel_order(account_id, order_id)

    # ── quotes and status ─────────────────────────────────────────────────
    def quote(self, symbols: list[str]) -> list[dict[str, Any]] | None:
        for b in self.brokers:
            if b.name == "snaptrade":
                continue
            try:
                rows = b.quote(symbols)
            except Exception:  # noqa: BLE001 — quotes are best-effort; Yahoo is the fallback
                rows = None
            if rows:
                return rows
        return None

    def statuses(self) -> list[dict[str, Any]]:
        return [b.connection_status() for b in self.brokers if b.name != "snaptrade"]


def build(settings: config.Settings, registry: registry_mod.Registry | None = None) -> Hub:
    brokers: list[Broker] = []
    if settings.etrade is not None:
        from second_opinion.brokers.etrade import ETradeBroker
        from second_opinion.brokers.etrade_auth import ETradeAuth

        brokers.append(ETradeBroker(ETradeAuth(settings.etrade)))
    if settings.snaptrade is not None:
        brokers.append(SnapTradeBroker())
    if not brokers:
        raise ConfigError("no brokerage credentials configured", hint=config.NO_BROKER_HINT)
    return Hub(brokers, settings.account_types, registry if registry is not None else registry_mod.Registry())


def load(settings: config.Settings | None = None) -> Hub:
    return build(settings or config.load_settings())


def try_load() -> Hub | None:
    """A hub for best-effort quote routing; None when nothing is configured."""
    try:
        return load()
    except ConfigError:
        return None
