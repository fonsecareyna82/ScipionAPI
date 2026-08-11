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

from typing import Any, Dict, List, Optional

from pyworkflow.protocol.protocol import Protocol


logger = logging.getLogger(__name__)


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
        """
        Resolve the producer protocol of a Scipion pointer.

        Supported pointer representations:

        - Pointer(parentProtocol, extended="outputName")
        - Pointer(outputObject)
        - Pointer(parentProtocol)
        """
        pointerObj = self.safeCall(
            pointer,
            "getObjValue",
            None,
        )

        # Pointer directly targeting a protocol.
        if isinstance(targetObj, Protocol):
            return self.getScipionObjectId(
                targetObj
            )

        # Standard modern pointer:
        # Pointer(parentProtocol, extended="outputName").
        if isinstance(pointerObj, Protocol):
            return self.getScipionObjectId(
                pointerObj
            )

        # Legacy/direct pointer to an output object.
        # The output object id is not the producer protocol id.
        for candidate in (
                targetObj,
                pointerObj,
        ):
            if candidate is None:
                continue

            parentProtocolId = self.safeCall(
                candidate,
                "getObjParentId",
                None,
            )

            if parentProtocolId not in (
                    None,
                    "",
            ):
                return parentProtocolId

            parentProtocol = self.safeCall(
                candidate,
                "getObjParent",
                None,
            )

            parentProtocolId = (
                self.getScipionObjectId(
                    parentProtocol
                )
            )

            if parentProtocolId not in (
                    None,
                    "",
            ):
                return parentProtocolId

        # Compatibility fallback for proxy-like protocol objects.
        extended = self.safeCall(
            pointer,
            "getExtended",
            None,
        )

        if str(extended or "").strip():
            parentProtocolId = (
                self.getScipionObjectId(
                    pointerObj
                )
            )

            if parentProtocolId not in (
                    None,
                    "",
            ):
                return parentProtocolId

        return None

    def getPointerOutputName(
            self,
            pointer: Any,
            targetObj: Any,
            parentProtocolId: Any,
    ) -> Optional[str]:
        """
        Resolve the pointed protocol output name.

        Modern pointers store it in ``extended``. Direct/legacy pointers
        store it in the output object's SQLite name.
        """
        outputName = self.safeCall(
            pointer,
            "getExtended",
            None,
        )

        outputNameText = str(
            outputName or ""
        ).strip()

        if outputNameText:
            return outputNameText

        pointerObj = self.safeCall(
            pointer,
            "getObjValue",
            None,
        )

        for candidate in (
                targetObj,
                pointerObj,
        ):
            if (
                    candidate is None
                    or isinstance(candidate, Protocol)
            ):
                continue

            objectName = self.safeCall(
                candidate,
                "getObjName",
                None,
            )

            if objectName in (None, ""):
                objectName = getattr(
                    candidate,
                    "_objName",
                    None,
                )

            objectNameText = str(
                objectName or ""
            ).strip()

            if not objectNameText:
                continue

            if parentProtocolId not in (
                    None,
                    "",
            ):
                expectedPrefix = "%s." % (
                    parentProtocolId,
                )

                if objectNameText.startswith(
                        expectedPrefix
                ):
                    resolvedName = objectNameText[
                                   len(expectedPrefix):
                                   ].strip()

                    if resolvedName:
                        return resolvedName

            if "." in objectNameText:
                possibleParentId, possibleOutputName = (
                    objectNameText.split(
                        ".",
                        1,
                    )
                )

                try:
                    int(possibleParentId)
                    possibleParentIsProtocolId = True
                except Exception:
                    possibleParentIsProtocolId = False

                if (
                        possibleParentIsProtocolId
                        and possibleOutputName.strip()
                ):
                    return possibleOutputName.strip()

            return objectNameText

        return None

    def buildProtocolInputRefsForPostgresql(
            self,
            projectId: int,
            protocol: Any,
            protocolDbIdByScipionId: Dict[str, int],
            strict: bool = False,
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

                parentOutputName = (
                    self.getPointerOutputName(
                        pointer=pointerItem,
                        targetObj=targetObj,
                        parentProtocolId=(
                            parentProtocolId
                        ),
                    )
                )

                pointerObj = self.safeCall(
                    pointerItem,
                    "getObjValue",
                    None,
                )

                directProtocolPointer = (
                        not parentOutputName
                        and (
                                isinstance(targetObj, Protocol)
                                or isinstance(pointerObj, Protocol)
                        )
                )

                missingFields = []

                if parentProtocolId in (
                        None,
                        "",
                ):
                    missingFields.append(
                        "parentProtocolId"
                    )

                if parentProtocolDbId in (
                        None,
                        "",
                ):
                    missingFields.append(
                        "parentProtocolDbId"
                    )

                if not parentOutputName and not directProtocolPointer:
                    missingFields.append(
                        "parentOutputName"
                    )

                if missingFields:
                    message = (
                        "Could not resolve PostgreSQL protocol "
                        "input ref. projectId=%s protocolId=%s "
                        "inputName=%s itemIndex=%s "
                        "missing=%s targetClass=%s "
                        "targetObjectId=%s"
                        % (
                            projectId,
                            protocolIdText,
                            inputNameText,
                            itemIndex,
                            missingFields,
                            self.getScipionClassName(
                                targetObj
                            ),
                            self.getScipionObjectId(
                                targetObj
                            ),
                        )
                    )

                    if strict:
                        raise RuntimeError(
                            message
                        )

                    logger.warning(
                        message
                    )

                    continue

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
                    "parentOutputName": parentOutputName,
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