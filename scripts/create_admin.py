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
#!/usr/bin/env python3
# createAdminUserScript

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.backend.database import SessionLocal
from app.backend.models.user_model import User
from app.backend.utils.security import hashPassword


def _loadEnv(repoRoot: Path) -> None:
    # Load .env from repository root
    envPath = repoRoot / ".env"
    if not envPath.exists():
        raise RuntimeError(f".env file not found at: {envPath}")
    load_dotenv(dotenv_path=envPath)


def ensureAdminUser(adminName: str, adminEmail: str, adminPassword: str) -> None:
    # Create or update an admin user in a deterministic way
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.email == adminEmail).first()
        hashed = hashPassword(adminPassword)

        if user is None:
            user = User(
                email=adminEmail,
                hashedPassword=hashed,
                isActive=True,
                role="admin",
                firstName=adminName,
                isVerified=True,
                verificationCode=None,
            )
            session.add(user)
        else:
            user.hashedPassword = hashed
            user.isActive = True
            user.role = "admin"
            user.firstName = adminName
            user.isVerified = True
            user.verificationCode = None

        session.commit()
    finally:
        session.close()


def main() -> int:
    repoRoot = Path(__file__).resolve().parents[3]
    _loadEnv(repoRoot)

    adminName = os.getenv("ADMIN_USERNAME", "").strip()
    adminEmail = os.getenv("ADMIN_EMAIL", "").strip()
    adminPassword = os.getenv("ADMIN_PASSWORD", "").strip()

    if not adminName or not adminEmail or not adminPassword:
        raise RuntimeError("Missing ADMIN_USERNAME, ADMIN_EMAIL, or ADMIN_PASSWORD in .env")

    ensureAdminUser(adminName=adminName, adminEmail=adminEmail, adminPassword=adminPassword)
    print(f"Admin user ensured: {adminEmail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
