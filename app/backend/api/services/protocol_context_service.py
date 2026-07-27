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
from typing import Any, Callable, Dict

from pyworkflow.protocol import (
    STATUS_LAUNCHED,
    STATUS_RUNNING,
    STATUS_SCHEDULED,
)

from app.backend.api.services.protocol_form_serializer import (
    ProtocolFormSerializer,
)
from app.backend.api.services.protocol_wizard_service import (
    findProtocolWizardsWeb,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)
from app.backend.runtime.protocol_output_persistence_service import (
    RuntimeProtocolOutputPersistenceService,
)


class ProtocolContextService:
    """Build the web context for a Scipion protocol."""

    def buildContext(
            self,
            *,
            project,
            projectId: int,
            protocol,
            mapper=None,
            getResourceLogoCallback: Callable,
            getProtocolColorCallback: Callable,
            buildProtocolThumbnailUrlCallback: Callable,
            buildProtocolThumbnailRebuildUrlCallback: Callable,
            findViewersWebCallback: Callable,
            usingPostgresqlRuntime: bool,
            getScipionObjectIdCallback: Callable,
            resolvePostgresqlProtocolDbIdCallback: Callable,
            splitPointerValueCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Build the complete web context for the selected protocol.

        This operation only reads and serializes protocol information.
        It does not persist protocols, modify parent protocols or mutate
        protocol outputs.
        """
        headerParams = [
            "runName",
            "_objComment",
            "_useQueue",
            "_prerequisites",
            "gpuList",
            "numberOfThreads",
            "numberOfMpi",
        ]

        package = protocol.getClassPackage()
        hasExpert = protocol.hasExpert()

        if hasExpert:
            headerParams.append("expertLevel")

        logoPath = ""
        packageLogoPath = getattr(
            package,
            "_logo",
            "",
        )

        if packageLogoPath != "":
            logoPath = getResourceLogoCallback(
                packageLogoPath
            )

        protocolName = str(protocol)

        if protocol.runName.get() is None:
            runName = protocol.getRunName()
        else:
            runName = protocol.runName.get()

        protocolStatus = protocol.getStatus()
        protocolClassName = protocol.getClassName()
        hosts = project.getHostNames()

        context = {}

        info = {
            "protocolId": protocol.getObjId(),
            "label": protocolName,
            "runName": runName,
            "status": protocolStatus,
            "expertLevel": hasExpert,
            "packageLogo": logoPath,
            "color": getProtocolColorCallback(
                protocolStatus
            ),
            "hosts": hosts,
            "projectId": projectId,
            "protocolClassName": protocolClassName,
            "thumbnailUrl": (
                buildProtocolThumbnailUrlCallback(
                    projectId,
                    int(protocol.getObjId()),
                )
                if protocol.hasObjId()
                else None
            ),
            "thumbnailRebuildUrl": (
                buildProtocolThumbnailRebuildUrlCallback(
                    projectId,
                    int(protocol.getObjId()),
                )
                if protocol.hasObjId()
                else None
            ),
        }

        references = protocol.citations()
        protocolHelp = protocol.getHelpText() + "\n\n"

        if references != ["No references provided"]:
            for reference in references:
                protocolHelp += reference + "\n"

        form = {
            "references": references,
            "help": protocolHelp,
        }

        wizards = findProtocolWizardsWeb(
            project,
            protocol,
        )

        # Preserve the current viewer discovery call even though its
        # result is not currently included in the returned context.
        viewers = findViewersWebCallback(protocol)

        protocolFormSerializer = ProtocolFormSerializer()

        info["inputs"] = (
            protocolFormSerializer
            .serializeProtocolInputs(
                protocol=protocol,
                mapper=mapper,
                projectId=projectId,
                usingPostgresqlRuntime=usingPostgresqlRuntime,
                getScipionObjectIdCallback=getScipionObjectIdCallback,
                resolvePostgresqlProtocolDbIdCallback=resolvePostgresqlProtocolDbIdCallback,
                splitPointerValueCallback=splitPointerValueCallback,
            )
        )

        persistedOutputs = {}

        if (
                usingPostgresqlRuntime
                and mapper is not None
        ):
            protocolId = (
                getScipionObjectIdCallback(
                    protocol
                )
            )

            if protocolId is not None:
                persistedOutputs = (
                    RuntimeProtocolOutputPersistenceService()
                    .loadPersistedProtocolOutputs(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=protocolId,
                    )
                )

        info["outputs"] = (
            protocolFormSerializer
            .serializeProtocolOutputs(
                protocol=protocol,
                protocolName=protocolName,
                persistedOutputs=(
                    persistedOutputs
                ),
            )
        )

        paramsData, paramsValue = (
            protocolFormSerializer
            .serializeProtocolSections(
                protocol=protocol,
                wizards=wizards,
                mapper=mapper,
                projectId=projectId,
                headerParams=headerParams,
                runName=runName,
                usingPostgresqlRuntime=usingPostgresqlRuntime,
                getScipionObjectIdCallback=getScipionObjectIdCallback,
                resolvePostgresqlProtocolDbIdCallback=resolvePostgresqlProtocolDbIdCallback,
                splitPointerValueCallback=splitPointerValueCallback,
            )
        )

        try:
            paramsValue = dict(paramsValue or {})
        except Exception:
            paramsValue = {}

        runtimeStatusSyncService = (
            RuntimeProtocolStatusSyncService()
        )

        paramsValue[
            runtimeStatusSyncService.RUNTIME_METADATA_KEY
        ] = runtimeStatusSyncService.buildRuntimeMetadata(
            protocol
        )

        info["executeMode"] = {
            "launch": {
                "label": "Launch",
                "help": (
                    "Start the protocol from its "
                    "current configuration"
                ),
            },
            "restart": {
                "label": "Restart",
                "help": (
                    "Restart the protocol execution from scratch "
                    "(keeps current params)."
                ),
            },
        }

        emptyInput, openSetPointer, emptyPointers = (
            protocol.getInputStatus()
        )

        if openSetPointer or emptyPointers:
            info["executeMode"] = {
                "schedule": {
                    "label": "Schedule",
                    "help": (
                        "Schedule the protocol from its "
                        "current configuration"
                    ),
                },
            }

        if protocolStatus in (
                STATUS_LAUNCHED,
                STATUS_RUNNING,
                STATUS_SCHEDULED,
        ):
            info["executeMode"] = {
                "stop": {
                    "label": "Stop",
                    "help": "Stop the protocol",
                },
            }

        form["sections"] = paramsData

        context["info"] = info
        context["form"] = form
        context["values"] = paramsValue

        return context