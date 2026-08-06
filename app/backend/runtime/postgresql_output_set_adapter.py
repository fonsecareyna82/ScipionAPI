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
import threading
import uuid
from types import MethodType
from typing import Any, Dict

import pyworkflow.utils as pwutils
from pyworkflow.object import (
    Set as ScipionSet,
)
from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import (
    PostgresqlRuntimeSetSqliteMaterializer,
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

    DELETE_CHILD_ATTRIBUTE = (
        "_deleteChild"
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
        self._finalizedSetsByOutputName: Dict[
            str,
            Any,
        ] = {}

        self._pendingOutputSetReplacements: Dict[
            str,
            Any,
        ] = {}
        self._pendingOutputMetadataSources: Dict[
            str,
            Any,
        ] = {}

        self._directRuntimeSetsByStorageKey: Dict[
            tuple,
            Any,
        ] = {}

        self._directCanonicalSetsByAliasIdentity: Dict[
            int,
            Any,
        ] = {}

        self._directSetLoadPatch = None
        self._directSetLock = threading.RLock()

    def install(self) -> None:
        if self._installed:
            return

        self._patchSpaCreator()
        self._patchTomoCreator()
        self._patchDeclaredOutputClassCreators()
        self._patchDeleteChild()
        self._patchInsertChild()
        self._patchDirectSetLoad()
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
            self._restoreDirectSetLoad()

            try:
                self._restoreDeclaredOutputClassCreators()

            finally:
                for attributeName, patchInfo in reversed(
                        list(self._patches.items())
                ):
                    if patchInfo["hadInstanceAttribute"]:
                        setattr(
                            self.protocol,
                            attributeName,
                            patchInfo["instanceValue"],
                        )
                    else:
                        self.protocol.__dict__.pop(
                            attributeName,
                            None,
                        )

                self._patches.clear()
                self._createdSets.clear()
                self._finalizedSetsByOutputName.clear()
                self._pendingOutputSetReplacements.clear()
                self._pendingOutputMetadataSources.clear()
                self._directRuntimeSetsByStorageKey.clear()
                self._directCanonicalSetsByAliasIdentity.clear()
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

    def _patchDirectSetLoad(self) -> None:
        if self._directSetLoadPatch is not None:
            return

        originalLoad = ScipionSet.load

        existingOwner = getattr(
            originalLoad,
            "_postgresqlOutputSetAdapter",
            None,
        )

        if (
                existingOwner is not None
                and existingOwner is not self
        ):
            raise RuntimeError(
                "Scipion Set.load() is already patched by "
                "another PostgreSQL output adapter."
            )

        adapter = self

        def load(runtimeSet):
            return adapter._loadDirectPostgresqlSet(
                originalLoad=originalLoad,
                runtimeSet=runtimeSet,
            )

        load._postgresqlOutputSetAdapter = self

        self._directSetLoadPatch = {
            "originalLoad": originalLoad,
            "patchedLoad": load,
        }

        ScipionSet.load = load

    def _restoreDirectSetLoad(self) -> None:
        patchInfo = self._directSetLoadPatch

        if patchInfo is None:
            return

        if ScipionSet.load is patchInfo["patchedLoad"]:
            ScipionSet.load = patchInfo["originalLoad"]

        self._directSetLoadPatch = None

    def _getDirectSetStorageKey(
            self,
            runtimeSet,
    ):
        mapperPath = getattr(
            runtimeSet,
            "_mapperPath",
            None,
        )

        if mapperPath is None or len(mapperPath) == 0:
            return None

        storagePath = str(
            mapperPath[0]
        ).strip()

        if not storagePath:
            return None

        getWorkingDir = getattr(
            self.protocol,
            "getWorkingDir",
            None,
        )

        if not callable(getWorkingDir):
            return None

        workingDir = str(
            getWorkingDir()
            or ""
        ).strip()

        if not workingDir:
            return None

        absoluteStoragePath = os.path.abspath(
            os.path.normpath(
                storagePath
            )
        )

        absoluteWorkingDir = os.path.abspath(
            os.path.normpath(
                workingDir
            )
        )

        try:
            commonPath = os.path.commonpath([
                absoluteStoragePath,
                absoluteWorkingDir,
            ])

        except ValueError:
            return None

        if commonPath != absoluteWorkingDir:
            return None

        prefix = (
            str(mapperPath[1]).strip()
            if len(mapperPath) > 1
            else ""
        )

        return (
            runtimeSet.__class__,
            absoluteStoragePath,
            prefix,
        )

    def _loadDirectPostgresqlSet(
            self,
            originalLoad,
            runtimeSet,
    ):
        compatibilityBuild = bool(
            getattr(
                runtimeSet,
                PostgresqlRuntimeSetSqliteMaterializer.COMPATIBILITY_BUILD_ATTRIBUTE,
                False,
            )
        )

        if compatibilityBuild:
            return originalLoad(runtimeSet)

        mapperPath = getattr(
            runtimeSet,
            "_mapperPath",
            None,
        )

        storagePath = (
            str(mapperPath[0]).strip()
            if mapperPath is not None and len(mapperPath)
            else ""
        )

        if (
                storagePath
                and PostgresqlRuntimeSetSqliteMaterializer.refreshManagedPath(
            storagePath
        )
        ):
            return originalLoad(runtimeSet)

        storageKey = self._getDirectSetStorageKey(
            runtimeSet
        )

        if storageKey is None:
            return originalLoad(
                runtimeSet
            )

        setClass = runtimeSet.__class__

        capability = (
            self.runtimeMapper
            .getPostgresqlOutputSetCapability(
                setClass
            )
        )

        if not capability.get("supported"):
            self._raiseUnsupportedOutputSet(
                setClass=setClass,
                creatorKind="direct-load",
                capability=capability,
            )

        with self._directSetLock:
            canonicalSet = (
                self
                ._directRuntimeSetsByStorageKey
                .get(
                    storageKey
                )
            )

            if canonicalSet is None:
                storagePath = storageKey[1]

                # Delete only a stale artifact from an older
                # execution. No SQLite file is opened or created.
                pwutils.cleanPath(
                    storagePath
                )

                canonicalSet = (
                    self
                    ._createPostgresqlRuntimeSet(
                        setClass=setClass,
                        constructorKwargs={},
                        creatorKind="direct-load",
                        creationMetadata={
                            "storagePath": storagePath,
                            "storagePrefix": storageKey[2],
                        },
                    )
                )

                self._directRuntimeSetsByStorageKey[
                    storageKey
                ] = canonicalSet

            runtimeAlias = (
                self.runtimeMapper
                .bindPostgresqlOutputSetAlias(
                    protocol=self.protocol,
                    runtimeSet=runtimeSet,
                    canonicalSet=canonicalSet,
                )
            )

            if runtimeAlias is not runtimeSet:
                raise RuntimeError(
                    "PostgreSQL direct Set binding replaced "
                    "constructor object identity. "
                    "setClass=%s storagePath=%s"
                    % (
                        setClass.__name__,
                        storageKey[1],
                    )
                )

            self._directCanonicalSetsByAliasIdentity[
                id(runtimeAlias)
            ] = canonicalSet

            return runtimeAlias

    def _getRegisteredPostgresqlOutputSet(
            self,
            outputName: str,
    ):
        outputName = str(
            outputName
        )

        runtimeSet = (
            self
            ._finalizedSetsByOutputName
            .get(
                outputName
            )
        )

        if runtimeSet is not None:
            return runtimeSet

        existingOutput = getattr(
            self.protocol,
            outputName,
            None,
        )

        if not self._isPostgresqlRuntimeOutputSet(
                existingOutput
        ):
            return None

        self._finalizedSetsByOutputName[
            outputName
        ] = existingOutput

        return existingOutput

    def _patchDeleteChild(self) -> None:
        originalDeleteChild = getattr(
            self.protocol,
            self.DELETE_CHILD_ATTRIBUTE,
            None,
        )

        if not callable(originalDeleteChild):
            return

        adapter = self

        def deleteChild(
                protocolSelf,
                key,
                child,
        ):
            outputName = str(
                key
            )

            existingOutput = (
                adapter
                ._getRegisteredPostgresqlOutputSet(
                    outputName
                )
            )

            if (
                    isinstance(
                        child,
                        ScipionSet,
                    )
                    and existingOutput is not None
            ):
                adapter._pendingOutputSetReplacements[
                    outputName
                ] = existingOutput

                return None

            return originalDeleteChild(
                key,
                child,
            )

        self._patchMethod(
            self.DELETE_CHILD_ATTRIBUTE,
            deleteChild,
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

    @staticmethod
    def _isPostgresqlRuntimeOutputSet(
            runtimeSet,
    ) -> bool:
        if not isinstance(
                runtimeSet,
                ScipionSet,
        ):
            return False

        checker = getattr(
            runtimeSet,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if not callable(checker):
            return False

        try:
            return bool(checker())
        except Exception:
            return False

    def _adoptDirectOutputSet(
            self,
            outputName: str,
            child,
    ):
        if not isinstance(child, ScipionSet):
            return child

        directCanonicalSet = (
            self
            ._directCanonicalSetsByAliasIdentity
            .pop(
                id(child),
                None,
            )
        )

        if directCanonicalSet is not None:
            self._pendingOutputMetadataSources[
                outputName
            ] = child

            self._pendingOutputSetReplacements.pop(
                outputName,
                None,
            )

            return directCanonicalSet

        existingOutput = (
            self
            ._pendingOutputSetReplacements
            .pop(
                outputName,
                None,
            )
        )

        if existingOutput is None:
            existingOutput = (
                self
                ._getRegisteredPostgresqlOutputSet(
                    outputName
                )
            )

        if existingOutput is child:
            return child

        if existingOutput is not None:
            legacyPath = None

            try:
                legacyPath = child.getFileName()
            except Exception:
                pass

            refreshedOutput = (
                self.runtimeMapper
                .replacePostgresqlOutputSetSnapshot(
                    protocol=self.protocol,
                    outputName=outputName,
                    runtimeSet=existingOutput,
                    sourceSet=child,
                )
            )

            if refreshedOutput is not existingOutput:
                raise RuntimeError(
                    "Repeated PostgreSQL output update "
                    "replaced runtime object identity. "
                    "outputName=%s"
                    % outputName
                )

            if legacyPath:
                pwutils.cleanPath(
                    legacyPath
                )
            self._finalizedSetsByOutputName[
                outputName
            ] = existingOutput

            return existingOutput

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

        legacyPath = None

        try:
            legacyPath = child.getFileName()
        except Exception:
            pass

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

        if legacyPath:
            pwutils.cleanPath(
                legacyPath
            )

        return child

    def _raiseUnsupportedOutputSet(self, setClass, creatorKind, capability):
        setClassName = getattr(setClass, "__name__", str(setClass))

        raise NotImplementedError(
            "Declared output Set cannot be stored natively in PostgreSQL. "
            "projectId=%s protocolId=%s protocolClass=%s "
            "setClass=%s creator=%s reason=%s"
            % (
                self.projectId,
                self.protocol.getObjId(),
                self.protocol.__class__.__name__,
                setClassName,
                creatorKind,
                capability.get("reason"),
            )
        )

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

        if not capability.get("supported"):
            self._raiseUnsupportedOutputSet(setClass=setClass,
                                            creatorKind="class-create",
                                            capability=capability)

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
        capability = (
            self.runtimeMapper
            .getPostgresqlOutputSetCapability(
                setClass
            )
        )

        if not capability.get("supported"):
            self._raiseUnsupportedOutputSet(
                setClass=setClass,
                creatorKind=creatorKind,
                capability=capability,
            )

        return self._createPostgresqlRuntimeSet(
            setClass=setClass,
            constructorKwargs=constructorKwargs,
            creatorKind=creatorKind,
            creationMetadata={
                "template": str(template),
                "suffix": str(suffix),
            },
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

        metadataSource = (
            self
            ._pendingOutputMetadataSources
            .pop(
                outputName,
                None,
            )
        )

        entry = self._createdSets.get(
            id(child)
        )

        if entry is None:
            return

        alreadyFinalized = bool(
            entry["finalized"]
        )

        if (
                alreadyFinalized
                and metadataSource is None
        ):
            return

        report = (
            self.runtimeMapper
            .finalizePostgresqlOutputSet(
                protocol=self.protocol,
                outputName=outputName,
                runtimeSet=child,
                metadataSource=metadataSource,
            )
        )

        entry["finalized"] = True
        entry["outputName"] = outputName
        entry["report"] = report

        self._finalizedSetsByOutputName[
            outputName
        ] = child

        self._pendingOutputSetReplacements.pop(
            outputName,
            None,
        )

        if alreadyFinalized:
            logger.debug(
                "Refreshed native PostgreSQL output Set metadata. "
                "projectId=%s protocolId=%s "
                "runtimeObjectId=%s outputName=%s "
                "setId=%s itemsCount=%s",
                self.projectId,
                self.protocol.getObjId(),
                child.getObjId(),
                outputName,
                report.get("setId"),
                (
                    report.get("properties")
                    or {}
                ).get("itemsCount"),
            )

            return

        logger.info(
            "Finalized native PostgreSQL output Set. "
            "projectId=%s protocolId=%s "
            "runtimeObjectId=%s outputName=%s "
            "setId=%s",
            self.projectId,
            self.protocol.getObjId(),
            child.getObjId(),
            outputName,
            report.get("setId"),
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