"""Signing in with a real Keycloak, through the API's routes, end to end (skipped without one).

Set SCIPIONAPI_TEST_KEYCLOAK_ISSUER (e.g. http://localhost:8180/realms/facility), _CLIENT_ID, _CLIENT_SECRET,
_USERNAME and _PASSWORD of a client allowing any redirect address and of a user with a verified mail.
"""
import os
import re
from html import unescape
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.api import dependencies
from app.backend.api.routers import auth_router, settings_router
from app.backend.api.services import sign_in
from app.backend.mapper.postgresql import PostgresqlFlatMapper

ENV = {name: os.environ.get("SCIPIONAPI_TEST_KEYCLOAK_" + name.upper())
       for name in ("issuer", "client_id", "client_secret", "username", "password")}
pytestmark = pytest.mark.skipif(not all(ENV.values()), reason="No test Keycloak set up")

RETURN = "http://localhost:5173/auth/sso"


def _logInAtKeycloak(url: str) -> str:
    """What a browser does at Keycloak: open its page, send the user's name and password; answers where Keycloak
    sends the browser back to."""
    with httpx.Client(follow_redirects=True, timeout=20) as browser:
        page = browser.get(url)
        action = unescape(re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text).group(1))
        # Keycloak marks its cookies secure; a browser sends them to localhost over http, this client does not
        cookies = "; ".join("%s=%s" % (cookie.name, cookie.value) for cookie in browser.cookies.jar)
        answer = browser.post(urljoin(str(page.url), action), follow_redirects=False, headers={"Cookie": cookies},
                              data={"username": ENV["username"], "password": ENV["password"]})
    assert answer.status_code in (302, 303), answer.text[:300]
    return answer.headers["location"]


def test_SigningInWithARealKeycloakGivesASession(postgresqlIntegrationDb, postgresqlMigratedEnv, monkeypatch):
    db = postgresqlIntegrationDb
    monkeypatch.setattr(sign_in, "_cache", {})
    mapper = PostgresqlFlatMapper(db)
    key = "kc-%s" % uuid4().hex[:8]
    provider = sign_in.saveProvider(db, {"key": key, "label": "Test Keycloak", "issuer": ENV["issuer"],
                                         "clientId": ENV["client_id"], "clientSecret": ENV["client_secret"]})
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(settings_router.router)
    app.dependency_overrides[auth_router.getMapper] = lambda: mapper
    app.dependency_overrides[dependencies.getMapper] = lambda: mapper
    email = None
    try:
        with TestClient(app) as client:
            assert {"key": key, "label": "Test Keycloak"} in client.get("/auth/providers").json()
            # The button
            started = client.get("/auth/oidc/%s/start" % key, params={"returnTo": RETURN}, follow_redirects=False)
            assert started.status_code == 302 and started.headers["location"].startswith(ENV["issuer"])
            # Keycloak, as a browser
            back = urlsplit(_logInAtKeycloak(started.headers["location"]))
            assert back.path == "/auth/oidc/%s/callback" % key
            # Keycloak's answer to the API, which sends the browser to the web with a one-time code
            finished = client.get(back.path + "?" + back.query, follow_redirects=False)
            target = finished.headers["location"]
            assert target.startswith(RETURN + "?code="), target
            code = parse_qs(urlsplit(target).query)["code"][0]
            # The web's session
            session = client.post("/auth/oidc/exchange", json={"code": code}).json()
            me = client.get("/auth/me", headers={"Authorization": "Bearer %s" % session["accessToken"]}).json()
            email = me["email"]
            assert me["isActive"] and me["firstName"] and email
            # Once only
            assert client.post("/auth/oidc/exchange", json={"code": code}).status_code == 401
            # A return address outside this installation is refused
            refused = client.get("/auth/oidc/%s/start" % key, params={"returnTo": "https://evil.example.org/x"},
                                 follow_redirects=False)
            assert refused.status_code == 400
    finally:
        db.execute("DELETE FROM sign_in_providers WHERE id = %s", (provider["id"],))
        if email:
            db.execute("DELETE FROM users WHERE email = %s", (email,))
