"""Unit tests for the JWT verifier with stubbed JWKS.

We generate an RSA keypair in-test, mint our own tokens, mock the JWKS
endpoint, and exercise: valid token, expired token, wrong audience, missing
tenant_id claim, tampered signature.

``@respx.mock`` monkeypatches httpx's default transport for the duration of
the decorated function, so the JWTVerifier's internal ``httpx.AsyncClient()``
gets intercepted automatically.
"""

from __future__ import annotations

import base64
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from sentinelrag_shared.auth import JWTVerifier, JWTVerifierError

ISSUER = "http://kc.local/realms/sentinelrag"
AUDIENCE = "sentinelrag-api"
JWKS_URL = "http://kc.local/realms/sentinelrag/protocol/openid-connect/certs"
KID = "test-kid-1"


def _b64(n: int) -> str:
    return base64.urlsafe_b64encode(
        n.to_bytes((n.bit_length() + 7) // 8, "big")
    ).rstrip(b"=").decode("ascii")


def _generate_rsa_keypair() -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": KID,
        "n": _b64(public_numbers.n),
        "e": _b64(public_numbers.e),
    }
    return private_key, jwk


def _sign(payload: dict[str, Any], private_key: Any) -> str:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": KID})


def _stub_jwks(jwk: dict[str, Any]) -> None:
    """Register the JWKS route with respx. Call inside an @respx.mock test."""
    respx.get(JWKS_URL).mock(
        return_value=httpx.Response(200, json={"keys": [jwk]})
    )


def _verifier() -> JWTVerifier:
    """Build a verifier that uses the default httpx.AsyncClient (which respx hooks)."""
    return JWTVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
    )


@pytest.fixture
def keypair_and_jwks() -> tuple[Any, dict[str, Any]]:
    return _generate_rsa_keypair()


@pytest.fixture
def base_claims() -> dict[str, Any]:
    now = int(time.time())
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(uuid4()),
        "tenant_id": str(uuid4()),
        "email": "alice@example.com",
        "iat": now,
        "exp": now + 600,
        "nbf": now - 5,
    }


@pytest.mark.unit
class TestJWTVerifier:
    @respx.mock
    @pytest.mark.asyncio
    async def test_valid_token_passes(self, keypair_and_jwks, base_claims) -> None:
        priv, jwk = keypair_and_jwks
        _stub_jwks(jwk)
        verifier = _verifier()
        token = _sign(base_claims, priv)

        result = await verifier.verify(token)
        assert str(result.sub) == base_claims["sub"]
        assert str(result.tenant_id) == base_claims["tenant_id"]
        assert result.email == base_claims["email"]

        await verifier.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, keypair_and_jwks, base_claims) -> None:
        priv, jwk = keypair_and_jwks
        _stub_jwks(jwk)
        verifier = _verifier()
        base_claims["exp"] = int(time.time()) - 60
        token = _sign(base_claims, priv)

        with pytest.raises(JWTVerifierError, match="expired"):
            await verifier.verify(token)
        await verifier.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self, keypair_and_jwks, base_claims) -> None:
        priv, jwk = keypair_and_jwks
        _stub_jwks(jwk)
        verifier = _verifier()
        base_claims["aud"] = "some-other-service"
        token = _sign(base_claims, priv)

        with pytest.raises(JWTVerifierError):
            await verifier.verify(token)
        await verifier.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_missing_tenant_claim_rejected(
        self, keypair_and_jwks, base_claims
    ) -> None:
        priv, jwk = keypair_and_jwks
        _stub_jwks(jwk)
        verifier = _verifier()
        base_claims.pop("tenant_id")
        token = _sign(base_claims, priv)

        with pytest.raises(JWTVerifierError, match="tenant_id"):
            await verifier.verify(token)
        await verifier.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_tampered_signature_rejected(
        self, keypair_and_jwks, base_claims
    ) -> None:
        priv, jwk = keypair_and_jwks
        _stub_jwks(jwk)
        verifier = _verifier()
        token = _sign(base_claims, priv)
        # Replace 16 chars of the signature. A single-char flip can be a
        # base64 no-op when padding is involved; 16 chars guarantees a
        # different decoded signature.
        tampered = token[:-16] + ("A" * 16)
        with pytest.raises(JWTVerifierError):
            await verifier.verify(tampered)
        await verifier.close()
