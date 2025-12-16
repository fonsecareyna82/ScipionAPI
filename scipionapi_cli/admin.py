# scipionapi_cli/admin.py
from typing import Dict

from app.backend.utils.security import hashPassword


def ensureAdminUser(env: Dict[str, str]) -> None:
    # ensureOrmModelsLoaded
    # This guarantees SQLAlchemy can resolve string-based relationships like "Protocol".
    from app.backend.models import project_model, protocol_model  # noqa: F401

    # lazyImportAfterEnvExport
    from app.backend.database import SessionLocal
    from app.backend import models

    adminEmail = env["ADMIN_EMAIL"]
    adminName = env["ADMIN_USERNAME"]
    adminPassword = env["ADMIN_PASSWORD"]

    session = SessionLocal()
    try:
        # findExistingUserByEmail
        user = (
            session.query(models.User)
            .filter(models.User.email == adminEmail)
            .first()
        )

        hashed = hashPassword(adminPassword)

        if user is None:
            # createAdminUser
            user = models.User(
                email=adminEmail,
                hashedPassword=hashed,
                role="admin",
                isActive=True,
                isVerified=True,
                firstName=adminName,
            )
            session.add(user)
            session.commit()
            return

        # updateExistingAdminUser
        user.hashedPassword = hashed
        user.role = "admin"
        user.isActive = True
        user.isVerified = True
        if getattr(user, "firstName", None) in (None, ""):
            user.firstName = adminName

        session.commit()

    except Exception:
        # rollbackOnError
        session.rollback()
        raise
    finally:
        session.close()
