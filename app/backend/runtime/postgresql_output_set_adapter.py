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
import inspect
import logging
import os
import uuid
from types import MethodType
from typing import Any, Dict

import pyworkflow.utils as pwutils
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

        self._classCreatePatches: Dict[
            type,
            Dict[str, Any],
        ] = {}

        self._createdSets: Dict[
            int,
            Dict[str, Any],
        ] = {}
        self._declaredOutputSetClasses = (
            self._resolveDeclaredOutputSetClasses()
        )

    def _resolveDeclaredOutputSetClasses(
            self,
    ) -> set:
        possibleOutputs = getattr(
            self.protocol,
            "_possibleOutputs",
            None,
        )

        if not isinstance(possibleOutputs, dict):
            return set()

        declaredClasses = set()

        for setClass in possibleOutputs.values():
            if not isinstance(setClass, type):
                continue

            try:
                if issubclass(setClass, ScipionSet):
                    declaredClasses.add(setClass)

            except TypeError:
                continue

        return declaredClasses

    def _shouldRedirectSetClass(
            self,
            setClass,
    ) -> bool:
        """
        Redirect declared output Sets to PostgreSQL.

        Protocols without _possibleOutputs preserve the previous
        behavior for backward compatibility.
        """
        if not self._declaredOutputSetClasses:
            return True

        if not isinstance(setClass, type):
            return False

        for declaredClass in self._declaredOutputSetClasses:
            try:
                if issubclass(setClass, declaredClass):
                    return True

            except TypeError:
                continue

        return False

    def install(self) -> None:
        if self._installed:
            return

        self._patchSpaCreator()
        self._patchTomoCreator()
        self._patchDeclaredOutputClassCreators()
        self._patchInsertChild()
        logger.info(
            "Installed PostgreSQL output Set adapter. "
            "projectId=%s protocolId=%s "
            "protocolClass=%s patchedMethods=%s",
            self.projectId,
            self.protocol.getObjId(),
            self.protocol.__class__.__name__,
            sorted(
                self._patches
            ),
        )
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return

        try:
            self._discardUnfinalizedSets()
        finally:
            try:
                self._restoreDeclaredOutputClassCreators()
            finally:
                for attributeName, patchInfo in reversed(list(self._patches.items())):
                    if patchInfo["hadInstanceAttribute"]:
                        setattr(self.protocol, attributeName, patchInfo["instanceValue"],)
                    else:
                        self.protocol.__dict__.pop(attributeName, None,)

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
            logger.debug(
                "Protocol does not expose a tomography "
                "Set creator. protocolClass=%s "
                "attribute=%s",
                self.protocol.__class__.__name__,
                self.TOMO_CREATE_ATTRIBUTE,
            )

            return

        if not self._isCompatibleSetCreator(
                originalCreator
        ):
            logger.debug(
                "Protocol _createSet() does not match "
                "the Scipion tomography Set creator "
                "contract. protocolClass=%s "
                "creator=%r",
                self.protocol.__class__.__name__,
                originalCreator,
            )

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

        logger.info(
            "Installed PostgreSQL tomography "
            "output Set creator. "
            "projectId=%s protocolId=%s "
            "protocolClass=%s",
            self.projectId,
            self.protocol.getObjId(),
            self.protocol.__class__.__name__,
        )

    def _patchDeclaredOutputClassCreators(
            self,
    ) -> None:
        possibleOutputs = getattr(
            self.protocol,
            "_possibleOutputs",
            None,
        )

        if not isinstance(
                possibleOutputs,
                dict,
        ):
            return

        outputNamesByClass = {}

        for outputName, setClass in (
                possibleOutputs.items()
        ):
            if not isinstance(
                    setClass,
                    type,
            ):
                continue

            try:
                isSetClass = issubclass(
                    setClass,
                    ScipionSet,
                )

            except TypeError:
                isSetClass = False

            if not isSetClass:
                continue

            outputNamesByClass.setdefault(
                setClass,
                [],
            ).append(
                str(outputName)
            )

        for setClass, outputNames in (
                outputNamesByClass.items()
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
                logger.debug(
                    "Not patching declared output "
                    "Set class creator. "
                    "projectId=%s protocolId=%s "
                    "setClass=%s outputNames=%s "
                    "reason=%s",
                    self.projectId,
                    self.protocol.getObjId(),
                    setClass.__name__,
                    outputNames,
                    capability.get(
                        "reason"
                    ),
                )

                continue

            originalCreator = getattr(
                setClass,
                "create",
                None,
            )

            if not callable(
                    originalCreator
            ):
                continue

            if not self._isCompatibleClassCreator(
                    originalCreator
            ):
                logger.debug(
                    "Declared output Set create() "
                    "does not match EMSet.create(). "
                    "setClass=%s creator=%r",
                    setClass.__name__,
                    originalCreator,
                )

                continue

            if (
                    setClass
                    in self._classCreatePatches
            ):
                continue

            hadOwnCreate = (
                    "create"
                    in setClass.__dict__
            )

            ownCreateDescriptor = (
                setClass.__dict__.get(
                    "create"
                )
            )

            adapter = self

            def create(
                    runtimeSetClass,
                    outputPath,
                    prefix=None,
                    suffix=None,
                    ext=None,
                    _originalCreator=originalCreator,
                    **kwargs,
            ):
                return (
                    adapter
                    ._createSetFromClassCreator(
                        originalCreator=(
                            _originalCreator
                        ),
                        setClass=(
                            runtimeSetClass
                        ),
                        outputPath=(
                            outputPath
                        ),
                        prefix=prefix,
                        suffix=suffix,
                        ext=ext,
                        constructorKwargs=kwargs,
                    )
                )

            self._classCreatePatches[
                setClass
            ] = {
                "hadOwnCreate": (
                    hadOwnCreate
                ),
                "ownCreateDescriptor": (
                    ownCreateDescriptor
                ),
                "originalCreator": (
                    originalCreator
                ),
                "outputNames": list(
                    outputNames
                ),
            }

            setattr(
                setClass,
                "create",
                classmethod(
                    create
                ),
            )

            logger.info(
                "Installed PostgreSQL declared "
                "output Set class creator. "
                "projectId=%s protocolId=%s "
                "setClass=%s outputNames=%s",
                self.projectId,
                self.protocol.getObjId(),
                setClass.__name__,
                outputNames,
            )

    @staticmethod
    def _isCompatibleClassCreator(
            creator,
    ) -> bool:
        """
        Detect the common EMSet.create() contract.

        Bound classmethod signature:
            (
                outputPath,
                prefix=None,
                suffix=None,
                ext=None,
                **kwargs
            )
        """
        try:
            signature = inspect.signature(
                creator
            )

        except (
                TypeError,
                ValueError,
        ):
            return False

        parameters = list(
            signature.parameters.values()
        )

        positionalNames = [
            parameter.name
            for parameter in parameters
            if parameter.kind
               in {
                   inspect.Parameter
                   .POSITIONAL_ONLY,

                   inspect.Parameter
                   .POSITIONAL_OR_KEYWORD,
               }
        ]

        if (
                len(positionalNames) < 4
                or positionalNames[:4]
                != [
            "outputPath",
            "prefix",
            "suffix",
            "ext",
        ]
        ):
            return False

        return any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    @staticmethod
    def _isCompatibleSetCreator(
            creator,
    ) -> bool:
        """
        Detect Scipion's common Set creator contract without
        relying on a concrete ProtTomoBase class identity.

        Bound-method signature:
            (SetClass, template, suffix, **kwargs)
        """
        try:
            signature = inspect.signature(
                creator
            )

        except (
                TypeError,
                ValueError,
        ):
            return False

        parameters = list(
            signature.parameters.values()
        )

        parameterNames = [
            parameter.name
            for parameter in parameters
            if parameter.kind
               in {
                   inspect.Parameter
                   .POSITIONAL_ONLY,

                   inspect.Parameter
                   .POSITIONAL_OR_KEYWORD,
               }
        ]

        if (
                len(parameterNames) < 3
                or parameterNames[:3]
                != [
            "SetClass",
            "template",
            "suffix",
        ]
        ):
            return False

        return any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    def _patchInsertChild(self) -> None:
        originalInsertChild = getattr(
            self.protocol,
            self.INSERT_CHILD_ATTRIBUTE,
            None,
        )

        if not callable(originalInsertChild):
            raise RuntimeError(
                "Protocol does not expose _insertChild()."
            )

        adapter = self

        def insertChild(
                protocolSelf,
                key,
                child,
        ):
            outputName = str(key)

            child = adapter._adoptDirectOutputSet(
                outputName=outputName,
                child=child,
            )

            adapter._finalizeOutputSet(
                outputName=outputName,
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

    def _adoptDirectOutputSet(
            self,
            outputName: str,
            child,
    ):
        if not isinstance(child, ScipionSet):
            return child

        if id(child) in self._createdSets:
            return child

        runtimeChecker = getattr(
            child,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if callable(runtimeChecker) and runtimeChecker():
            return child

        setClass = child.__class__

        if not self._shouldRedirectSetClass(setClass):
            return child

        capability = (
            self.runtimeMapper
            .getPostgresqlOutputSetCapability(
                setClass
            )
        )

        if not capability.get("supported"):
            raise NotImplementedError(
                "Directly constructed output Set cannot be "
                "stored natively in PostgreSQL. "
                "outputName=%s setClass=%s reason=%s"
                % (
                    outputName,
                    setClass.__name__,
                    capability.get("reason"),
                )
            )

        if not child.isEmpty():
            raise RuntimeError(
                "Directly constructed output Set must be "
                "declared before appending items. "
                "outputName=%s setClass=%s size=%s"
                % (
                    outputName,
                    setClass.__name__,
                    child.getSize(),
                )
            )

        legacyPath = None

        try:
            legacyPath = child.getFileName()
        except Exception:
            pass

        closeSet = getattr(
            child,
            "close",
            None,
        )

        if callable(closeSet):
            closeSet()

        if legacyPath:
            pwutils.cleanPath(
                legacyPath
            )

        runtimeSet = self._createPostgresqlRuntimeSet(
            setClass=setClass,
            constructorKwargs={},
            creatorKind="direct-constructor",
            creationMetadata={
                "declaredOutputName": outputName,
                "legacyPath": legacyPath,
            },
            existingSet=child,
        )

        if runtimeSet is not child:
            raise RuntimeError(
                "Directly constructed output Set was not "
                "promoted in place. "
                "outputName=%s setClass=%s"
                % (
                    outputName,
                    setClass.__name__,
                )
            )

        return child

    def _createSetFromClassCreator(
            self,
            originalCreator,
            setClass,
            outputPath,
            prefix,
            suffix,
            ext,
            constructorKwargs,
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
            return originalCreator(
                outputPath,
                prefix=prefix,
                suffix=suffix,
                ext=ext,
                **dict(
                    constructorKwargs
                    or {}
                ),
            )

        legacyPath = (
            self._buildLegacyClassCreatePath(
                setClass=setClass,
                outputPath=outputPath,
                prefix=prefix,
                suffix=suffix,
                ext=ext,
            )
        )

        # Preserve EMSet.create() restart semantics:
        # remove a SQLite left by an earlier execution.
        #
        # The new execution will not create it again.
        pwutils.cleanPath(
            legacyPath
        )

        return (
            self
            ._createPostgresqlRuntimeSet(
                setClass=setClass,
                constructorKwargs=(
                    constructorKwargs
                ),
                creatorKind="class-create",
                creationMetadata={
                    "outputPath": str(
                        outputPath
                    ),
                    "prefix": prefix,
                    "suffix": suffix,
                    "ext": ext,
                    "legacyPath": (
                        legacyPath
                    ),
                },
            )
        )

    @staticmethod
    def _buildLegacyClassCreatePath(
            setClass,
            outputPath,
            prefix=None,
            suffix=None,
            ext=None,
    ) -> str:
        filePrefix = (
                prefix
                or setClass.__name__
                .lower()
                .replace(
            "setof",
            "",
        )
        )

        if suffix:
            filePrefix += (
                    "_%s"
                    % suffix
            )

        extension = str(
            ext or "sqlite"
        )

        if extension.startswith(
                "."
        ):
            extension = extension[1:]

        fileName = "%s.%s" % (
            filePrefix,
            extension,
        )

        return os.path.join(
            outputPath,
            fileName,
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
        if not self._shouldRedirectSetClass(
                setClass
        ):
            logger.debug(
                "Using native SQLite working Set. "
                "projectId=%s protocolId=%s "
                "protocolClass=%s setClass=%s creator=%s",
                self.projectId,
                self.protocol.getObjId(),
                self.protocol.__class__.__name__,
                getattr(
                    setClass,
                    "__name__",
                    str(setClass),
                ),
                creatorKind,
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

        return (
            self
            ._createPostgresqlRuntimeSet(
                setClass=setClass,
                constructorKwargs=(
                    constructorKwargs
                ),
                creatorKind=creatorKind,
                creationMetadata={
                    "template": str(
                        template
                    ),
                    "suffix": str(
                        suffix
                    ),
                },
            )
        )

    def _createPostgresqlRuntimeSet(
            self,
            setClass,
            constructorKwargs,
            creatorKind: str,
            creationMetadata=None,
            existingSet=None,
    ):
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
                provisionalOutputName=provisionalOutputName,
                constructorKwargs=dict(constructorKwargs or {}),
                reservationToken=reservationToken,
                runtimeSet=existingSet,
            )
        )

        entry = {
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
            "creatorKind": (
                creatorKind
            ),
        }

        entry.update(
            dict(
                creationMetadata
                or {}
            )
        )

        self._createdSets[
            id(runtimeSet)
        ] = entry

        logger.info(
            "Created native PostgreSQL output Set. "
            "projectId=%s protocolId=%s "
            "runtimeObjectId=%s className=%s "
            "provisionalOutputName=%s "
            "creator=%s",
            self.projectId,
            self.protocol.getObjId(),
            runtimeSet.getObjId(),
            runtimeSet.getClassName(),
            provisionalOutputName,
            creatorKind,
        )

        return runtimeSet

    def _restoreDeclaredOutputClassCreators(
            self,
    ) -> None:
        for setClass, patchInfo in reversed(
                list(
                    self._classCreatePatches
                            .items()
                )
        ):
            if patchInfo[
                "hadOwnCreate"
            ]:
                setattr(
                    setClass,
                    "create",
                    patchInfo[
                        "ownCreateDescriptor"
                    ],
                )

            else:
                try:
                    delattr(
                        setClass,
                        "create",
                    )

                except AttributeError:
                    pass

        self._classCreatePatches.clear()

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