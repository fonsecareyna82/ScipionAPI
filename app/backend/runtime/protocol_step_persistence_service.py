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

    def loadProtocolStepsForPostgresql(self, protocol: Any) -> List[Any]:
        for methodName in ("loadSteps", "getSteps"):
            try:
                method = getattr(protocol, methodName, None)
                if not callable(method):
                    continue

                steps = method() or []
                steps = list(steps)

                if steps:
                    return steps

            except Exception:
                logger.debug(
                    "Could not load protocol steps using %s.",
                    methodName,
                    exc_info=True,
                )

        for attrName in ("_steps", "steps"):
            try:
                steps = getattr(protocol, attrName, None)

                if not steps:
                    continue

                if isinstance(steps, dict):
                    steps = list(steps.values())
                else:
                    steps = list(steps)

                if steps:
                    return steps

            except Exception:
                logger.debug(
                    "Could not load protocol steps from attribute %s.",
                    attrName,
                    exc_info=True,
                )

        return []

    def buildProtocolStepsForPostgresql(self, protocol: Any) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []

        steps = self.loadProtocolStepsForPostgresql(protocol)

        if not steps:
            return result

        for step in steps:
            try:
                stepIndex = self.safeProtocolStepCall(step, "getIndex", None)

                if stepIndex is None:
                    continue

                elapsedSeconds = None
                elapsed = self.safeProtocolStepCall(step, "getElapsedTime", None)

                try:
                    if elapsed is not None:
                        elapsedSeconds = elapsed.total_seconds()
                except Exception:
                    elapsedSeconds = None

                stepName = self.safeProtocolStepValue(
                    getattr(step, "funcName", None),
                    None,
                )

                if not stepName:
                    stepName = self.safeProtocolStepCall(step, "getClassName", "")

                prerequisites = []
                rawPrerequisites = self.safeProtocolStepCall(
                    step,
                    "getPrerequisites",
                    [],
                )

                try:
                    prerequisites = [
                        int(prerequisite)
                        for prerequisite in (rawPrerequisites or [])
                    ]
                except Exception:
                    prerequisites = []

                rawArgs = self.safeProtocolStepValue(
                    getattr(step, "argsStr", None),
                    None,
                )

                needsGpu = self.safeProtocolStepCall(step, "needsGPU", None)

                if needsGpu is None:
                    needsGpu = True

                result.append({
                    "index": int(stepIndex),
                    "name": str(stepName or ""),
                    "status": self.safeProtocolStepCall(step, "getStatus", ""),
                    "prerequisites": prerequisites,
                    "args": self.safeProtocolStepJsonValue(rawArgs),
                    "initTime": self.safeProtocolStepValue(
                        getattr(step, "initTime", None),
                        None,
                    ),
                    "endTime": self.safeProtocolStepValue(
                        getattr(step, "endTime", None),
                        None,
                    ),
                    "elapsedSeconds": elapsedSeconds,
                    "error": self.safeProtocolStepCall(step, "getErrorMessage", None),
                    "interactive": bool(
                        self.safeProtocolStepCall(step, "isInteractive", False)
                    ),
                    "needsGpu": bool(needsGpu),
                    "event": "snapshot",
                })

            except Exception:
                logger.debug(
                    "Could not serialize protocol step for PostgreSQL.",
                    exc_info=True,
                )

        return result