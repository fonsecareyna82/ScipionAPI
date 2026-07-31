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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import copy
import threading
from typing import Any, Callable, Dict

from app.backend.api.services.plugins_revision import getPluginsRevision
from app.backend.api.services.json_subprocess_runner import JsonSubprocessRunner

_newProtocolLock = threading.Lock()
_newProtocolCache: Dict[str, Dict[str, Any]] = {}
_lastNewProtocolRevision = -1


def _invalidateNewProtocolCacheIfNeeded() -> int:
    global _lastNewProtocolRevision

    revision = int(getPluginsRevision() or 0)

    with _newProtocolLock:
        if revision != _lastNewProtocolRevision:
            _newProtocolCache.clear()
            _lastNewProtocolRevision = revision

    return revision


class ProtocolService:
    """Orchestrate protocol retrieval and context operations."""

    def getNewProtocolParams(
            self,
            *,
            currentProject,
            projectId: int,
            protocolClassName: str,
            buildProtocolContextCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Return the web context for a new protocol instance.

        The context is cached until the installed plugins revision changes.
        """
        _invalidateNewProtocolCacheIfNeeded()

        cacheKey = "%s:%s" % (
            str(projectId),
            str(protocolClassName),
        )

        with _newProtocolLock:
            cached = _newProtocolCache.get(cacheKey)

            if cached is not None:
                return copy.deepcopy(cached)

        protocolClass = (
            currentProject
            .getDomain()
            .getProtocols()
            .get(protocolClassName)
        )

        if protocolClass:
            protocol = currentProject.newProtocol(
                protocolClass
            )

            currentProject._fixProtParamsConfiguration(
                protocol
            )

            context = buildProtocolContextCallback(
                projectId,
                protocol,
            )

        else:
            context = self._buildNewProtocolContextInSubprocess(
                currentProject=currentProject,
                projectId=projectId,
                protocolClassName=protocolClassName,
            )

        with _newProtocolLock:
            _newProtocolCache[cacheKey] = context

        return copy.deepcopy(context)

    def _buildNewProtocolContextInSubprocess(
            self,
            *,
            currentProject,
            projectId: int,
            protocolClassName: str,
    ) -> Dict[str, Any]:
        """
        Build a new protocol context in a clean process when the current
        process domain does not yet contain the requested protocol class.
        """
        projectPath = None

        for attrName in ("path", "_path"):
            value = getattr(
                currentProject,
                attrName,
                None,
            )

            if value:
                projectPath = value
                break

        if not projectPath:
            getPath = getattr(
                currentProject,
                "getPath",
                None,
            )

            if callable(getPath):
                projectPath = getPath()

        if not projectPath:
            raise RuntimeError(
                "Cannot resolve currentProject path "
                "for subprocess protocol build"
            )

        code = """
    import contextlib
    import os
    import sys

    with contextlib.redirect_stdout(sys.stderr):
        from app.backend.database import getMapper
        from app.backend.api.services.project_service import ProjectService

        projectPath = os.environ["SCIPIONWEB_PROJECT_PATH"]
        projectId = int(os.environ["SCIPIONWEB_PROJECT_ID"])
        protocolClassName = os.environ["SCIPIONWEB_PROTOCOL_CLASS"]

        mapper = getMapper()
        projectService = ProjectService()
        project = None

        try:
            project = projectService._loadPostgresqlRuntimeProject(
                mapper=mapper,
                projectId=projectId,
                projectPath=projectPath,
            )

            domain = project.getDomain()
            protocolClass = domain.getProtocols().get(
                protocolClassName
            )

            if protocolClass is None:
                raise RuntimeError(
                    f"Protocol class not found: {protocolClassName}"
                )

            protocol = project.newProtocol(
                protocolClass
            )
            project._fixProtParamsConfiguration(
                protocol
            )

            _scipionPayload = projectService._buildProtocolContext(
                projectId,
                protocol,
            )

        finally:
            if project is not None:
                try:
                    project.closeMapper()
                except Exception:
                    pass

            try:
                mapper.db.close()
            except Exception:
                pass
    """

        jsonSubprocessRunner = JsonSubprocessRunner()

        return jsonSubprocessRunner.run(
            code=code,
            operationName="Build new protocol context",
            extraEnv={
                "SCIPIONWEB_PROJECT_PATH": projectPath,
                "SCIPIONWEB_PROJECT_ID": projectId,
                "SCIPIONWEB_PROTOCOL_CLASS": protocolClassName,
            },
        )

    def getProtocolParams(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            usingPostgresqlRuntime: bool,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            getScipionProtocolForRuntimeCallback: Callable,
            fixProtocolParamsConfigurationCallback: Callable,
            buildProtocolContextCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Return the web context of an existing protocol.

        PostgreSQL-runtime protocols reuse the context built from the real
        run.db protocol, preserving runtime outputs and avoiding a second
        protocol reconstruction.
        """
        if usingPostgresqlRuntime:
            syncResult = (
                syncPostgresqlRuntimeProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                    registerOutputs=False,
                    syncRelations=False,
                    returnProtocolContext=True,
                )
            )

            return syncResult["protocolContext"]

        protocol = getScipionProtocolForRuntimeCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol.getPlugin()
        fixProtocolParamsConfigurationCallback(protocol)

        return buildProtocolContextCallback(
            projectId,
            protocol,
            mapper,
        )
