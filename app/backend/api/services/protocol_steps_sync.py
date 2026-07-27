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
import os
from typing import Any, Dict, List, Optional

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.runtime.protocol_step_persistence_service import (
    RuntimeProtocolStepPersistenceService,
)

logger = logging.getLogger(__name__)


def _value(obj: Any, default=None):
    try:
        if hasattr(obj, "hasValue") and not obj.hasValue():
            return default
        if hasattr(obj, "get"):
            return obj.get(default)
    except TypeError:
        try:
            return obj.get()
        except Exception:
            return default
    except Exception:
        return default
    return obj if obj is not None else default


def _jsonValue(text: Any):
    if text in (None, ""):
        return None
    try:
        return json.loads(str(text))
    except Exception:
        return str(text)


def _projectPath(protocol) -> Optional[str]:
    project = protocol.getProject()
    for attr in ("path", "_path"):
        value = getattr(project, attr, None)
        if value:
            return os.path.abspath(str(value))
    if hasattr(project, "getPath"):
        return os.path.abspath(str(project.getPath()))
    return None


def _tryRegisterProtocolOutputs(
        mapper: PostgresqlFlatMapper,
        projectId: int,
        protocolDbId: int,
        protocolId: int,
        protocol,
) -> None:
    """
    Opportunistically register protocol outputs while the runtime process updates
    steps.

    This is important for streaming protocols: outputs can exist while the
    protocol is still running.
    """
    try:
        from app.backend.api.services.project_service import ProjectService

        service = ProjectService()

        if not service._shouldRegisterProtocolOutputs(protocol):
            return

        report = service.registerOutput(
            projectId=projectId,
            protocol=protocol,
            mapper=mapper,
            returnReport=True,
        )

        logger.info(
            "Registered PostgreSQL runtime outputs from steps event. "
            "projectId=%s protocolDbId=%s protocolId=%s outputs=%s declared=%s errors=%s",
            projectId,
            protocolDbId,
            protocolId,
            len(report.get("persisted") or []),
            len(report.get("declared") or []),
            report.get("errors") or [],
        )

    except Exception:
        logger.exception(
            "Could not register PostgreSQL runtime outputs from steps event. "
            "projectId=%s protocolDbId=%s protocolId=%s",
            projectId,
            protocolDbId,
            protocolId,
        )


_stepPersistenceService = (
    RuntimeProtocolStepPersistenceService()
)


def _serializeStep(
        step,
        event: str,
) -> Dict[str, Any]:
    return (
        _stepPersistenceService
        .buildProtocolStepForPostgresql(
            step,
            event=event,
        )
    )


def _buildMapper() -> PostgresqlFlatMapper:
    db = PostgresqlDb(
        dbName=os.environ["DATABASE_NAME"],
        user=os.environ["DATABASE_USER"],
        password=os.environ["DATABASE_PASS"],
    )
    return PostgresqlFlatMapper(db)


def syncProtocolStepsEvent(protocol, event: str, steps: List[Any], step: Any = None) -> None:
    mapper = _buildMapper()
    try:
        projectPath = _projectPath(protocol)
        target = mapper.resolveProtocolStepTarget(projectPath, protocol.getObjId())
        if not target:
            logger.warning("Protocol steps target not found. projectPath=%s protocolId=%s", projectPath, protocol.getObjId())
            return

        projectId = int(target["projectId"])
        protocolDbId = int(target["protocolDbId"])
        protocolId = int(protocol.getObjId())

        if event == "steps-stored":
            mapper.replaceProtocolSteps(
                projectId,
                protocolDbId,
                protocolId,
                [_serializeStep(s, event) for s in steps],
            )
        elif step is not None:
            mapper.upsertProtocolStep(
                projectId,
                protocolDbId,
                protocolId,
                _serializeStep(step, event),
            )
        _tryRegisterProtocolOutputs(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            protocolId=protocolId,
            protocol=protocol,
        )
    finally:
        mapper.db.close()


def _setStepScalar(
        step,
        attrName: str,
        value,
) -> None:
    attr = getattr(
        step,
        attrName,
        None,
    )

    setter = getattr(
        attr,
        "set",
        None,
    )

    if not callable(setter):
        return

    if value is None:
        setter(None)
        return

    if hasattr(
            value,
            "strftime",
    ):
        value = value.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )

    setter(
        value
    )


def _restorePreviousStep(
        templateStep,
        row: Dict[str, Any],
):
    previousStep = (
        templateStep.clone()
    )

    stepIndex = int(
        row["index"]
    )

    previousStep.setIndex(
        stepIndex
    )

    previousStep.setPrerequisites(
        *[
            int(value)
            for value in (
                row.get(
                    "prerequisites"
                )
                or []
            )
        ]
    )

    previousStep.setStatus(
        row.get(
            "status"
        )
        or ""
    )

    _setStepScalar(
        previousStep,
        "funcName",
        row.get(
            "name"
        )
        or "",
    )

    argsText = row.get(
        "argsText"
    )

    if argsText is None:
        argsText = json.dumps(
            row.get("args"),
            default=lambda value: None,
        )

    _setStepScalar(
        previousStep,
        "argsStr",
        argsText,
    )

    resultFiles = row.get(
        "resultFiles"
    )

    _setStepScalar(
        previousStep,
        "_resultFiles",
        (
            json.dumps(
                resultFiles
            )
            if resultFiles is not None
            else None
        ),
    )

    _setStepScalar(
        previousStep,
        "initTime",
        row.get(
            "initTime"
        ),
    )

    _setStepScalar(
        previousStep,
        "endTime",
        row.get(
            "endTime"
        ),
    )

    _setStepScalar(
        previousStep,
        "_error",
        row.get(
            "error"
        ),
    )

    _setStepScalar(
        previousStep,
        "interactive",
        bool(
            row.get(
                "interactive"
            )
        ),
    )

    _setStepScalar(
        previousStep,
        "_needsGPU",
        bool(
            row.get(
                "needsGpu",
                True,
            )
        ),
    )

    return previousStep


def loadProtocolSteps(
        protocol,
        currentSteps=None,
) -> List[Any]:
    """
    Reconstruct the previous execution steps from PostgreSQL.

    Current step definitions are cloned so bound functions and
    plugin-specific step classes come from the running protocol,
    while execution state comes from PostgreSQL.
    """
    mapper = _buildMapper()

    try:
        target = mapper.resolveProtocolStepTarget(
            _projectPath(protocol),
            protocol.getObjId(),
        )

        if not target:
            return []

        rows = mapper.listProtocolSteps(
            projectId=int(
                target["projectId"]
            ),
            protocolId=int(
                protocol.getObjId()
            ),
        ) or []

        currentSteps = list(
            currentSteps
            if currentSteps is not None
            else (
                getattr(
                    protocol,
                    "_steps",
                    None,
                )
                or []
            )
        )

        if not currentSteps:
            return []

        rowsByIndex = {
            int(row["index"]): row
            for row in rows
            if row.get("index") is not None
        }

        previousSteps = []

        for stepIndex, templateStep in enumerate(
                currentSteps,
                start=1,
        ):
            row = rowsByIndex.get(
                stepIndex
            )

            # Never shift subsequent steps if one row is missing.
            if row is None:
                break

            # Snapshots written before the complete schema must not
            # be used to skip execution.
            if int(
                    row.get(
                        "schemaVersion"
                    )
                    or 1
            ) < 2:
                return []

            previousSteps.append(
                _restorePreviousStep(
                    templateStep,
                    row,
                )
            )

        return previousSteps

    finally:
        mapper.db.close()

