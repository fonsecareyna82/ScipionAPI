"""Signing in with an institution's account, through OpenID Connect (Keycloak and the like).

1. The sign-in page lists the providers an administrator set up (none by default).
2. Its button goes to start(): ScipionWeb keeps what will prove the answer is this sign-in's (state, nonce and a
   PKCE code verifier) and sends the browser to the provider. The person signs in there: ScipionWeb never sees
   their password.
3. The provider sends the browser back to finish() with a code. ScipionWeb trades it for the person's tokens
   (with its client secret), checks the ID token's signature (the provider's published keys), issuer, audience,
   expiry and nonce, and finds the account: the one this identity already signed in with; else an account with
   that mail, only when the provider says the mail is verified; else a new account (active at once, or waiting for
   an administrator, as the provider is set up), with the default roles.
4. The browser goes back to the web with a one-time code (a minute), which the web exchanges for its session
   (exchange()); no token travels in an address.
"""
import base64
import hashlib
import logging
import re
import secrets
import threading
import time
import uuid
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlencode, urlsplit

from app.backend.mapper.sign_in_mapper import SignInPostgresqlMapper

logger = logging.getLogger(__name__)

REQUEST_SECONDS = 600
CODE_SECONDS = 120
HTTP_TIMEOUT = 8.0
CACHE_SECONDS = 3600
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
# The origins the web is served from in development; the API's own origin and the public address always count
DEVELOPMENT_ORIGINS = ("http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173")
_KEY_SALT = "scipionweb-sign-in-providers:"

_cacheLock = threading.Lock()
_cache: Dict[str, Tuple[float, Any]] = {}


class SignInError(Exception):
    """What the person is told when signing in with a provider does not work."""


# The client secret is kept encrypted --------------------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet

    from app.backend.utils.jwt import SECRET_KEY

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((_KEY_SALT + SECRET_KEY).encode()).digest()))


def encryptSecret(secret: Optional[str]) -> Optional[str]:
    return _fernet().encrypt(secret.encode()).decode() if secret else None


def decryptSecret(stored: Optional[str]) -> Optional[str]:
    if not stored:
        return None
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except Exception:
        logger.warning("The client secret of a sign-in provider cannot be read (the server key changed?)")
        return None


# The provider's published configuration and keys ---------------------------------------------------------------

def _getJson(url: str, http=None) -> Dict[str, Any]:
    import httpx

    client = http or httpx
    response = client.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _cached(key: str, load, fresh: bool = False):
    now = time.monotonic()
    with _cacheLock:
        hit = _cache.get(key)
        if hit and not fresh and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = load()
    with _cacheLock:
        _cache[key] = (now, value)
    return value


def discovery(issuer: str, http=None, fresh: bool = False) -> Dict[str, Any]:
    """The provider's configuration (its endpoints and keys' address), from <issuer>/.well-known/..."""
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        config = _cached("discovery:" + url, lambda: _getJson(url, http), fresh)
    except Exception as error:
        raise SignInError("The institution's sign-in service could not be reached (%s)." % type(error).__name__)
    for name in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not config.get(name):
            raise SignInError("The institution's sign-in service does not publish its %s." % name)
    return config


def _keys(config: Dict[str, Any], http=None, fresh: bool = False) -> Dict[str, Any]:
    return _cached("jwks:" + config["jwks_uri"], lambda: _getJson(config["jwks_uri"], http), fresh)


def _codeChallenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


# Where the browser may be sent back to ------------------------------------------------------------------------

def _origin(url: str) -> Optional[str]:
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return "%s://%s" % (parts.scheme, parts.netloc.lower())


def returnAllowed(returnTo: str, ownOrigins: Iterable[str]) -> bool:
    """Only to the web of this installation (no open redirect): its public address, the API's own origin or a
    development server."""
    origin = _origin(returnTo)
    allowed = {_origin(value) for value in list(ownOrigins) + list(DEVELOPMENT_ORIGINS) if value}
    return origin is not None and origin in allowed


def withQuery(url: str, values: Dict[str, str]) -> str:
    return url + ("&" if "?" in url else "?") + urlencode(values)


# The flow ---------------------------------------------------------------------------------------------------

def start(db, key: str, redirectUri: str, returnTo: str, http=None) -> str:
    """The provider's address to send the browser to, with this sign-in's proofs kept."""
    mapper = SignInPostgresqlMapper(db)
    provider = mapper.providerByKey(key)
    if not provider or not provider.get("enabled"):
        raise SignInError("This way of signing in is not available.")
    config = discovery(provider["issuer"], http)
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    mapper.forgetOldRequests(REQUEST_SECONDS)
    mapper.saveRequest({"state": state, "providerId": provider["id"], "nonce": nonce, "codeVerifier": verifier,
                        "returnTo": returnTo, "redirectUri": redirectUri})
    return withQuery(config["authorization_endpoint"], {
        "response_type": "code", "client_id": provider["clientId"], "redirect_uri": redirectUri,
        "scope": provider.get("scopes") or "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": _codeChallenge(verifier), "code_challenge_method": "S256"})


def takeRequest(db, state: str) -> Optional[Dict[str, Any]]:
    return SignInPostgresqlMapper(db).takeRequest(state or "", "request", REQUEST_SECONDS)


def _tokens(provider: Dict[str, Any], config: Dict[str, Any], code: str, request: Dict[str, Any], http=None):
    import httpx

    client = http or httpx
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": request["redirectUri"],
            "client_id": provider["clientId"], "code_verifier": request["codeVerifier"]}
    secret = decryptSecret(provider.get("clientSecret"))
    if secret:
        data["client_secret"] = secret
    try:
        response = client.post(config["token_endpoint"], data=data, timeout=HTTP_TIMEOUT,
                               headers={"Accept": "application/json"})
    except Exception as error:
        raise SignInError("The institution's sign-in service could not be reached (%s)." % type(error).__name__)
    if response.status_code != 200:
        logger.warning("The provider %s refused the sign-in code: %s %s", provider["key"], response.status_code,
                       response.text[:300])
        raise SignInError("The institution's sign-in service refused the sign-in; try again.")
    tokens = response.json()
    if not tokens.get("id_token"):
        raise SignInError("The institution's sign-in service did not say who signed in.")
    return tokens


def checkIdToken(idToken: str, provider: Dict[str, Any], config: Dict[str, Any], nonce: str,
                 accessToken: Optional[str] = None, http=None) -> Dict[str, Any]:
    """The ID token's claims, once its signature, issuer, audience, expiry and nonce are right."""
    from jose import jwt
    from jose.exceptions import JOSEError

    try:
        header = jwt.get_unverified_header(idToken)
    except JOSEError:
        raise SignInError("The institution's answer could not be read.")
    algorithm = header.get("alg")
    if algorithm not in ALLOWED_ALGORITHMS:
        raise SignInError("The institution's answer is not signed in a way ScipionWeb accepts.")
    keys = _keys(config, http)
    if header.get("kid") and not any(key.get("kid") == header["kid"] for key in keys.get("keys", [])):
        # The provider may have changed its keys since they were read
        keys = _keys(config, http, fresh=True)
    try:
        claims = jwt.decode(idToken, keys, algorithms=[algorithm], audience=provider["clientId"],
                            issuer=config["issuer"], access_token=accessToken)
    except JOSEError as error:
        logger.warning("An ID token of %s was refused: %s", provider["key"], error)
        raise SignInError("The institution's answer could not be verified.")
    if not nonce or claims.get("nonce") != nonce:
        raise SignInError("The institution's answer does not belong to this sign-in.")
    if not claims.get("sub"):
        raise SignInError("The institution's answer does not say who signed in.")
    return claims


def _userinfo(config: Dict[str, Any], accessToken: str, http=None) -> Dict[str, Any]:
    import httpx

    if not config.get("userinfo_endpoint") or not accessToken:
        return {}
    try:
        response = (http or httpx).get(config["userinfo_endpoint"], timeout=HTTP_TIMEOUT,
                                       headers={"Authorization": "Bearer %s" % accessToken})
        return response.json() if response.status_code == 200 else {}
    except Exception:
        return {}


def _names(claims: Dict[str, Any]) -> Tuple[str, str]:
    first, last = (claims.get("given_name") or "").strip(), (claims.get("family_name") or "").strip()
    if not first and not last:
        full = (claims.get("name") or claims.get("preferred_username") or "").strip()
        first, _, last = full.partition(" ")
    return first or "-", last or "-"


def accountOf(db, flat, provider: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    """The account of who signed in: theirs from before, one with their verified mail, or a new one."""
    from app.backend.api.audit import recordAudit
    from app.backend.api.services.access_service import AccessService
    from app.backend.utils.security import hashPassword

    mapper = SignInPostgresqlMapper(db)
    subject = str(claims["sub"])
    email = (claims.get("email") or "").strip()
    user = mapper.userOfIdentity(provider["id"], subject)
    if user:
        mapper.linkIdentity(user["id"], provider["id"], subject, email or None)
        return user
    if not email:
        raise SignInError("The institution did not give a mail address, which ScipionWeb needs for the account.")
    existing = flat.getUserByEmail(email)
    if existing:
        if claims.get("email_verified") is not True:
            raise SignInError("There is already an account with this mail, and the institution does not say the "
                              "mail is verified: ask an administrator to join them.")
        if mapper.identityOfUser(existing["id"], provider["id"]):
            raise SignInError("This account is already joined to another person of the institution: ask an "
                              "administrator.")
        mapper.linkIdentity(existing["id"], provider["id"], subject, email)
        recordAudit(flat, existing, "auth.identityLinked", "user", existing["id"], email,
                    details={"provider": provider["key"]})
        return existing
    first, last = _names(claims)
    active = provider.get("newAccounts", "active") == "active"
    userId = flat.insertUser(email=email, hashedPassword=hashPassword(secrets.token_urlsafe(32)), firstName=first,
                             lastName=last, institution=provider.get("label"), role="user", isActive=active,
                             isVerified=True, verificationCode=str(uuid.uuid4()))
    AccessService(db).giveDefaultRoles(userId)
    mapper.linkIdentity(userId, provider["id"], subject, email)
    recordAudit(flat, {"id": userId, "email": email}, "auth.signUp", "user", userId, email,
                details={"provider": provider["key"], "active": active})
    return flat.getUserById(userId)


def finish(db, flat, request: Dict[str, Any], code: str, http=None) -> str:
    """The provider's answer to a sign-in under way: the one-time code the web exchanges for its session."""
    from app.backend.api.audit import recordAudit

    provider = SignInPostgresqlMapper(db).providerById(request["providerId"]) if request.get("providerId") else None
    if not provider or not provider.get("enabled"):
        raise SignInError("This way of signing in is not available.")
    config = discovery(provider["issuer"], http)
    tokens = _tokens(provider, config, code, request, http)
    claims = checkIdToken(tokens["id_token"], provider, config, request.get("nonce"), tokens.get("access_token"), http)
    if not claims.get("email"):
        claims = dict(_userinfo(config, tokens.get("access_token"), http), **claims)
    user = accountOf(db, flat, provider, claims)
    if not bool(user.get("isActive", True)):
        recordAudit(flat, user, "auth.signInFailed", details={"reason": "account not active",
                                                              "provider": provider["key"]})
        raise SignInError("Your account waits for an administrator to activate it.")
    oneTime = secrets.token_urlsafe(32)
    SignInPostgresqlMapper(db).saveRequest({"state": oneTime, "kind": "code", "userId": user["id"]})
    return oneTime


def exchange(db, flat, code: str) -> Dict[str, Any]:
    """The account a one-time code (from finish) was given for; it can be used once, within CODE_SECONDS."""
    taken = SignInPostgresqlMapper(db).takeRequest(code or "", "code", CODE_SECONDS)
    user = flat.getUserById(taken["userId"]) if taken and taken.get("userId") else None
    if not user:
        raise SignInError("This sign-in expired; sign in again.")
    if not bool(user.get("isActive", True)):
        raise SignInError("Your account waits for an administrator to activate it.")
    return user


# What the administrator sees ----------------------------------------------------------------------------------

def providerOut(provider: Dict[str, Any], db=None) -> Dict[str, Any]:
    out = {key: provider.get(key) for key in ("id", "key", "label", "issuer", "clientId", "scopes", "newAccounts",
                                              "enabled")}
    out["hasSecret"] = bool(provider.get("clientSecret"))
    if db is not None:
        out["accounts"] = SignInPostgresqlMapper(db).identitiesCount(provider["id"])
    return out


KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _cleanIssuer(issuer: str) -> str:
    issuer = (issuer or "").strip().rstrip("/")
    parts = urlsplit(issuer)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("The issuer must be an https address (http only for a test server on this machine).")
    return issuer


def saveProvider(db, payload: Dict[str, Any], providerId: Optional[int] = None, http=None) -> Dict[str, Any]:
    """Add (providerId None) or change a provider. A client secret left out keeps the one there is; an empty one
    removes it. The issuer is checked: its configuration must be published."""
    mapper = SignInPostgresqlMapper(db)
    current = mapper.providerById(providerId) if providerId is not None else None
    if providerId is not None and not current:
        raise LookupError("No such sign-in provider")
    values: Dict[str, Any] = {}
    if "key" in payload or current is None:
        key = str(payload.get("key") or "").strip().lower()
        if not KEY_PATTERN.match(key):
            raise ValueError("The key must be short, in lower case letters, digits and dashes (e.g. esrf).")
        other = mapper.providerByKey(key)
        if other and (current is None or other["id"] != current["id"]):
            raise ValueError("Another provider has this key.")
        values["key"] = key
    for name, required in (("label", True), ("clientId", True)):
        if name in payload or current is None:
            value = str(payload.get(name) or "").strip()
            if required and not value:
                raise ValueError({"label": "The button needs a name.", "clientId": "The client id is needed."}[name])
            values[name] = value
    if "issuer" in payload or current is None:
        values["issuer"] = _cleanIssuer(str(payload.get("issuer") or ""))
        discovery(values["issuer"], http, fresh=True)
    if "scopes" in payload:
        scopes = " ".join(str(payload.get("scopes") or "").split())
        values["scopes"] = scopes if "openid" in scopes.split() else ("openid " + scopes).strip()
    if "newAccounts" in payload:
        if payload["newAccounts"] not in ("active", "pending"):
            raise ValueError("New accounts are either active or pending.")
        values["newAccounts"] = payload["newAccounts"]
    if "enabled" in payload:
        values["enabled"] = bool(payload["enabled"])
    if payload.get("clientSecret") is not None:
        values["clientSecret"] = encryptSecret(str(payload["clientSecret"])) if payload["clientSecret"] else None
    if current is None:
        providerId = mapper.insertProvider(values)
    else:
        mapper.updateProvider(current["id"], values)
    return providerOut(mapper.providerById(providerId), db)


def testProvider(db, providerId: int, http=None) -> Dict[str, Any]:
    """Whether the provider's configuration can be read now (what an administrator checks after saving)."""
    provider = SignInPostgresqlMapper(db).providerById(providerId)
    if not provider:
        raise LookupError("No such sign-in provider")
    try:
        config = discovery(provider["issuer"], http, fresh=True)
        keys = _keys(config, http, fresh=True)
    except SignInError as error:
        return {"ok": False, "error": str(error)}
    except Exception as error:
        return {"ok": False, "error": "Its keys could not be read (%s)." % type(error).__name__}
    return {"ok": True, "issuer": config["issuer"], "keys": len(keys.get("keys", []))}
