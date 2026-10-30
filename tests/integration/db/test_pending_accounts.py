"""The accounts waiting for activation that the bell tells administrators of."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from app.backend.mapper.access_mapper import AccessPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

def test_ANewInactiveAccountIsListedSinceAnEarlierTimeOnly(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    uid = flat.insertUser(email="p-%s@example.com" % uuid4().hex, hashedPassword="x", firstName="P", lastName="", institution=None,
                          role="user", isActive=False, isVerified=True, verificationCode="")
    try:
        rows = AccessPostgresqlMapper(db).listPendingAccountsSince(before, 50)
        assert uid in [r["id"] for r in rows]
        assert AccessPostgresqlMapper(db).listPendingAccountsSince(datetime.now(timezone.utc) + timedelta(seconds=5), 50) == []
    finally:
        db.execute("DELETE FROM users WHERE id = %s", (uid,))
