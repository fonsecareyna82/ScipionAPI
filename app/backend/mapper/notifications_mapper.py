"""The queries of the users' notifications: the outbox, each user's choices and the mail's settings."""
import json
from typing import Any, Dict, Iterable, List, Optional

SAVE_SETTING_SQL = """
    INSERT INTO notification_settings (key, value, "updatedBy") VALUES (%s, %s::JSONB, %s)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "updatedBy" = EXCLUDED."updatedBy", "updatedAt" = NOW()
"""

INSERT_SQL = """
    INSERT INTO notifications ("userId", email, kind, title, body, link, "inWeb", "emailState")
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
"""

# What is mailed now: the pending notices whose time came, with the address they go to (a user's, while active)
DUE_SQL = """
    SELECT n.id, n."userId", n.kind, n.title, n.body, n.link, n."emailAttempts",
           COALESCE(n.email, u.email) AS address, u."isActive" AS active
      FROM notifications n
      LEFT JOIN users u ON u.id = n."userId"
     WHERE n."emailState" = 'pending' AND n."emailNextAt" <= NOW()
     ORDER BY n.id
     LIMIT %s
"""

DIGEST_SQL = """
    SELECT n.id, n."userId", n.kind, n.title, n.body, n.link, n."createdAt", u.email AS address,
           u."isActive" AS active
      FROM notifications n
      JOIN users u ON u.id = n."userId"
     WHERE n."emailState" = 'digest'
     ORDER BY n."userId", n.id
"""

LIST_MINE_SQL = """
    SELECT id, kind, title, body, link, "createdAt", "readAt"
      FROM notifications
     WHERE "userId" = %s AND "inWeb"
     ORDER BY "createdAt" DESC, id DESC
     LIMIT %s
"""

OUTBOX_SQL = """
    SELECT n.id, n.kind, n.title, n."createdAt", n."emailState", n."emailAttempts", n."emailedAt", n."emailError",
           COALESCE(n.email, u.email) AS address
      FROM notifications n
      LEFT JOIN users u ON u.id = n."userId"
     WHERE n."emailState" <> 'skipped' OR n."emailError" IS NOT NULL
     ORDER BY n.id DESC
     LIMIT %s
"""


class NotificationsPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # Settings ------------------------------------------------------------------------------------------
    def getSettings(self) -> Dict[str, Any]:
        return {row["key"]: row["value"] for row in
                self.db.fetchAll("SELECT key, value FROM notification_settings") or []}

    def saveSettings(self, values: Dict[str, Any], userId: Optional[int]) -> None:
        with self.db.transaction():
            for key, value in values.items():
                self.db.execute(SAVE_SETTING_SQL, (key, json.dumps(value), userId), commit=False)

    # Preferences ---------------------------------------------------------------------------------------
    def preferencesOf(self, userIds: Iterable[int]) -> Dict[int, Dict[str, str]]:
        """{userId: {kind: channel}} for the users given."""
        ids = sorted({int(userId) for userId in userIds})
        answer: Dict[int, Dict[str, str]] = {userId: {} for userId in ids}
        if not ids:
            return answer
        for row in self.db.fetchAll('SELECT "userId", kind, channel FROM notification_preferences '
                                    'WHERE "userId" = ANY(%s)', (ids,)) or []:
            answer[int(row["userId"])][row["kind"]] = row["channel"]
        return answer

    def savePreferences(self, userId: int, channels: Dict[str, Optional[str]]) -> None:
        """A user's channel per kind; None goes back to the default."""
        with self.db.transaction():
            for kind, channel in channels.items():
                if channel is None:
                    self.db.execute('DELETE FROM notification_preferences WHERE "userId" = %s AND kind = %s',
                                    (int(userId), kind), commit=False)
                else:
                    self.db.execute('INSERT INTO notification_preferences ("userId", kind, channel) '
                                    'VALUES (%s, %s, %s) ON CONFLICT ("userId", kind) DO UPDATE '
                                    'SET channel = EXCLUDED.channel', (int(userId), kind, channel), commit=False)

    def groupMemberIds(self, groupIds: List[int]) -> List[int]:
        ids = sorted({int(groupId) for groupId in groupIds or []})
        if not ids:
            return []
        rows = self.db.fetchAll('SELECT DISTINCT "userId" FROM user_group_members WHERE "groupId" = ANY(%s)', (ids,))
        return [int(row["userId"]) for row in rows or []]

    def runOf(self, runId: int) -> Optional[Dict[str, Any]]:
        """A protocol run with its project's owner (to tell of its end)."""
        row = self.db.fetchOne('SELECT r.id, r."projectId", r."projectPath", r."protocolId", r."protocolClassName", '
                               'r."protocolLabel", r."userId", r."startedAt", r."endedAt", r.status, p."ownerId" '
                               'FROM protocol_runs r LEFT JOIN projects p ON p.id = r."projectId" WHERE r.id = %s',
                               (int(runId),))
        return dict(row) if row else None

    def activeUserIds(self, userIds: Iterable[int]) -> List[int]:
        ids = sorted({int(userId) for userId in userIds if userId is not None})
        if not ids:
            return []
        rows = self.db.fetchAll('SELECT id FROM users WHERE id = ANY(%s) AND "isActive"', (ids,))
        return [int(row["id"]) for row in rows or []]

    # The outbox ----------------------------------------------------------------------------------------
    def insert(self, userId: Optional[int], email: Optional[str], kind: str, title: str, body: str, link: str,
               inWeb: bool, emailState: str) -> int:
        row = self.db.executeReturningOne(INSERT_SQL, (userId, email, kind, title, body, link, inWeb, emailState))
        return int(row["id"])

    def listMine(self, userId: int, limit: int = 50) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(LIST_MINE_SQL, (int(userId), int(limit))) or []]

    def countUnread(self, userId: int) -> int:
        row = self.db.fetchOne('SELECT COUNT(*) AS n FROM notifications WHERE "userId" = %s AND "inWeb" '
                               'AND "readAt" IS NULL', (int(userId),))
        return int(row["n"]) if row else 0

    def listUnreadSince(self, userId: int, since, limit: int = 50) -> List[Dict[str, Any]]:
        """The user's unread notices made after since (all the unread ones without since), the newest first."""
        condition = ' AND "createdAt" > %s' if since is not None else ""
        params = (int(userId),) + ((since,) if since is not None else ()) + (int(limit),)
        rows = self.db.fetchAll('SELECT id, kind, title, body, link, "createdAt" FROM notifications '
                                'WHERE "userId" = %s AND "inWeb" AND "readAt" IS NULL' + condition +
                                ' ORDER BY "createdAt" DESC, id DESC LIMIT %s', params)
        return [dict(row) for row in rows or []]

    def markRead(self, userId: int, ids: Optional[List[int]] = None) -> int:
        """Mark the user's notices read (the given ones, else all); answers how many."""
        if ids is not None and not ids:
            return 0
        condition = " AND id = ANY(%s)" if ids is not None else ""
        params = (int(userId),) + (([int(value) for value in ids],) if ids is not None else ())
        cursor = self.db.execute('UPDATE notifications SET "readAt" = NOW() WHERE "userId" = %s '
                                 'AND "readAt" IS NULL' + condition, params)
        return int(getattr(cursor, "rowcount", 0) or 0)

    def due(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(DUE_SQL, (int(limit),)) or []]

    def digest(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(DIGEST_SQL) or []]

    def markSent(self, ids: List[int]) -> None:
        if ids:
            self.db.execute('UPDATE notifications SET "emailState" = \'sent\', "emailedAt" = NOW(), "emailError" = NULL '
                            'WHERE id = ANY(%s)', ([int(value) for value in ids],))

    def forgetBody(self, notificationId: int) -> None:
        self.db.execute("UPDATE notifications SET body = '' WHERE id = %s", (int(notificationId),))

    def markSkipped(self, ids: List[int], reason: str) -> None:
        if ids:
            self.db.execute('UPDATE notifications SET "emailState" = \'skipped\', "emailError" = %s '
                            'WHERE id = ANY(%s)', (reason, [int(value) for value in ids]))

    def markRetry(self, notificationId: int, error: str, delayMinutes: float, giveUp: bool) -> None:
        """A mail that did not go: tried again after delayMinutes, or failed for good."""
        self.db.execute('UPDATE notifications SET "emailAttempts" = "emailAttempts" + 1, "emailError" = %s, '
                        '"emailState" = CASE WHEN %s THEN \'failed\' ELSE "emailState" END, '
                        '"emailNextAt" = NOW() + %s * INTERVAL \'1 minute\' WHERE id = %s',
                        (error[:1000], bool(giveUp), float(delayMinutes), int(notificationId)))

    def skipWaiting(self, reason: str) -> int:
        cursor = self.db.execute('UPDATE notifications SET "emailState" = \'skipped\', "emailError" = %s '
                                 'WHERE "emailState" IN (\'pending\', \'digest\')', (reason,))
        return int(getattr(cursor, "rowcount", 0) or 0)

    def skipStale(self, days: float) -> int:
        """Pending mails older than days (no mail server all that time) are not sent any more."""
        cursor = self.db.execute('UPDATE notifications SET "emailState" = \'skipped\', '
                                 '"emailError" = \'No mail server while it waited\' '
                                 'WHERE "emailState" IN (\'pending\', \'digest\') '
                                 'AND "createdAt" < NOW() - %s * INTERVAL \'1 day\'', (float(days),))
        return int(getattr(cursor, "rowcount", 0) or 0)

    def outbox(self, limit: int = 200) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(OUTBOX_SQL, (int(limit),)) or []]

    def tryLock(self) -> bool:
        row = self.db.fetchOne("SELECT pg_try_advisory_lock(hashtext('notification_send')) AS locked") or {}
        return bool(row.get("locked"))

    def unlock(self) -> None:
        self.db.fetchOne("SELECT pg_advisory_unlock(hashtext('notification_send')) AS unlocked")
