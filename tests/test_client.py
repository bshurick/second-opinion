from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal

import pytest

pytest.importorskip("snaptrade_client")

from snaptrade_client import request_after_hook  # noqa: E402

from second_opinion import client  # noqa: E402
from second_opinion.config import Settings, SnapTradeSettings  # noqa: E402


def test_patch_is_installed_on_import() -> None:
    client.reset_cache()
    client.get_client(Settings(snaptrade=SnapTradeSettings(client_id="cid", consumer_key="ck")))
    assert request_after_hook.compute_request_signature is client._patched_compute_request_signature


def test_signature_serializes_decimal_like_snaptrade() -> None:
    body = {"units": Decimal("1"), "price": Decimal("12.5")}
    sig = client._patched_compute_request_signature("/api/v1/trade/impact?clientId=c&timestamp=1", "key", body)
    expected_obj = {"content": {"units": 1, "price": 12.5}, "path": "/api/v1/trade/impact", "query": "clientId=c&timestamp=1"}
    expected = base64.b64encode(
        hmac.new(b"key", json.dumps(expected_obj, separators=(",", ":"), sort_keys=True).encode(), hashlib.sha256).digest()
    ).decode()
    assert sig == expected


def test_get_client_uses_personal_auth_and_caches() -> None:
    client.reset_cache()
    s = Settings(snaptrade=SnapTradeSettings(client_id="cid", consumer_key="ck"))
    a = client.get_client(s)
    b = client.get_client(s)
    assert a is b
    config = a.account_information.api_client.configuration
    assert config.api_key.get("PartnerClientId") == "cid"
    assert config.auth_mode == "personalApiKey"
