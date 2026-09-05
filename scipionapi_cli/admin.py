# scipionapi_cli/admin.py
# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
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