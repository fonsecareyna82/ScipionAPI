"""Signing in with an institution's account against the migrated database, with a pretend provider."""
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.backend.api.services import sign_in
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.sign_in_mapper import SignInPostgresqlMapper
from tests.support.fake_oidc import FakeProvider

CALLBACK = "http://api.local/api/auth/oidc/facility/callback"
RETURN = "http://localhost:5173/auth/sso"


@pytest.fixture
def world(postgresqlIntegrationDb, postgresqlMigratedEnv, monkeypatch):
    db = postgresqlIntegrationDb
    monkeypatch.setattr(sign_in, "_cache", {})
    fake = FakeProvider()
    tag = uuid4().hex[:8]
    fake.claims = {"email": "ana-%s@facility.example.org" % tag, "sub": "sub-%s" % tag}
    key = "facility-%s" % tag
    provider = sign_in.saveProvider(db, {"key": key, "label": "Facility", "issuer": fake.issuer,
                                         "clientId": fake.clientId, "clientSecret": "s3cret"}, http=fake)
    flat = PostgresqlFlatMapper(db)
    made = []
    try:
        yield {"db": db, "flat": flat, "fake": fake, "provider": provider, "key": key, "made": made, "tag": tag}
    finally:
        emails = [fake.claims["email"]] + made
        db.execute("DELETE FROM sign_in_providers WHERE id = %s", (provider["id"],))
        db.execute("DELETE FROM users WHERE email = ANY(%s)", (emails,))


def _signIn(world):
    """The whole round: the button, the provider's answer, the web's exchange; answers the account."""
    url = sign_in.start(world["db"], world["key"], CALLBACK, RETURN, http=world["fake"])
    query = parse_qs(urlsplit(url).query)
    assert query["redirect_uri"] == [CALLBACK] and query["code_challenge_method"] == ["S256"]
    world["fake"].nonce = query["nonce"][0]
    pending = sign_in.takeRequest(world["db"], query["state"][0])
    code = sign_in.finish(world["db"], world["flat"], pending, "provider-code", http=world["fake"])
    return sign_in.exchange(world["db"], world["flat"], code)


def test_ANewPersonGetsAnActiveAccountWithTheDefaultRoles(world):
    user = _signIn(world)
    assert user["email"] == world["fake"].claims["email"]
    assert (user["firstName"], user["lastName"], user["isActive"], user["isVerified"]) == ("Ana", "Lopez", True, True)
    roles = world["db"].fetchAll('SELECT r.name, r."isDefault" FROM user_access_roles ur '
                                 'JOIN access_roles r ON r.id = ur."roleId" WHERE ur."userId" = %s', (user["id"],))
    defaults = world["db"].fetchAll('SELECT name FROM access_roles WHERE "isDefault"')
    assert sorted(row["name"] for row in roles) == sorted(row["name"] for row in defaults) and roles
    # What went to the provider: the PKCE verifier and the client secret, decrypted
    sent = world["fake"].posts[-1]
    assert sent["client_secret"] == "s3cret" and sent["code_verifier"] and sent["redirect_uri"] == CALLBACK
    # The same person again is the same account
    assert _signIn(world)["id"] == user["id"]


def test_AnAccountWithTheSameVerifiedMailIsJoined(world):
    flat = world["flat"]
    userId = flat.insertUser(email=world["fake"].claims["email"], hashedPassword="x", firstName="Ana",
                             lastName="Before", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    assert _signIn(world)["id"] == userId


def test_AnUnverifiedMailNeverTakesAnExistingAccount(world):
    world["flat"].insertUser(email=world["fake"].claims["email"], hashedPassword="x", firstName="Ana",
                             lastName="Before", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    world["fake"].claims["email_verified"] = False
    with pytest.raises(sign_in.SignInError, match="ask an administrator to join them"):
        _signIn(world)


def test_ANewPersonWaitsForActivationWhenTheProviderSaysSo(world):
    sign_in.saveProvider(world["db"], {"newAccounts": "pending"}, world["provider"]["id"], http=world["fake"])
    with pytest.raises(sign_in.SignInError, match="waits for an administrator"):
        _signIn(world)
    user = world["flat"].getUserByEmail(world["fake"].claims["email"])
    assert user and not user["isActive"]


def test_ASignInIsUsedOnceAndItsCodeToo(world):
    url = sign_in.start(world["db"], world["key"], CALLBACK, RETURN, http=world["fake"])
    query = parse_qs(urlsplit(url).query)
    world["fake"].nonce = query["nonce"][0]
    pending = sign_in.takeRequest(world["db"], query["state"][0])
    assert sign_in.takeRequest(world["db"], query["state"][0]) is None
    code = sign_in.finish(world["db"], world["flat"], pending, "provider-code", http=world["fake"])
    sign_in.exchange(world["db"], world["flat"], code)
    with pytest.raises(sign_in.SignInError, match="expired"):
        sign_in.exchange(world["db"], world["flat"], code)


def test_AnOldSignInHasExpired(world):
    url = sign_in.start(world["db"], world["key"], CALLBACK, RETURN, http=world["fake"])
    state = parse_qs(urlsplit(url).query)["state"][0]
    world["db"].execute("UPDATE sign_in_requests SET \"createdAt\" = NOW() - INTERVAL '1 hour' WHERE state = %s",
                        (state,))
    assert sign_in.takeRequest(world["db"], state) is None


def test_AProviderThatRefusesTheCodeIsTold(world):
    world["fake"].tokenStatus = 400
    with pytest.raises(sign_in.SignInError, match="refused the sign-in"):
        _signIn(world)


def test_TheAdministratorSeesNoSecretAndADisabledProviderIsNotOffered(world):
    db, provider = world["db"], world["provider"]
    assert provider["hasSecret"] and "clientSecret" not in provider
    keys = [row["key"] for row in SignInPostgresqlMapper(db).providers(enabledOnly=True)]
    assert world["key"] in keys
    sign_in.saveProvider(db, {"enabled": False}, provider["id"], http=world["fake"])
    assert world["key"] not in [row["key"] for row in SignInPostgresqlMapper(db).providers(enabledOnly=True)]
    with pytest.raises(sign_in.SignInError, match="not available"):
        sign_in.start(db, world["key"], CALLBACK, RETURN, http=world["fake"])
    # A secret left out is kept; an empty one removes it
    assert sign_in.saveProvider(db, {"label": "Facility X"}, provider["id"], http=world["fake"])["hasSecret"]
    assert not sign_in.saveProvider(db, {"clientSecret": ""}, provider["id"], http=world["fake"])["hasSecret"]


def test_AProviderIsCheckedWhenSaved(world):
    with pytest.raises(ValueError, match="https"):
        sign_in.saveProvider(world["db"], {"key": "x-%s" % world["tag"], "label": "X", "clientId": "c",
                                           "issuer": "http://login.example.org"}, http=world["fake"])
    with pytest.raises(sign_in.SignInError, match="could not be reached"):
        sign_in.saveProvider(world["db"], {"key": "y-%s" % world["tag"], "label": "Y", "clientId": "c",
                                           "issuer": "https://elsewhere.example.org"}, http=world["fake"])
    with pytest.raises(ValueError, match="key"):
        sign_in.saveProvider(world["db"], {"key": "Bad Key", "label": "Z", "clientId": "c",
                                           "issuer": world["fake"].issuer}, http=world["fake"])
