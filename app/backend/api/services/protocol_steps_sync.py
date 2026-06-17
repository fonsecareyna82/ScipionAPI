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


def _serializeStep(step, event: str) -> Dict[str, Any]:
    elapsed = None
    try:
        elapsed = step.getElapsedTime().total_seconds()
    except Exception:
        pass

    return {
        "index": int(step.getIndex() or 0),
        "name": _value(getattr(step, "funcName", None), step.getClassName()),
        "status": step.getStatus(),
        "prerequisites": [int(p) for p in step.getPrerequisites()],
        "args": _jsonValue(_value(getattr(step, "argsStr", None))),
        "initTime": _value(getattr(step, "initTime", None)),
        "endTime": _value(getattr(step, "endTime", None)),
        "elapsedSeconds": elapsed,
        "error": step.getErrorMessage(),
        "interactive": step.isInteractive(),
        "needsGpu": step.needsGPU(),
        "event": event,
    }


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
    finally:
        mapper.db.close()