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
from typing import Any, Dict, List, Optional


class RuntimeProtocolInputRefBuilderService:
    """Build PostgreSQL runtime protocol_input_refs from Scipion pointers."""

    def safeCall(self, obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)

            if method is None:
                return default

            return method()

        except Exception:
            return default

    def getScipionClassName(self, obj: Any) -> Optional[str]:
        if obj is None:
            return None

        className = self.safeCall(obj, "getClassName", None)

        if className:
            return str(className)

        return obj.__class__.__name__

    def getScipionObjectId(self, obj: Any) -> Optional[Any]:
        return self.safeCall(obj, "getObjId", None)

    def iterProtocolInputPointers(self, pointer: Any) -> List[Any]:
        if pointer is None:
            return []

        if isinstance(pointer, (list, tuple, set)):
            return list(pointer)

        try:
            if not isinstance(pointer, (str, bytes, dict)):
                items = list(pointer)

                if items:
                    return items

        except Exception:
            pass

        return [pointer]

    def getPointerTargetObject(self, pointer: Any) -> Any:
        if pointer is None:
            return None

        target = self.safeCall(pointer, "get", None)

        if target is not None:
            return target

        return pointer

    def getPointerParentProtocolId(
            self,
            pointer: Any,
            targetObj: Any,
    ) -> Optional[Any]:
        pointerObj = self.safeCall(pointer, "getObjValue", None)
        parentProtocolId = self.safeCall(pointerObj, "getObjId", None)

        if parentProtocolId is not None:
            return parentProtocolId

        parentObj = self.safeCall(targetObj, "getObjParent", None)
        parentProtocolId = self.safeCall(parentObj, "getObjId", None)

        if parentProtocolId is not None:
            return parentProtocolId

        return None

    def getPointerOutputName(self, pointer: Any) -> Optional[str]:
        outputName = self.safeCall(pointer, "getExtended", None)

        if outputName is None:
            return None

        outputNameText = str(outputName).strip()

        return outputNameText or None

    def buildProtocolInputRefsForPostgresql(
            self,
            projectId: int,
            protocol: Any,
            protocolDbIdByScipionId: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        protocolId = self.getScipionObjectId(protocol)

        if protocolId is None:
            return []

        protocolIdText = str(protocolId)
        protocolDbId = protocolDbIdByScipionId.get(protocolIdText)

        if protocolDbId is None:
            return []

        try:
            inputAttributes = list(protocol.iterInputAttributes())
        except Exception:
            return []

        refs: List[Dict[str, Any]] = []
        nextItemIndexByInputName: Dict[str, int] = {}

        for inputName, pointer in inputAttributes:
            inputNameText = str(inputName)
            pointerItems = self.iterProtocolInputPointers(
                pointer
            )

            itemIndex = nextItemIndexByInputName.get(
                inputNameText,
                0,
            )

            for pointerItem in pointerItems:
                targetObj = self.getPointerTargetObject(
                    pointerItem
                )

                if targetObj is None:
                    continue

                parentProtocolId = self.getPointerParentProtocolId(
                    pointerItem,
                    targetObj,
                )
                parentProtocolIdText = (
                    str(parentProtocolId)
                    if parentProtocolId is not None
                    else None
                )
                parentProtocolDbId = (
                    protocolDbIdByScipionId.get(
                        parentProtocolIdText
                    )
                    if parentProtocolIdText is not None
                    else None
                )

                targetObjectId = self.getScipionObjectId(
                    targetObj
                )

                refs.append({
                    "projectId": int(projectId),
                    "protocolDbId": int(protocolDbId),
                    "protocolId": protocolIdText,
                    "inputName": inputNameText,
                    "itemIndex": int(itemIndex),
                    "parentProtocolDbId": parentProtocolDbId,
                    "parentProtocolId": parentProtocolIdText,
                    "parentOutputName": self.getPointerOutputName(
                        pointerItem
                    ),
                    "objectClassName": self.getScipionClassName(
                        targetObj
                    ),
                    "objectId": (
                        str(targetObjectId)
                        if targetObjectId is not None
                        else None
                    ),
                })

                itemIndex += 1

            nextItemIndexByInputName[
                inputNameText
            ] = itemIndex

        return refs