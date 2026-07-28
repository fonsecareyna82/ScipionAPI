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
import uuid
from types import MethodType
from typing import Any, Dict

from pyworkflow.object import (
    Set as ScipionSet,
)

logger = logging.getLogger(
    __name__
)


class RuntimePostgresqlOutputSetAdapter:
    """
    Redirect native Scipion output Set creation to PostgreSQL.

    Plugins continue calling the standard API:
        self._createSetOfParticles()
        self._createSetOfTomograms()
        output.append(item)
        self._defineOutputs(outputParticles=output)

    Only this runtime protocol instance is patched.
    """

    SPA_CREATE_ATTRIBUTE = (
        "_EMProtocol__createSet"
    )

    TOMO_CREATE_ATTRIBUTE = (
        "_createSet"
    )

    INSERT_CHILD_ATTRIBUTE = (
        "_insertChild"
    )

    def __init__(
            self,
            runtimeMapper,
            projectId: int,
            protocol,
    ):
        self.runtimeMapper = (
            runtimeMapper
        )

        self.projectId = int(
            projectId
        )

        self.protocol = protocol

        self._installed = False
        self._patches: Dict[
            str,
            Dict[str, Any],
        ] = {}

        self._createdSets: Dict[
            int,
            Dict[str, Any],
        ] = {}

    def install(self) -> None:
        if self._installed:
            return

        self._patchSpaCreator()
        self._patchTomoCreator()
        self._patchInsertChild()

        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return

        try:
            self._discardUnfinalizedSets()

        finally:
            for attributeName, patchInfo in reversed(
                    list(
                        self._patches.items()
                    )
            ):
                if patchInfo[
                    "hadInstanceAttribute"
                ]:
                    setattr(
                        self.protocol,
                        attributeName,
                        patchInfo[
                            "instanceValue"
                        ],
                    )
                else:
                    self.protocol.__dict__.pop(
                        attributeName,
                        None,
                    )

            self._patches.clear()
            self._installed = False

    def _patchSpaCreator(self) -> None:
        originalCreator = getattr(
            self.protocol,
            self.SPA_CREATE_ATTRIBUTE,
            None,
        )

        if not callable(
                originalCreator
        ):
            return

        adapter = self

        def createSet(
                protocolSelf,
                SetClass,
                template,
                suffix,
                **kwargs,
        ):
            return adapter._createSet(
                originalCreator=(
                    originalCreator
                ),
                setClass=SetClass,
                template=template,
                suffix=suffix,
                constructorKwargs=kwargs,
                creatorKind="spa",
            )

        self._patchMethod(
            self.SPA_CREATE_ATTRIBUTE,
            createSet,
        )

    def _patchTomoCreator(self) -> None:
        originalCreator = getattr(
            self.protocol,
            self.TOMO_CREATE_ATTRIBUTE,
            None,
        )

        if not callable(
                originalCreator
        ):
            return

        # Do not patch arbitrary plugin methods named
        # _createSet. The tomography base creator always
        # receives SetClass, template and suffix.
        try:
            from tomo.protocols.protocol_base import (
                ProtTomoBase,
            )

            if not isinstance(
                    self.protocol,
                    ProtTomoBase,
            ):
                return

        except Exception:
            return

        adapter = self

        def createSet(
                protocolSelf,
                SetClass,
                template,
                suffix,
                **kwargs,
        ):
            return adapter._createSet(
                originalCreator=(
                    originalCreator
                ),
                setClass=SetClass,
                template=template,
                suffix=suffix,
                constructorKwargs=kwargs,
                creatorKind="tomo",
            )

        self._patchMethod(
            self.TOMO_CREATE_ATTRIBUTE,
            createSet,
        )

    def _patchInsertChild(self) -> None:
        originalInsertChild = getattr(
            self.protocol,
            self.INSERT_CHILD_ATTRIBUTE,
            None,
        )

        if not callable(
                originalInsertChild
        ):
            raise RuntimeError(
                "Protocol does not expose _insertChild()."
            )

        adapter = self

        def insertChild(
                protocolSelf,
                key,
                child,
        ):
            adapter._finalizeOutputSet(
                outputName=str(key),
                child=child,
            )

            return originalInsertChild(
                key,
                child,
            )

        self._patchMethod(
            self.INSERT_CHILD_ATTRIBUTE,
            insertChild,
        )

    def _createSet(
            self,
            originalCreator,
            setClass,
            template,
            suffix,
            constructorKwargs,
            creatorKind: str,
    ):
        capability = (
            self.runtimeMapper
            .getPostgresqlOutputSetCapability(
                setClass
            )
        )

        if not capability.get(
                "supported"
        ):
            logger.warning(
                "Using native SQLite output Set "
                "compatibility path. "
                "projectId=%s protocolId=%s "
                "setClass=%s creator=%s reason=%s",
                self.projectId,
                self.protocol.getObjId(),
                getattr(
                    setClass,
                    "__name__",
                    str(setClass),
                ),
                creatorKind,
                capability.get(
                    "reason"
                ),
            )

            return originalCreator(
                setClass,
                template,
                suffix,
                **dict(
                    constructorKwargs
                    or {}
                ),
            )

        reservationToken = (
            uuid.uuid4().hex
        )

        provisionalOutputName = (
            "__postgresql_runtime_output_%s"
            % reservationToken
        )

        runtimeSet = (
            self.runtimeMapper
            .createPostgresqlOutputSet(
                protocol=self.protocol,
                setClass=setClass,
                provisionalOutputName=(
                    provisionalOutputName
                ),
                constructorKwargs=(
                    constructorKwargs
                ),
                reservationToken=(
                    reservationToken
                ),
            )
        )

        self._createdSets[
            id(runtimeSet)
        ] = {
            "runtimeSet": runtimeSet,
            "runtimeObjectId": (
                runtimeSet.getObjId()
            ),
            "provisionalOutputName": (
                provisionalOutputName
            ),
            "outputName": None,
            "finalized": False,
            "setClassName": (
                runtimeSet.getClassName()
            ),
            "template": str(
                template
            ),
            "suffix": str(
                suffix
            ),
            "creatorKind": creatorKind,
        }

        logger.info(
            "Created native PostgreSQL output Set. "
            "projectId=%s protocolId=%s "
            "runtimeObjectId=%s className=%s "
            "provisionalOutputName=%s",
            self.projectId,
            self.protocol.getObjId(),
            runtimeSet.getObjId(),
            runtimeSet.getClassName(),
            provisionalOutputName,
        )

        return runtimeSet

    def _finalizeOutputSet(
            self,
            outputName: str,
            child,
    ) -> None:
        if not isinstance(
                child,
                ScipionSet,
        ):
            return

        entry = self._createdSets.get(
            id(child)
        )

        if entry is None:
            return

        if entry["finalized"]:
            return

        report = (
            self.runtimeMapper
            .finalizePostgresqlOutputSet(
                protocol=self.protocol,
                outputName=outputName,
                runtimeSet=child,
            )
        )

        entry["finalized"] = True
        entry["outputName"] = (
            outputName
        )
        entry["report"] = report

        logger.info(
            "Finalized native PostgreSQL output Set. "
            "projectId=%s protocolId=%s "
            "runtimeObjectId=%s outputName=%s "
            "setId=%s",
            self.projectId,
            self.protocol.getObjId(),
            child.getObjId(),
            outputName,
            report.get(
                "setId"
            ),
        )

    def _discardUnfinalizedSets(
            self,
    ) -> None:
        for entry in list(
                self._createdSets.values()
        ):
            if entry.get(
                    "finalized"
            ):
                continue

            runtimeSet = entry[
                "runtimeSet"
            ]

            try:
                discarded = (
                    self.runtimeMapper
                    .discardPostgresqlOutputSet(
                        protocol=self.protocol,
                        runtimeSet=runtimeSet,
                    )
                )

                logger.info(
                    "Discarded unregistered PostgreSQL "
                    "output Set reservation. "
                    "projectId=%s protocolId=%s "
                    "runtimeObjectId=%s discarded=%s",
                    self.projectId,
                    self.protocol.getObjId(),
                    runtimeSet.getObjId(),
                    discarded,
                )

            except Exception:
                logger.exception(
                    "Could not discard unregistered "
                    "PostgreSQL output Set reservation. "
                    "projectId=%s protocolId=%s "
                    "runtimeObjectId=%s",
                    self.projectId,
                    self.protocol.getObjId(),
                    runtimeSet.getObjId(),
                )

        self._createdSets.clear()

    def _patchMethod(
            self,
            attributeName: str,
            function,
    ) -> None:
        if attributeName in self._patches:
            return

        hadInstanceAttribute = (
            attributeName
            in self.protocol.__dict__
        )

        instanceValue = (
            self.protocol.__dict__.get(
                attributeName
            )
        )

        self._patches[
            attributeName
        ] = {
            "hadInstanceAttribute": (
                hadInstanceAttribute
            ),
            "instanceValue": (
                instanceValue
            ),
        }

        setattr(
            self.protocol,
            attributeName,
            MethodType(
                function,
                self.protocol,
            ),
        )