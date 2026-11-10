"""Signing in with a real Keycloak, through the API's routes, end to end (skipped without one).

Set SCIPIONAPI_TEST_KEYCLOAK_ISSUER (e.g. http://localhost:8180/realms/facility), _CLIENT_ID, _CLIENT_SECRET,
_USERNAME, _PASSWORD and, for the shared browser case, _USERNAME2 and _PASSWORD2: a client allowing any redirect
address (and post-logout "+"), and users with a verified mail.
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
       for name in ("issuer", "client_id", "client_secret", "username", "password", "username2", "password2")}
pytestmark = pytest.mark.skipif(not all(ENV.values()), reason="No test Keycloak set up")

RETURN = "http://localhost:5173/auth/sso"


class Browser:
    """A browser at Keycloak: it keeps Keycloak's session cookies (secure ones too: a browser sends them to
    localhost over http, httpx does not) and stops at the first address outside Keycloak."""

    def __init__(self):
        self.client = httpx.Client(timeout=20)
        self.cookies = {}

    def _keep(self, response):
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if "Max-Age=0" in header or "expires=Thu, 01 Jan 1970" in header:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value

    def go(self, url, data=None):
        """Follow Keycloak's redirects; answers (the page, the address outside Keycloak it sent the browser to)."""
        for _ in range(10):
            headers = {"Cookie": "; ".join("%s=%s" % item for item in self.cookies.items())}
            response = (self.client.post(url, data=data, headers=headers) if data is not None
                        else self.client.get(url, headers=headers))
            self._keep(response)
            data = None
            if response.status_code not in (301, 302, 303, 307):
                return response, None
            url = urljoin(url, response.headers["location"])
            if not url.startswith(ENV["issuer"].split("/realms/")[0]):
                return response, url
        raise AssertionError("Too many redirects")

    def logIn(self, url, username, password):
        page, back = self.go(url)
        if back:
            return back, False
        action = unescape(re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text).group(1))
        _, back = self.go(urljoin(str(page.url), action), data={"username": username, "password": password})
        assert back, "Keycloak did not send the browser back"
        return back, True


def test_SigningInAndOutWithARealKeycloakInASharedBrowser(postgresqlIntegrationDb, postgresqlMigratedEnv,
                                                          monkeypatch):
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
    emails = []
    browser = Browser()
    try:
        with TestClient(app) as api:
            def signIn(username, password):
                started = api.get("/auth/oidc/%s/start" % key, params={"returnTo": RETURN}, follow_redirects=False)
                assert started.status_code == 302 and started.headers["location"].startswith(ENV["issuer"])
                back, askedAtKeycloak = browser.logIn(started.headers["location"], username, password)
                back = urlsplit(back)
                assert back.path == "/auth/oidc/%s/callback" % key
                finished = api.get(back.path + "?" + back.query, follow_redirects=False)
                target = finished.headers["location"]
                assert target.startswith(RETURN + "?code="), target
                code = parse_qs(urlsplit(target).query)["code"][0]
                session = api.post("/auth/oidc/exchange", json={"code": code}).json()
                me = api.get("/auth/me", headers={"Authorization": "Bearer %s" % session["accessToken"]}).json()
                emails.append(me["email"])
                assert api.post("/auth/oidc/exchange", json={"code": code}).status_code == 401
                return me, session, askedAtKeycloak

            assert {"key": key, "label": "Test Keycloak"} in api.get("/auth/providers").json()
            ana, session, asked = signIn(ENV["username"], ENV["password"])
            assert asked and ana["isActive"]
            # Without signing out of Keycloak, its button lets anyone at this browser in as Ana
            again, _, asked = signIn(ENV["username2"], ENV["password2"])
            assert not asked and again["id"] == ana["id"]
            # Signing out of ScipionWeb goes to Keycloak, which ends its session and comes back to the sign-in page
            assert session["signOutUrl"]
            _, back = browser.go(session["signOutUrl"])
            assert back == "http://localhost:5173/signin"
            # The next person is asked who they are, and comes in as themselves
            luis, _, asked = signIn(ENV["username2"], ENV["password2"])
            assert asked and luis["id"] != ana["id"] and luis["firstName"] == "Luis"
            # A return address outside this installation is refused
            refused = api.get("/auth/oidc/%s/start" % key, params={"returnTo": "https://evil.example.org/x"},
                              follow_redirects=False)
            assert refused.status_code == 400
    finally:
        db.execute("DELETE FROM sign_in_providers WHERE id = %s", (provider["id"],))
        if emails:
            db.execute("DELETE FROM users WHERE email = ANY(%s)", (list(set(emails)),))
