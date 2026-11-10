"""Signing in with an institution's account: the ID token checks and where the browser may go back to."""
import time

import pytest

from app.backend.api.services import sign_in
from tests.support.fake_oidc import FakeProvider


@pytest.fixture(autouse=True)
def emptyCache(monkeypatch):
    monkeypatch.setattr(sign_in, "_cache", {})


def _check(fake, token, nonce="n-1"):
    provider = {"key": "facility", "clientId": fake.clientId}
    return sign_in.checkIdToken(token, provider, fake.config(), nonce, http=fake)


def test_AGoodIdTokenGivesWhoSignedIn():
    fake = FakeProvider()
    claims = _check(fake, fake.idToken("n-1"))
    assert (claims["sub"], claims["email"], claims["email_verified"]) == ("f1e2-user", "ana@facility.example.org", True)


@pytest.mark.parametrize("change, message", [
    ({"sub": "f1e2-user"}, None),
    ({"aud": "another-app"}, "could not be verified"),
    ({"iss": "https://evil.example.org"}, "could not be verified"),
    ({"exp": int(time.time()) - 600, "iat": int(time.time()) - 900}, "could not be verified"),
])
def test_AnIdTokenThatIsNotForThisSignInIsRefused(change, message):
    fake = FakeProvider()
    if message is None:
        # Another sign-in's token (another nonce)
        with pytest.raises(sign_in.SignInError, match="does not belong to this sign-in"):
            _check(fake, fake.idToken("other", **change))
        return
    with pytest.raises(sign_in.SignInError, match=message):
        _check(fake, fake.idToken("n-1", **change))


def test_AnIdTokenSignedByAnotherKeyIsRefused():
    fake, impostor = FakeProvider(), FakeProvider()
    with pytest.raises(sign_in.SignInError, match="could not be verified"):
        _check(fake, impostor.idToken("n-1"))


def test_AnUnsignedIdTokenIsRefused():
    from jose import jwt

    fake = FakeProvider()
    token = jwt.encode({"sub": "x", "nonce": "n-1"}, "secret", algorithm="HS256")
    with pytest.raises(sign_in.SignInError, match="not signed in a way"):
        _check(fake, token)


def test_TheBrowserGoesBackOnlyToThisInstallationsWeb():
    own = ["https://scipion.cnb.csic.es", "http://api.local:8080"]
    assert sign_in.returnAllowed("https://scipion.cnb.csic.es/auth/sso", own)
    assert sign_in.returnAllowed("http://localhost:5173/auth/sso", own)
    assert not sign_in.returnAllowed("https://evil.example.org/auth/sso", own)
    assert not sign_in.returnAllowed("javascript:alert(1)", own)
    assert not sign_in.returnAllowed("//evil.example.org/x", own)


def test_ThePkceChallengeIsTheVerifiersHash():
    # RFC 7636, appendix B
    assert sign_in._codeChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_TheClientSecretIsKeptEncrypted():
    stored = sign_in.encryptSecret("s3cret")
    assert stored and "s3cret" not in stored and sign_in.decryptSecret(stored) == "s3cret"
    assert sign_in.encryptSecret("") is None and sign_in.decryptSecret(None) is None
