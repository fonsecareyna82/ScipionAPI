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
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RuntimeProtocolStepPersistenceService:
    """Build PostgreSQL runtime step snapshots from Scipion protocol steps."""

    def safeProtocolStepValue(self, value: Any, default=None):
        try:
            if value is None:
                return default

            if hasattr(value, "hasValue") and not value.hasValue():
                return default

            if hasattr(value, "get"):
                try:
                    return value.get(default)
                except TypeError:
                    return value.get()

            return value
        except Exception:
            return default

    def safeProtocolStepCall(self, step: Any, methodName: str, default=None):
        try:
            method = getattr(step, methodName, None)
            if not callable(method):
                return default

            value = method()
            return value if value is not None else default
        except Exception:
            return default

    def safeProtocolStepJsonValue(self, value: Any):
        if value in (None, ""):
            return None

        if isinstance(value, (dict, list, tuple)):
            return value

        try:
            return json.loads(str(value))
        except Exception:
            return str(value)

    def loadProtocolStepsForPostgresql(
            self,
            protocol: Any,
    ) -> List[Any]:
        """
        Return only the currently defined in-memory steps.

        PostgreSQL synchronization must never read steps.sqlite.
        """
        steps = getattr(
            protocol,
            "_steps",
            None,
        )

        if not steps:
            return []

        if isinstance(
                steps,
                dict,
        ):
            return list(
                steps.values()
            )

        return list(
            steps
        )

    def buildProtocolStepForPostgresql(
            self,
            step: Any,
            *,
            event: str = "snapshot",
    ) -> Dict[str, Any]:
        stepIndex = self.safeProtocolStepCall(
            step,
            "getIndex",
            None,
        )

        if stepIndex is None:
            raise ValueError(
                "Protocol step has no index."
            )

        rawArgs = self.safeProtocolStepValue(
            getattr(
                step,
                "argsStr",
                None,
            ),
            None,
        )

        rawResultFiles = (
            self.safeProtocolStepValue(
                getattr(
                    step,
                    "_resultFiles",
                    None,
                ),
                None,
            )
        )

        rawPrerequisites = (
                self.safeProtocolStepCall(
                    step,
                    "getPrerequisites",
                    [],
                )
                or []
        )

        elapsedSeconds = None

        elapsed = self.safeProtocolStepCall(
            step,
            "getElapsedTime",
            None,
        )

        try:
            if elapsed is not None:
                elapsedSeconds = (
                    elapsed.total_seconds()
                )
        except Exception:
            elapsedSeconds = None

        stepName = self.safeProtocolStepValue(
            getattr(
                step,
                "funcName",
                None,
            ),
            None,
        )

        if not stepName:
            stepName = (
                self.safeProtocolStepCall(
                    step,
                    "getClassName",
                    "",
                )
            )

        needsGpu = self.safeProtocolStepCall(
            step,
            "needsGPU",
            True,
        )

        return {
            "index": int(stepIndex),
            "stepClassName": (
                step.__class__.__name__
            ),
            "name": str(
                stepName
                or ""
            ),
            "status": (
                self.safeProtocolStepCall(
                    step,
                    "getStatus",
                    "",
                )
            ),
            "prerequisites": [
                int(prerequisite)
                for prerequisite
                in rawPrerequisites
            ],
            "args": (
                self.safeProtocolStepJsonValue(
                    rawArgs
                )
            ),
            "argsText": (
                str(rawArgs)
                if rawArgs is not None
                else None
            ),
            "resultFiles": (
                self.safeProtocolStepJsonValue(
                    rawResultFiles
                )
            ),
            "initTime": (
                self.safeProtocolStepValue(
                    getattr(
                        step,
                        "initTime",
                        None,
                    ),
                    None,
                )
            ),
            "endTime": (
                self.safeProtocolStepValue(
                    getattr(
                        step,
                        "endTime",
                        None,
                    ),
                    None,
                )
            ),
            "elapsedSeconds": (
                elapsedSeconds
            ),
            "error": (
                self.safeProtocolStepCall(
                    step,
                    "getErrorMessage",
                    None,
                )
            ),
            "interactive": bool(
                self.safeProtocolStepCall(
                    step,
                    "isInteractive",
                    False,
                )
            ),
            "needsGpu": bool(
                needsGpu
            ),
            "event": event,
            "schemaVersion": 2,
        }

    def buildProtocolStepsForPostgresql(
            self,
            protocol: Any,
    ) -> List[Dict[str, Any]]:
        steps = (
            self
            .loadProtocolStepsForPostgresql(
                protocol
            )
        )

        return [
            self.buildProtocolStepForPostgresql(
                step,
                event="snapshot",
            )
            for step in steps
        ]