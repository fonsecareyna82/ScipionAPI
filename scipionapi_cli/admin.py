# scipionapi_cli/admin.py
from typing import Dict, Optional

from app.backend.utils.security import hashPassword


def ensureAdminUser(env: Dict[str, str], adminPassword: Optional[str] = None) -> None:
    # ensureOrmModelsLoaded
    # This guarantees SQLAlchemy can resolve string-based relationships like "Protocol".
    from app.backend.models import project_model, protocol_model  # noqa: F401

    # lazyImportAfterEnvExport
    from app.backend.database import SessionLocal
    from app.backend import models

    adminEmail = (env.get("ADMIN_EMAIL") or "").strip()
    adminName = (env.get("ADMIN_USERNAME") or "").strip()
    plainPassword = (adminPassword or "").strip()

    if not adminEmail:
        raise RuntimeError("ADMIN_EMAIL is required to ensure the admin user.")

    if not adminName:
        raise RuntimeError("ADMIN_USERNAME is required to ensure the admin user.")

    if not plainPassword:
        raise RuntimeError(
            "Admin password is required but was not provided. "
            "Pass it from installCommand instead of storing it in .env."
        )

    session = SessionLocal()
    try:
        # findExistingUserByEmail
        user = (
            session.query(models.User)
            .filter(models.User.email == adminEmail)
            .first()
        )

        hashed = hashPassword(plainPassword)

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