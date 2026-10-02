"""SnapTrade SDK client in Personal API key mode.

Personal keys represent one human: there is no registered SnapTrade user and
no user_secret, so callers never pass user_id/user_secret.

The module also monkey-patches the SDK's request-signature computation. The
stock implementation calls ``json.dumps`` with no encoder and crashes on the
``Decimal`` values the SDK's own validators *require* for ``units``/``price``;
without this patch every order call returns 401 "Unable to verify signature".

The ``snaptrade_client`` package is imported lazily (inside ``_sdk()``) rather
than at module top: every script in this plugin imports this module, and
``output.run`` maps a missing dependency (``ImportError``) to exit code 6 —
but only if the import happens inside the script's main function, not while
this module is being loaded.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from base64 import b64encode
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from second_opinion import config
from second_opinion.config import Settings, SnapTradeSettings

if TYPE_CHECKING:
    from snaptrade_client import SnapTrade

_patch_applied = False


def _sdk() -> Any:
    import snaptrade_client

    return snaptrade_client


def _decimal_safe_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        if o == o.to_integral_value():
            return int(o)
        return float(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


def _patched_compute_request_signature(path: str, consumer_key: str, body: Any) -> str:
    # Must stay byte-for-byte identical to the SDK's own sig_object — SnapTrade
    # signs the path exactly as the SDK passes it; any deviation yields 401.
    schemas = _sdk().schemas
    subpath, query = path.split("?")
    sig_object = {
        "content": None if body is schemas.unset or body == {} else body,
        "path": subpath,
        "query": query,
    }
    sig_content = json.dumps(sig_object, separators=(",", ":"), sort_keys=True, default=_decimal_safe_default)
    sig_digest = hmac.new(consumer_key.encode(), sig_content.encode(), hashlib.sha256).digest()
    return b64encode(sig_digest).decode()


def _apply_patch() -> None:
    global _patch_applied
    if _patch_applied:
        return
    _sdk().request_after_hook.compute_request_signature = _patched_compute_request_signature
    _patch_applied = True


_cached: tuple[SnapTradeSettings, "SnapTrade"] | None = None


def reset_cache() -> None:
    global _cached
    _cached = None


def get_client(settings: Settings | None = None) -> "SnapTrade":
    global _cached
    _apply_patch()
    s = (settings or config.load_settings()).require_snaptrade()
    if _cached is not None and _cached[0] == s:
        return _cached[1]
    sdk_module = _sdk()
    sdk = sdk_module.SnapTrade(
        auth=sdk_module.SnapTradeAuth.personal_api_key(consumer_key=s.consumer_key, client_id=s.client_id)
    )
    _cached = (s, sdk)
    return sdk


def get_commercial_client(settings: Settings | None = None) -> "SnapTrade":
    """Same key in commercial mode. Only used for key-level operations that
    personal mode cannot perform (registering the key's single user)."""
    _apply_patch()
    s = (settings or config.load_settings()).require_snaptrade()
    sdk_module = _sdk()
    return sdk_module.SnapTrade(
        auth=sdk_module.SnapTradeAuth.commercial_api_key(consumer_key=s.consumer_key, client_id=s.client_id)
    )
