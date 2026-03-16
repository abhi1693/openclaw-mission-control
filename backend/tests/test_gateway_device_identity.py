from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.services.openclaw.device_identity import (
    build_device_auth_payload,
    load_or_create_device_identity,
    sign_device_payload,
)


def _base64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def test_load_or_create_device_identity_persists_same_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    identity_path = tmp_path / "identity" / "device.json"
    monkeypatch.setenv("OPENCLAW_GATEWAY_DEVICE_IDENTITY_PATH", str(identity_path))

    first = load_or_create_device_identity()
    second = load_or_create_device_identity()

    assert identity_path.exists()
    assert first.device_id == second.device_id
    assert first.public_key_pem.strip() == second.public_key_pem.strip()
    assert first.private_key_pem.strip() == second.private_key_pem.strip()


def test_build_device_auth_payload_uses_nonce_for_v2() -> None:
    payload = build_device_auth_payload(
        device_id="dev",
        client_id="gateway-client",
        client_mode="backend",
        role="operator",
        scopes=["operator.read", "operator.admin"],
        signed_at_ms=123,
        token="token",
        nonce="nonce-xyz",
    )

    assert payload == (
        "v2|dev|gateway-client|backend|operator|operator.read,operator.admin|123|token|nonce-xyz"
    )


def test_sign_device_payload_produces_valid_ed25519_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    identity_path = tmp_path / "identity" / "device.json"
    monkeypatch.setenv("OPENCLAW_GATEWAY_DEVICE_IDENTITY_PATH", str(identity_path))
    identity = load_or_create_device_identity()

    payload = "v1|device|client|backend|operator|operator.read|1|token"
    signature = sign_device_payload(identity.private_key_pem, payload)

    loaded = serialization.load_pem_public_key(identity.public_key_pem.encode("utf-8"))
    assert isinstance(loaded, Ed25519PublicKey)
    loaded.verify(_base64url_decode(signature), payload.encode("utf-8"))
