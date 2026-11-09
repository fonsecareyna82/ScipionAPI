"""The queries of resetting a forgotten password: one-time tokens, kept as their hash."""
from typing import Any, Dict, Optional


class PasswordResetPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def recentlyAsked(self, userId: int, minutes: float) -> bool:
        row = self.db.fetchOne('SELECT 1 AS found FROM password_resets WHERE "userId" = %s '
                               'AND "createdAt" > NOW() - %s * INTERVAL \'1 minute\' LIMIT 1',
                               (int(userId), float(minutes)))
        return row is not None

    def create(self, userId: int, tokenHash: str, minutes: float) -> None:
        """A new link: the user's earlier ones stop working."""
        with self.db.transaction():
            self.db.execute('UPDATE password_resets SET "usedAt" = NOW() WHERE "userId" = %s AND "usedAt" IS NULL',
                            (int(userId),), commit=False)
            self.db.execute('INSERT INTO password_resets ("userId", "tokenHash", "expiresAt") '
                            'VALUES (%s, %s, NOW() + %s * INTERVAL \'1 minute\')',
                            (int(userId), tokenHash, float(minutes)), commit=False)

    def valid(self, tokenHash: str) -> Optional[Dict[str, Any]]:
        """The reset of a token not used nor expired, of an active account."""
        row = self.db.fetchOne('SELECT r.id, r."userId" FROM password_resets r JOIN users u ON u.id = r."userId" '
                               'WHERE r."tokenHash" = %s AND r."usedAt" IS NULL AND r."expiresAt" > NOW() '
                               'AND u."isActive"', (tokenHash,))
        return dict(row) if row else None

    def use(self, userId: int) -> None:
        """Every open link of the user stops working (the one used among them)."""
        self.db.execute('UPDATE password_resets SET "usedAt" = NOW() WHERE "userId" = %s AND "usedAt" IS NULL',
                        (int(userId),))
