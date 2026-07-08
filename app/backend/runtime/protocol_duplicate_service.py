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
# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# ******************************************************************************

import copy
from typing import Any, Dict

from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)


class RuntimeProtocolDuplicateService:
    """Runtime helpers for PostgreSQL protocol duplication."""

    runtimeParamKeysToDrop = (
        "status",
        "initTime",
        "endTime",
        "_error",
        "_resultFiles",
        "_outputs",
        "_useOutputList",
        "_jobId",
        "_pid",
        "_stepsDone",
        "_cpuTime",
        "_numberOfSteps",
        "lastUpdateTimeStamp",
    )

    def buildDuplicatedProtocolParams(
            self,
            sourceProtocol,
            sourceParams: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build params for a duplicated protocol.

        Duplicates must keep configuration params, but must not carry runtime
        state, output attrs or pointer values. Pointers are restored later from
        protocol_input_refs.
        """
        params = copy.deepcopy(sourceParams or {})

        for key in list(params.keys()):
            try:
                param = sourceProtocol.getParam(key)
            except Exception:
                param = None

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                params.pop(key, None)
                continue

            if str(key).startswith("_outputs"):
                params.pop(key, None)
                continue

            if key in self.runtimeParamKeysToDrop:
                params.pop(key, None)

        self._markRunNameAsCopy(params)

        return params

    @staticmethod
    def _markRunNameAsCopy(params: Dict[str, Any]) -> None:
        try:
            runName = params.get("runName")

            if isinstance(runName, dict):
                oldValue = runName.get("value") or runName.get("editableValue")

                if oldValue:
                    runName["value"] = "%s copy" % oldValue
                    runName["editableValue"] = "%s copy" % oldValue

            elif runName:
                params["runName"] = "%s copy" % runName

        except Exception:
            pass