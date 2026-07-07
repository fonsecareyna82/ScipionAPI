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
import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class ProtocolIdentityResolver:
    """
    Resolve protocol identity between PostgreSQL and Scipion runtime ids.

    PostgreSQL uses:
      - protocols.id: internal database id
      - protocols."protocolId": Scipion runtime object id

    Scipion uses:
      - protocol.getObjId(): runtime object id
    """

    def __init__(self, mapper=None, projectId: Optional[int] = None, db=None):
        self.mapper = mapper
        self.projectId = self.toOptionalInt(projectId)
        self.db = db if db is not None else getattr(mapper, "db", None)

    def resolveScipionProtocolId(self, protocolId: Any) -> Optional[int]:
        """
        Accept PostgreSQL protocols.id or Scipion protocols.protocolId.
        Return the Scipion runtime protocol id.
        """
        protocolRow = self.getProtocolRow(protocolId)

        if protocolRow is not None:
            scipionProtocolId = self.toOptionalInt(protocolRow.get("protocolId"))
            if scipionProtocolId is not None:
                return scipionProtocolId

        return self.toOptionalInt(protocolId)

    def resolvePostgresqlProtocolDbId(self, protocolId: Any) -> Optional[int]:
        """
        Accept PostgreSQL protocols.id or Scipion protocols.protocolId.
        Return PostgreSQL protocols.id.
        """
        protocolRow = self.getProtocolRow(protocolId)

        if protocolRow is None:
            return None

        return self.toOptionalInt(protocolRow.get("id"))

    def resolveReaderProtocolId(self, protocolId: Any) -> Optional[int]:
        """
        Return the id expected by PostgreSQL readers.

        Readers usually work with protocols.id. If the protocol is not found in
        PostgreSQL, keep the numeric value as fallback for legacy callers.
        """
        postgresqlProtocolDbId = self.resolvePostgresqlProtocolDbId(protocolId)

        if postgresqlProtocolDbId is not None:
            return postgresqlProtocolDbId

        return self.toOptionalInt(protocolId)

    def getProtocolRow(self, protocolId: Any) -> Optional[Dict[str, Any]]:
        if self.db is None or self.projectId is None:
            return None

        protocolIdInt = self.toOptionalInt(protocolId)
        protocolIdText = str(protocolId).strip() if protocolId not in (None, "") else ""

        if protocolIdInt is None and not protocolIdText:
            return None

        try:
            return self.db.fetchOne(
                """
                SELECT id, "protocolId"
                  FROM protocols
                 WHERE "projectId" = %s
                   AND (id = %s OR "protocolId" = %s)
                 LIMIT 1
                """,
                (
                    int(self.projectId),
                    protocolIdInt,
                    protocolIdText,
                ),
            )
        except Exception:
            logger.debug(
                "Could not resolve protocol identity. projectId=%s protocolId=%s",
                self.projectId,
                protocolId,
                exc_info=True,
            )
            return None

    @staticmethod
    def toOptionalInt(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None

        try:
            return int(value)
        except Exception:
            pass

        try:
            return int(float(str(value).strip()))
        except Exception:
            return None