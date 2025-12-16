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
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# * Public License for more details.
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

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _requireEnv(key: str) -> str:
    # requireEnvVar
    value = (os.getenv(key) or "").strip()
    if not value:
        scipionHome = os.getenv("SCIPION_HOME")
        hint = f" (SCIPION_HOME={scipionHome})" if scipionHome else ""
        raise RuntimeError(
            f"Missing required environment variable: {key}.{hint} "
            "Run `scipionapi install` and start via `scipionapi start` so the .env is exported."
        )
    return value


# readRequiredEnvAtImportTime
# The runtime/cli exports SCIPION_HOME/.env into the process environment before importing this module.
DATABASE_URL = _requireEnv("DATABASE_URL")

# createSqlAlchemyEngine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

# createSessionFactory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
    future=True,
)

# baseClassForModels
Base = declarative_base()


def getMapper():
    # getPostgresqlMapper
    from app.backend.mapper.postgresql import PostgresqlFlatMapper, PostgresqlDb

    dbName = _requireEnv("DATABASE_NAME")
    dbUser = _requireEnv("DATABASE_USER")
    dbPass = _requireEnv("DATABASE_PASS")

    db = PostgresqlDb(dbName=dbName, user=dbUser, password=dbPass)
    return PostgresqlFlatMapper(db)
