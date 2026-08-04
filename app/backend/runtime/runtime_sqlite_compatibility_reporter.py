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
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class RuntimeSqliteCompatibilityReporter:
    """Emit structured events for remaining PostgreSQL runtime SQLite paths."""

    EVENT_MARKER = "POSTGRESQL_SQLITE_COMPATIBILITY"

    def report(self, pathKind: str, projectId=None, protocolId=None, protocolClass=None, outputName=None, setClass=None, creatorKind=None, reason=None, legacyPath=None) -> Dict[str, Any]:
        event = {
            "pathKind": str(pathKind),
            "projectId": projectId,
            "protocolId": protocolId,
            "protocolClass": protocolClass,
            "outputName": outputName,
            "setClass": setClass,
            "creatorKind": creatorKind,
            "reason": reason,
            "legacyPath": str(legacyPath) if legacyPath else None,
        }

        logger.info("%s %s", self.EVENT_MARKER, json.dumps(event, sort_keys=True, default=str))
        return event