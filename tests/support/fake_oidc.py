"""A pretend OpenID Connect provider for the sign-in tests: its configuration, its keys, its tokens."""
import json
import time
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

ISSUER = "https://login.example.org/realms/facility"


def _key(kid: str):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = jwk.construct(private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), "RS256").to_dict()
    public.update({"kid": kid, "use": "sig", "alg": "RS256"})
    for name, value in list(public.items()):
        if isinstance(value, bytes):
            public[name] = value.decode()
    return pem, public


class _Response:
    def __init__(self, status: int, body: Any):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class FakeProvider:
    """Answers get/post as httpx would, for one issuer."""

    def __init__(self, issuer: str = ISSUER, clientId: str = "scipionweb"):
        self.issuer = issuer
        self.clientId = clientId
        self.pem, self.public = _key("key-1")
        self.claims: Dict[str, Any] = {}
        self.posts: List[Dict[str, Any]] = []
        self.tokenStatus = 200

    def config(self) -> Dict[str, Any]:
        return {"issuer": self.issuer, "authorization_endpoint": self.issuer + "/protocol/openid-connect/auth",
                "token_endpoint": self.issuer + "/protocol/openid-connect/token",
                "jwks_uri": self.issuer + "/protocol/openid-connect/certs",
                "userinfo_endpoint": self.issuer + "/protocol/openid-connect/userinfo",
                "end_session_endpoint": self.issuer + "/protocol/openid-connect/logout"}

    def idToken(self, nonce: Optional[str], **change) -> str:
        now = int(time.time())
        claims = dict({"iss": self.issuer, "aud": self.clientId, "sub": "f1e2-user", "iat": now, "exp": now + 300,
                       "nonce": nonce, "email": "ana@facility.example.org", "email_verified": True,
                       "given_name": "Ana", "family_name": "Lopez"}, **self.claims)
        claims.update(change)
        return jwt.encode({key: value for key, value in claims.items() if value is not None}, self.pem,
                          algorithm="RS256", headers={"kid": "key-1"})

    def get(self, url, timeout=None, headers=None):
        if url.endswith("/.well-known/openid-configuration"):
            return _Response(200, self.config()) if url.startswith(self.issuer) else _Response(404, {})
        if url.endswith("/certs"):
            return _Response(200, {"keys": [self.public]})
        if url.endswith("/userinfo"):
            return _Response(200, {"sub": "f1e2-user", "email": "ana@facility.example.org", "email_verified": True})
        return _Response(404, {})

    def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append(dict(data or {}))
        if self.tokenStatus != 200:
            return _Response(self.tokenStatus, {"error": "invalid_grant"})
        return _Response(200, {"access_token": "access", "token_type": "Bearer",
                               "id_token": self.idToken(self.nonce)})

    nonce: Optional[str] = None
