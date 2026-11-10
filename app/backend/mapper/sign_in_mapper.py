"""The queries of signing in with an institution's account: the providers, who each person is at them, and the
sign-ins under way."""
from typing import Any, Dict, List, Optional

PROVIDER_COLUMNS = ('id, key, label, issuer, "clientId", "clientSecret", scopes, "newAccounts", enabled, '
                    '"createdAt", "updatedAt"')
EDITABLE = ("key", "label", "issuer", "clientId", "clientSecret", "scopes", "newAccounts", "enabled")


class SignInPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # The providers ---------------------------------------------------------------------------------------------

    def providers(self, enabledOnly: bool = False) -> List[Dict[str, Any]]:
        rows = self.db.fetchAll("SELECT %s FROM sign_in_providers %s ORDER BY label, id"
                                % (PROVIDER_COLUMNS, "WHERE enabled" if enabledOnly else "")) or []
        return [dict(row) for row in rows]

    def providerByKey(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne("SELECT %s FROM sign_in_providers WHERE key = %%s" % PROVIDER_COLUMNS, (key,))
        return dict(row) if row else None

    def providerById(self, providerId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne("SELECT %s FROM sign_in_providers WHERE id = %%s" % PROVIDER_COLUMNS,
                               (int(providerId),))
        return dict(row) if row else None

    def insertProvider(self, values: Dict[str, Any]) -> int:
        names = [name for name in EDITABLE if name in values]
        row = self.db.executeReturningOne(
            "INSERT INTO sign_in_providers (%s) VALUES (%s) RETURNING id"
            % (", ".join('"%s"' % name for name in names), ", ".join("%s" for _ in names)),
            tuple(values[name] for name in names))
        return int(row["id"])

    def updateProvider(self, providerId: int, values: Dict[str, Any]) -> None:
        names = [name for name in EDITABLE if name in values]
        if not names:
            return
        self.db.execute('UPDATE sign_in_providers SET %s, "updatedAt" = NOW() WHERE id = %%s'
                        % ", ".join('"%s" = %%s' % name for name in names),
                        tuple(values[name] for name in names) + (int(providerId),))

    def deleteProvider(self, providerId: int) -> None:
        self.db.execute("DELETE FROM sign_in_providers WHERE id = %s", (int(providerId),))

    # Who each person is at a provider -----------------------------------------------------------------------

    def userOfIdentity(self, providerId: int, subject: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            'SELECT u.* FROM user_identities i JOIN users u ON u.id = i."userId" '
            'WHERE i."providerId" = %s AND i.subject = %s', (int(providerId), str(subject)))
        return dict(row) if row else None

    def linkIdentity(self, userId: int, providerId: int, subject: str, email: Optional[str]) -> None:
        self.db.execute(
            'INSERT INTO user_identities ("userId", "providerId", subject, email, "lastSignInAt") '
            'VALUES (%s, %s, %s, %s, NOW()) '
            'ON CONFLICT ("providerId", subject) DO UPDATE SET email = EXCLUDED.email, "lastSignInAt" = NOW()',
            (int(userId), int(providerId), str(subject), email))

    def identityOfUser(self, userId: int, providerId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne('SELECT * FROM user_identities WHERE "userId" = %s AND "providerId" = %s',
                               (int(userId), int(providerId)))
        return dict(row) if row else None

    def identitiesCount(self, providerId: int) -> int:
        row = self.db.fetchOne('SELECT COUNT(*) AS n FROM user_identities WHERE "providerId" = %s',
                               (int(providerId),))
        return int(row["n"]) if row else 0

    # Sign-ins under way, and the one-time codes after them --------------------------------------------------

    def saveRequest(self, values: Dict[str, Any]) -> None:
        self.db.execute(
            'INSERT INTO sign_in_requests (state, "providerId", nonce, "codeVerifier", "returnTo", "redirectUri", '
            '"userId", kind) VALUES (%(state)s, %(providerId)s, %(nonce)s, %(codeVerifier)s, %(returnTo)s, '
            '%(redirectUri)s, %(userId)s, %(kind)s)',
            dict({"providerId": None, "nonce": None, "codeVerifier": None, "returnTo": None, "redirectUri": None,
                  "userId": None, "kind": "request"}, **values))

    def takeRequest(self, state: str, kind: str, maxAgeSeconds: int) -> Optional[Dict[str, Any]]:
        """The sign-in (or code) of this state, used once: it is removed; None when unknown or too old."""
        row = self.db.executeReturningOne(
            'DELETE FROM sign_in_requests WHERE state = %s AND kind = %s RETURNING *', (str(state), kind))
        if not row:
            return None
        fresh = self.db.fetchOne("SELECT %s::timestamptz > NOW() - make_interval(secs => %s) AS fresh",
                                 (row["createdAt"], maxAgeSeconds))
        return dict(row) if fresh and fresh["fresh"] else None

    def forgetOldRequests(self, maxAgeSeconds: int) -> None:
        self.db.execute('DELETE FROM sign_in_requests WHERE "createdAt" < NOW() - make_interval(secs => %s)',
                        (maxAgeSeconds,))
