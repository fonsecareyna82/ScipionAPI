from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Iterator, Any
from datetime import datetime, timezone
from fastapi import HTTPException

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse, Response

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _makeRouterModule(moduleName: str) -> types.ModuleType:
    # makeRouterModule
    module = types.ModuleType(moduleName)
    router = APIRouter()
    module.router = router
    return module


def _installStubModules() -> dict[str, types.ModuleType | None]:
    # installStubModules
    moduleNames = [
        "app.backend.bootstrap",
        "app.backend.api.services.environment",
        "app.backend.utils.error_handlers",
        "app.backend.api.routers.project_router",
        "app.backend.api.routers.protocol_router",
        "app.backend.api.routers.plugin_router",
        "app.backend.api.routers.auth_router",
        "app.backend.api.routers.user_router",
        "app.backend.api.routers.settings_router",
    ]

    previousModules: dict[str, types.ModuleType | None] = {
        name: sys.modules.get(name) for name in moduleNames
    }

    bootstrapModule = types.ModuleType("app.backend.bootstrap")
    bootstrapModule.bootstrapEnv = lambda: None
    sys.modules["app.backend.bootstrap"] = bootstrapModule

    environmentModule = types.ModuleType("app.backend.api.services.environment")
    environmentModule.prepareEnvironment = lambda: None
    sys.modules["app.backend.api.services.environment"] = environmentModule

    errorHandlersModule = types.ModuleType("app.backend.utils.error_handlers")
    errorHandlersModule.registerAllErrorHandlers = lambda app: None
    sys.modules["app.backend.utils.error_handlers"] = errorHandlersModule

    sys.modules["app.backend.api.routers.project_router"] = _makeRouterModule(
        "app.backend.api.routers.project_router"
    )
    sys.modules["app.backend.api.routers.protocol_router"] = _makeRouterModule(
        "app.backend.api.routers.protocol_router"
    )
    sys.modules["app.backend.api.routers.plugin_router"] = _makeRouterModule(
        "app.backend.api.routers.plugin_router"
    )
    sys.modules["app.backend.api.routers.auth_router"] = _makeRouterModule(
        "app.backend.api.routers.auth_router"
    )
    sys.modules["app.backend.api.routers.user_router"] = _makeRouterModule(
        "app.backend.api.routers.user_router"
    )
    sys.modules["app.backend.api.routers.settings_router"] = _makeRouterModule(
        "app.backend.api.routers.settings_router"
    )

    return previousModules


def _restoreStubModules(previousModules: dict[str, types.ModuleType | None]) -> None:
    # restoreStubModules
    for moduleName, previousModule in previousModules.items():
        if previousModule is None:
            sys.modules.pop(moduleName, None)
        else:
            sys.modules[moduleName] = previousModule


def _importMainModule():
    # importMainModule
    sys.modules.pop("app.backend.main", None)
    return importlib.import_module("app.backend.main")


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def makeProjectOut(projectId: int = 1, name: str = "Demo Project", **overrides):
    # makeProjectOut
    payload = {
        "id": projectId,
        "name": name,
        "description": "Demo description",
        "status": "active",
        "createdAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc),
        "protocolsCount": 0,
        "diskUsage": "0.0 GB",
        "isOwner": True,
        "isShared": False,
        "permission": "full",
        "projectOwnerId": 1,
    }
    payload.update(overrides)
    return payload


class FakeProjectService:
    # fakeProjectService
    def __init__(self):
        self.listProjectWorkflowsResult = [{"id": "wf-1", "name": "Workflow 1"}]
        self.listProjectWorkflowsError = None

        self.projectByIdResult = makeProjectOut()
        self.lastGetProjectByIdCall = None

        self.projectDbRowResult = makeProjectOut()
        self.lastGetProjectDbRowCall = None
        self.lastGetProtocolsCall = None

        self.protocolsResult = [{"id": 11, "name": "Prot A"}]

        self.logChannelsResult = [{"id": "stdout", "label": "Output"}]
        self.pollLogsResult = {
            "channels": {
                "stdout": {"content": "hello", "offset": 5, "truncated": False},
            }
        }
        self.lastPollLogsCall = None

        self.resolveViewerResult = {"handled": False}
        self.resolveViewerError = None
        self.lastResolveViewerCall = None

        self.runMetadataTableActionResult = {"success": True, "message": "Subset created"}
        self.lastRunMetadataTableActionCall = None

        self.exportMetadataTableResponse = PlainTextResponse(
            "id,name\n1,row1\n",
            media_type="text/csv",
        )
        self.lastExportMetadataTableCall = None

        self.consistencyResult = {
            "ok": True,
            "projectId": 1,
            "summary": {
                "runtimeProtocols": 2,
                "postgresqlProtocols": 2,
                "runtimeDependencies": 1,
                "postgresqlDependencies": 1,
                "issues": 0,
            },
            "issues": {
                "missingProtocols": [],
                "extraProtocols": [],
                "statusMismatches": [],
                "missingDependencies": [],
                "extraDependencies": [],
            },
        }
        self.lastValidateProjectPostgresqlConsistencyCall = None

        self.metadataTablesResult = [
            {
                "name": "objects",
                "alias": "Particles",
                "rowCount": 1,
                "hasColumnId": True,
            }
        ]

        self.lastListOutputMetadataTablesCall = None

        self.metadataTableSchemaResult = {
            "name": "objects",
            "alias": "Particles",
            "hasColumnId": True,
            "actions": ["Particle"],
            "columns": [],
        }
        self.lastGetMetadataTableSchemaCall = None

        self.metadataTablePageResult = {
            "pageNumber": 1,
            "pageSize": 20,
            "totalRows": 1,
            "rows": [
                {
                    "id": 1,
                    "values": ["row-1"],
                }
            ],
        }
        self.metadataTableWindowResult = {
            "offset": 10,
            "limit": 25,
            "totalRows": 1,
            "rows": [{"id": 1, "values": ["row-1"]}],
        }
        self.lastGetMetadataTableWindowCall = None
        self.lastGetMetadataTablePageCall = None

        self.renderMetadataImageCellResponse = PlainTextResponse(
            "image-bytes",
            media_type="image/png",
        )
        self.lastRenderMetadataImageCellCall = None

        self.listProjectsResult = [makeProjectOut()]
        self.lastListProjectsCall = None

        self.createProjectResult = makeProjectOut(projectId=2, name="Created Project")
        self.lastCreateProjectCall = None

        self.updateProjectResult = makeProjectOut(projectId=1, name="Updated Project",
                                                  description="Updated description")
        self.lastUpdateProjectCall = None

        self.deleteProjectResult = {"success": True}
        self.lastDeleteProjectCall = None

        self.shareProjectResult = {"success": True, "sharedUserIds": [2, 3]}
        self.lastShareProjectCall = None

        self.lastRevokeProjectShareCall = None

        self.projectSharesResult = [
            {"userId": 2, "permission": "read"},
            {"userId": 3, "permission": "full"},
        ]
        self.lastListProjectSharesCall = None

        self.applyWorkflowResult = {"success": True, "workflowId": "wf-1"}
        self.applyWorkflowError = None
        self.lastApplyWorkflowCall = None

        self.syncProjectGraphAfterMutationError = None
        self.lastSyncProjectGraphAfterMutationCall = None

        self.protocolParamsResult = {
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        }
        self.lastGetProtocolParamsCall = None

        self.newProtocolParamsResult = {
            "protocolClassName": "ProtClass",
            "params": {"x": 2},
        }
        self.lastGetNewProtocolParamsCall = None

        self.launchProtocolError = None
        self.lastLaunchProtocolCall = None

        self.saveProtocolError = None
        self.saveProtocolResult = ({"protocolId": "10"}, [])
        self.lastSaveProtocolCall = None

        self.nextProtocolSuggestionsResult = [{"id": "next-1", "name": "Next protocol"}]
        self.nextProtocolSuggestionsError = None
        self.lastGetNextProtocolSuggestionsCall = None

        self.renameProtocolError = None
        self.lastRenameProtocolCall = None

        self.duplicateProtocolError = None
        self.duplicateProtocolResult = {
            "status": 0,
            "errors": [],
            "duplicated": [],
        }
        self.lastDuplicateProtocolCall = None

        self.deleteProtocolError = None
        self.lastDeleteProtocolCall = None

        self.restartProtocolAllError = None
        self.restartProtocolAllResult = []
        self.lastRestartProtocolAllCall = None

        self.continueProtocolAllError = None
        self.lastContinueProtocolAllCall = None

        self.resetProtocolFromError = None
        self.lastResetProtocolFromCall = None

        self.stopProtocolError = None
        self.lastStopProtocolCall = None
        self.volumeItemsResult = [
            {
                "id": "vol-1",
                "label": "Volume 1",
                "fileName": "/tmp/volume.mrc",
            }
        ]
        self.lastListOutputVolumesCall = None

        self.volumeInfoResult = {
            "id": "vol-1",
            "label": "Volume 1",
            "dimensions": [64, 64, 64],
        }
        self.lastGetVolumeInfoCall = None

        self.volumeHistogramResult = {
            "binEdges": [0.0, 1.0],
            "counts": [10],
        }
        self.lastGetVolumeHistogramCall = None

        self.tiltSeriesResult = [
            {
                "tiltSeriesId": "TS_001",
                "label": "TS_001",
                "nViews": 3,
            }
        ]
        self.lastListOutputTiltSeriesCall = None

        self.tiltSeriesFramesResult = {
            "tiltSeriesId": "TS_001",
            "label": "TS_001",
            "frames": [
                {"index": 0, "tiltAngle": -1.0},
                {"index": 1, "tiltAngle": 0.0},
            ],
        }
        self.lastGetTiltSeriesFramesCall = None

        self.ctftomoSeriesResult = [
            {
                "tiltSeriesId": "TS_001",
                "label": "TS_001",
                "nViews": 3,
            }
        ]
        self.lastListOutputCtftomoSeriesCall = None

        self.ctftomoSeriesViewsResult = {
            "tiltSeriesId": "TS_001",
            "label": "TS_001",
            "frames": [
                {"index": 0, "defocusU": 10000.0},
                {"index": 1, "defocusU": 11000.0},
            ],
        }
        self.lastGetCtftomoSeriesViewsCall = None

        self.coords3dTomogramsResult = [
            {
                "id": "tomo-1",
                "name": "Tomogram 1",
                "label": "tomo-1",
                "dims": [64, 64, 64],
                "voxelSize": [1.0, 1.0, 1.0],
            }
        ]
        self.lastListCoordinates3dTomogramsCall = None

        self.coords3dPointsResult = [
            {
                "id": 1,
                "x": 10.0,
                "y": 20.0,
                "z": 30.0,
                "tomoId": "tomo-1",
            }
        ]
        self.lastGetCoordinates3dPointsCall = None

        self.integratedAnalyzeContextResult = {
            "root": {
                "projectId": 1,
                "protocolId": 2,
                "outputName": "out",
            },
            "links": {},
            "summaries": {},
            "relations": {"items": []},
        }
        self.lastGetIntegratedAnalyzeContextCall = None

        self.projectTagsResult = [
            {
                "id": "tag-1",
                "title": "Good",
                "description": "Good protocols",
                "color": "#00ff00",
            }
        ]
        self.lastListProjectTagsCall = None

        self.createProjectTagResult = {
            "id": "tag-2",
            "title": "New tag",
            "description": None,
            "color": "#ff0000",
        }
        self.lastCreateProjectTagCall = None

        self.updateProjectTagResult = {
            "id": "tag-1",
            "title": "Updated tag",
            "description": "Updated",
            "color": "#0000ff",
        }
        self.lastUpdateProjectTagCall = None

        self.deleteProjectTagResult = True
        self.lastDeleteProjectTagCall = None

        self.protocolTagsResult = {
            "protocolId": "2",
            "protocolDbId": 22,
            "tagIds": ["tag-1"],
        }
        self.lastListProtocolTagsCall = None

        self.setProtocolTagsResult = {
            "protocolId": "2",
            "protocolDbId": 22,
            "tagIds": ["tag-1", "tag-2"],
        }
        self.lastSetProtocolTagsCall = None

        self.contextMenuVisibilityResult = {
            "open": True,
            "delete": True,
            "manageTags": True,
        }
        self.lastGetContextMenuVisibilityPolicyCall = None

        self.fscRowsResult = {
            "threshold": 0.143,
            "curves": [
                {
                    "label": "FSC 1",
                    "resolution": 3.2,
                    "x": [0.01, 0.02],
                    "y": [0.95, 0.87],
                }
            ],
        }
        self.lastGetFscRowsCall = None

        self.projectEffectiveSettingsResult = {
            "projectId": 1,
            "settings": {
                "user": {"protocolView": "tree"},
                "instance": {"executionMode": "local"},
                "host": {"queueSystem": "slurm"},
            },
        }
        self.lastGetProjectEffectiveSettingsCall = None

        self.coords3dSliceResponse = Response(
            content=b"slice-bytes",
            media_type="image/png",
        )
        self.lastRenderCoords3dTomogramSliceCall = None

    def listProjectWorkflows(self):
        if self.listProjectWorkflowsError is not None:
            raise self.listProjectWorkflowsError
        return self.listProjectWorkflowsResult

    def getProjectById(
            self,
            mapper,
            projectId,
            currentUser,
            refresh=False,
            checkPid=False,
            validateConsistency=False,
            failOnConsistencyError=False,
    ):
        self.lastGetProjectByIdCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "refresh": refresh,
            "checkPid": checkPid,
            "validateConsistency": validateConsistency,
            "failOnConsistencyError": failOnConsistencyError,
        }
        return self.projectByIdResult

    def getProjectDbRow(self, mapper, projectId, currentUser):
        self.lastGetProjectDbRowCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectDbRowResult

    def validateProjectPostgresqlConsistency(
            self,
            mapper,
            projectId,
            currentUser,
            refresh=True,
            checkPid=True,
    ):
        self.lastValidateProjectPostgresqlConsistencyCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "refresh": refresh,
            "checkPid": checkPid,
        }
        return self.consistencyResult

    def listProjectLogChannelsService(self, projectId, protocolId):
        return self.logChannelsResult

    def listProtocolLogChannelsService(self, projectId, protocolId, mapper=None):
        return self.logChannelsResult

    def pollProtocolLogsService(self, projectId, protocolId, offsets, maxBytes, maxLines, mapper=None):
        self.lastPollLogsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "offsets": dict(offsets),
            "maxBytes": maxBytes,
            "maxLines": maxLines,
            "mapper": mapper,
        }
        return self.pollLogsResult

    def resolveAnalyzeViewerDecision(self, projectId, protocolId, ctx, mapper=None):
        self.lastResolveViewerCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "ctx": ctx,
            "mapper": mapper
        }
        if self.resolveViewerError is not None:
            raise self.resolveViewerError
        return self.resolveViewerResult

    def listOutputMetadataTablesService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper,
    ):
        self.lastListOutputMetadataTablesCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.metadataTablesResult

    def getMetadataTableSchemaService(
            self,
            projectId,
            protocolId,
            outputName,
            tableName,
            mapper,
    ):
        self.lastGetMetadataTableSchemaCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tableName": tableName,
            "mapper": mapper,
        }
        return self.metadataTableSchemaResult

    def getMetadataTablePageService(
            self,
            projectId,
            protocolId,
            outputName,
            tableName,
            page,
            pageSize,
            sortBy,
            asc,
            selectionOnly,
            mapper,
    ):
        self.lastGetMetadataTablePageCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tableName": tableName,
            "page": page,
            "pageSize": pageSize,
            "sortBy": sortBy,
            "asc": asc,
            "selectionOnly": selectionOnly,
            "mapper": mapper,
        }
        return self.metadataTablePageResult

    def getMetadataTableWindowService(
            self,
            projectId,
            protocolId,
            outputName,
            tableName,
            offset,
            limit,
            selectionOnly,
            sortBy,
            asc,
            mapper,
    ):
        self.lastGetMetadataTableWindowCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tableName": tableName,
            "offset": offset,
            "limit": limit,
            "selectionOnly": selectionOnly,
            "sortBy": sortBy,
            "asc": asc,
            "mapper": mapper,
        }
        return self.metadataTableWindowResult

    def renderMetadataImageCellService(
            self,
            projectId,
            protocolId,
            outputName,
            tableName,
            rowId,
            rowIndex,
            columnName,
            size,
            applyTransform,
            inline,
            fmt,
            mapper,
    ):
        self.lastRenderMetadataImageCellCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tableName": tableName,
            "rowId": rowId,
            "rowIndex": rowIndex,
            "columnName": columnName,
            "size": size,
            "applyTransform": applyTransform,
            "inline": inline,
            "fmt": fmt,
            "mapper": mapper,
        }
        return self.renderMetadataImageCellResponse

    def runMetadataTableActionService(
            self,
            projectId,
            protocolId,
            outputName,
            tableName,
            action,
            subsetName,
            ids,
            currentUser,
            mapper,
    ):
        self.lastRunMetadataTableActionCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tableName": tableName,
            "action": action,
            "subsetName": subsetName,
            "ids": ids,
            "currentUser": currentUser,
            "mapper": mapper,
        }
        return self.runMetadataTableActionResult

    def exportMetadataTableService(
            self,
            projectId,
            protocolId,
            outputName,
            tableName,
            fmt,
            selectionOnly,
            ids,
            mapper,
    ):
        self.lastExportMetadataTableCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tableName": tableName,
            "fmt": fmt,
            "selectionOnly": selectionOnly,
            "ids": ids,
            "mapper": mapper,
        }
        return self.exportMetadataTableResponse

    def listProjects(self, mapper, currentUser):
        self.lastListProjectsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
        }
        return self.listProjectsResult

    def createProject(self, mapper, projectData, currentUser):
        self.lastCreateProjectCall = {
            "mapper": mapper,
            "projectData": projectData,
            "currentUser": currentUser,
        }
        return self.createProjectResult

    def updateProject(self, mapper, projectId, currentUser, projectData):
        self.lastUpdateProjectCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "projectData": projectData,
        }
        return self.updateProjectResult

    def deleteProject(self, mapper, currentUser, projectId):
        self.lastDeleteProjectCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "projectId": projectId,
        }
        return self.deleteProjectResult

    def shareProjectWithUser(self, mapper, projectId, currentUser, targetUserIds, permission):
        self.lastShareProjectCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "targetUserIds": targetUserIds,
            "permission": permission,
        }
        return self.shareProjectResult

    def revokeProjectShareForUser(self, mapper, projectId, currentUser, targetUserId):
        self.lastRevokeProjectShareCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "targetUserId": targetUserId,
        }

    def listProjectShares(self, mapper, projectId, currentUser):
        self.lastListProjectSharesCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectSharesResult

    def getProtocols(self, mapper, projectId, currentUser):
        self.lastGetProtocolsCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.protocolsResult

    def syncProjectGraphAfterMutation(self, mapper, projectId, actionLabel, refresh=True, checkPid=True):
        self.lastSyncProjectGraphAfterMutationCall = {
            "mapper": mapper,
            "projectId": projectId,
            "actionLabel": actionLabel,
            "refresh": refresh,
            "checkPid": checkPid,
        }
        if self.syncProjectGraphAfterMutationError is not None:
            raise self.syncProjectGraphAfterMutationError
        return {"protocols": 1, "dependencies": 0}

    def applyWorkflowToProject(self, mapper, projectId, workflowId, currentUser):
        self.lastApplyWorkflowCall = {
            "mapper": mapper,
            "projectId": projectId,
            "workflowId": workflowId,
            "currentUser": currentUser,
        }
        if self.applyWorkflowError is not None:
            raise self.applyWorkflowError
        return self.applyWorkflowResult

    def getProtocolParams(self, projectId, protocolId, mapper=None):
        self.lastGetProtocolParamsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "mapper": mapper,
        }
        return self.protocolParamsResult

    def getNewProtocolParams(self, projectId, protClassName):
        self.lastGetNewProtocolParamsCall = {
            "projectId": projectId,
            "protClassName": protClassName,
        }
        return self.newProtocolParamsResult

    def launchProtocol(self, mapper, projectId, protocolId, protocolClassName, params, executeMode):
        self.lastLaunchProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "protocolClassName": protocolClassName,
            "params": params,
            "executeMode": executeMode,
        }
        if self.launchProtocolError is not None:
            raise self.launchProtocolError

    def saveProtocol(self, mapper, projectId, protocolId, protocolClassName, params):
        self.lastSaveProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "protocolClassName": protocolClassName,
            "params": params,
        }
        if self.saveProtocolError is not None:
            raise self.saveProtocolError
        return self.saveProtocolResult

    def getNextProtocolSuggestions(self, protocolId, mapper=None, projectId=None):
        self.lastGetNextProtocolSuggestionsCall = {
            "protocolId": protocolId,
            "mapper": mapper,
            "projectId": projectId,
        }
        if self.nextProtocolSuggestionsError is not None:
            raise self.nextProtocolSuggestionsError
        return self.nextProtocolSuggestionsResult

    def renameProtocol(self, mapper, projectId, protocolId, newName, newComment=""):
        self.lastRenameProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "newName": newName,
            "newComment": newComment,
        }
        if self.renameProtocolError is not None:
            raise self.renameProtocolError

    def duplicateProtocol(self, mapper, projectId, items):
        self.lastDuplicateProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "items": items,
        }
        if self.duplicateProtocolError is not None:
            raise self.duplicateProtocolError
        return self.duplicateProtocolResult

    def deleteProtocol(self, mapper, projectId, protocolIds):
        self.lastDeleteProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolIds": protocolIds,
        }
        if self.deleteProtocolError is not None:
            raise self.deleteProtocolError

    def restartProtocolAll(self, mapper, projectId, protocolId):
        self.lastRestartProtocolAllCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        }
        if self.restartProtocolAllError is not None:
            raise self.restartProtocolAllError
        return self.restartProtocolAllResult

    def continueProtocolAll(self, mapper, projectId, protocolId, currentUser):
        self.lastContinueProtocolAllCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "currentUser": currentUser,
        }
        if self.continueProtocolAllError is not None:
            raise self.continueProtocolAllError

    def resetProtocolFrom(self, mapper, projectId, protocolId):
        self.lastResetProtocolFromCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        }
        if self.resetProtocolFromError is not None:
            raise self.resetProtocolFromError

    def stopProtocol(self, mapper, projectId, protocolIds):
        self.lastStopProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolIds": protocolIds,
        }
        if self.stopProtocolError is not None:
            raise self.stopProtocolError

    def listOutputVolumesService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper=None,
    ):
        self.lastListOutputVolumesCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.volumeItemsResult

    def getVolumeInfoService(
            self,
            projectId,
            protocolId,
            outputName,
            volumeId,
            mapper=None,
    ):
        self.lastGetVolumeInfoCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "volumeId": volumeId,
            "mapper": mapper,
        }
        return self.volumeInfoResult

    def getVolumeHistogramService(
            self,
            projectId,
            protocolId,
            outputName,
            volumeId,
            bins=128,
            mapper=None,
    ):
        self.lastGetVolumeHistogramCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "volumeId": volumeId,
            "bins": bins,
            "mapper": mapper,
        }
        return self.volumeHistogramResult

    def listOutputTiltSeriesService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper=None,
    ):
        self.lastListOutputTiltSeriesCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.tiltSeriesResult

    def getTiltSeriesFramesService(
            self,
            projectId,
            protocolId,
            outputName,
            tiltSeriesId,
            mapper=None,
    ):
        self.lastGetTiltSeriesFramesCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tiltSeriesId": tiltSeriesId,
            "mapper": mapper,
        }
        return self.tiltSeriesFramesResult

    def listOutputCtftomoSeriesService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper=None,
    ):
        self.lastListOutputCtftomoSeriesCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.ctftomoSeriesResult

    def getCtftomoSeriesViewsService(
            self,
            projectId,
            protocolId,
            outputName,
            tiltSeriesId,
            mapper=None,
    ):
        self.lastGetCtftomoSeriesViewsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tiltSeriesId": tiltSeriesId,
            "mapper": mapper,
        }
        return self.ctftomoSeriesViewsResult

    def listCoordinates3dTomogramsService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper=None,
    ):
        self.lastListCoordinates3dTomogramsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.coords3dTomogramsResult

    def getCoordinates3dPointsService(
            self,
            projectId,
            protocolId,
            outputName,
            tomogramId,
            mapper=None,
    ):
        self.lastGetCoordinates3dPointsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tomogramId": tomogramId,
            "mapper": mapper,
        }
        return self.coords3dPointsResult

    def getIntegratedAnalyzeContextService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper=None,
    ):
        self.lastGetIntegratedAnalyzeContextCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.integratedAnalyzeContextResult

    def listProjectTags(self, mapper, projectId, currentUser):
        self.lastListProjectTagsCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectTagsResult

    def createProjectTag(self, mapper, projectId, currentUser, payload):
        self.lastCreateProjectTagCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "payload": payload,
        }
        return self.createProjectTagResult

    def updateProjectTag(self, mapper, projectId, tagId, currentUser, payload):
        self.lastUpdateProjectTagCall = {
            "mapper": mapper,
            "projectId": projectId,
            "tagId": tagId,
            "currentUser": currentUser,
            "payload": payload,
        }
        return self.updateProjectTagResult

    def deleteProjectTag(self, mapper, projectId, tagId, currentUser):
        self.lastDeleteProjectTagCall = {
            "mapper": mapper,
            "projectId": projectId,
            "tagId": tagId,
            "currentUser": currentUser,
        }
        return self.deleteProjectTagResult

    def listProtocolTags(self, mapper, projectId, protocolId, currentUser):
        self.lastListProtocolTagsCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "currentUser": currentUser,
        }
        return self.protocolTagsResult

    def setProtocolTags(self, mapper, projectId, protocolId, tagIds, currentUser):
        self.lastSetProtocolTagsCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "tagIds": tagIds,
            "currentUser": currentUser,
        }
        return self.setProtocolTagsResult

    def getContextMenuVisibilityPolicy(self):
        self.lastGetContextMenuVisibilityPolicyCall = {}
        return self.contextMenuVisibilityResult

    def getFscRowsService(
            self,
            projectId,
            protocolId,
            outputName,
            mapper=None,
    ):
        self.lastGetFscRowsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "mapper": mapper,
        }
        return self.fscRowsResult

    def getProjectEffectiveSettings(self, mapper, projectId, currentUser):
        self.lastGetProjectEffectiveSettingsCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectEffectiveSettingsResult

    def renderCoords3dTomogramSliceService(
            self,
            projectId,
            protocolId,
            outputName,
            tomogramId,
            sliceIndex,
            axis="z",
            colormap=None,
            normalize="minmax",
            scale=1.0,
            inline=True,
            fmt="webp",
            thumb=None,
            fast=True,
            quality=75,
            mapper=None,
    ):
        self.lastRenderCoords3dTomogramSliceCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "tomogramId": tomogramId,
            "sliceIndex": sliceIndex,
            "axis": axis,
            "colormap": colormap,
            "normalize": normalize,
            "scale": scale,
            "inline": inline,
            "fmt": fmt,
            "thumb": thumb,
            "fast": fast,
            "quality": quality,
            "mapper": mapper,
        }
        return self.coords3dSliceResponse


@pytest.fixture
def authTestEnv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # authTestEnv
    scipionHome = tmp_path / "scipion_home"
    scipionHome.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_HOME", str(scipionHome))
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DATABASE_NAME", "scipion_test")
    monkeypatch.setenv("DATABASE_USER", "scipion_test")
    monkeypatch.setenv("DATABASE_PASS", "scipion_test")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")

    return scipionHome

@pytest.fixture
def projectRouterModule(authTestEnv):
    # projectRouterModule
    return importlib.import_module("app.backend.api.routers.project_router")


@pytest.fixture
def fakeProjectMapper():
    # fakeProjectMapper
    return object()


@pytest.fixture
def fakeProjectService():
    # fakeProjectServiceFixture
    return FakeProjectService()


@pytest.fixture
def projectClient(
    projectRouterModule,
    fakeProjectMapper,
    fakeProjectService,
) -> Iterator[TestClient]:
    # projectClient
    app = FastAPI()
    app.include_router(projectRouterModule.router)

    app.dependency_overrides[projectRouterModule.getMapper] = lambda: fakeProjectMapper
    app.dependency_overrides[projectRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    app.dependency_overrides[projectRouterModule.getProjectService] = lambda: fakeProjectService

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()

class FakeMapper:
    # fakeMapper
    def __init__(self):
        self.usersByEmail: dict[str, dict[str, Any]] = {}
        self.usersById: dict[int, dict[str, Any]] = {}
        self.usersByVerificationCode: dict[str, dict[str, Any]] = {}
        self.insertedUsers: list[dict[str, Any]] = []
        self.updatedVerificationCodes: list[tuple[int, str]] = []
        self.updatedUserFields: list[tuple[int, dict[str, Any]]] = []
        self.verifiedUserIds: list[int] = []
        self.nextUserId = 1

    def getUserByEmail(self, email: str):
        return self.usersByEmail.get(email)

    def insertUser(
        self,
        *,
        email: str,
        hashedPassword: str,
        firstName: str,
        lastName: str,
        institution: str,
        role: str,
        isActive: bool,
        isVerified: bool,
        verificationCode: str,
    ):
        userId = self.nextUserId
        self.nextUserId += 1

        user = {
            "id": userId,
            "email": email,
            "hashedPassword": hashedPassword,
            "firstName": firstName,
            "lastName": lastName,
            "institution": institution,
            "role": role,
            "isActive": isActive,
            "isVerified": isVerified,
            "verificationCode": verificationCode,
        }

        self.usersByEmail[email] = user
        self.usersById[userId] = user
        self.usersByVerificationCode[verificationCode] = user
        self.insertedUsers.append(user)
        return userId

    def getUserByVerificationCode(self, verificationCode: str):
        return self.usersByVerificationCode.get(verificationCode)

    def verifyUser(self, userId: int):
        user = self.usersById.get(userId)
        if user is not None:
            user["isVerified"] = True
            self.verifiedUserIds.append(userId)

    def updateUserVerificationCode(self, userId: int, newCode: str):
        user = self.usersById[userId]
        oldCode = user.get("verificationCode")
        if oldCode:
            self.usersByVerificationCode.pop(oldCode, None)
        user["verificationCode"] = newCode
        self.usersByVerificationCode[newCode] = user
        self.updatedVerificationCodes.append((userId, newCode))

    def getUserById(self, userId: int):
        return self.usersById.get(userId)

    def updateUserFields(self, userId: int, fields: dict[str, Any]):
        user = self.usersById[userId]
        user.update(fields)
        self.updatedUserFields.append((userId, fields))

@pytest.fixture
def mainModule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # mainModule
    scipionHome = tmp_path / "scipion_home"
    webDistPath = scipionHome / "web" / "dist"
    webDistPath.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_HOME", str(scipionHome))
    monkeypatch.setenv("SERVE_WEB", "0")
    monkeypatch.setenv("API_MOUNT_PATH", "/api")
    monkeypatch.setenv("WEB_DIST_PATH", str(webDistPath))

    previousModules = _installStubModules()

    try:
        module = _importMainModule()
        yield module
    finally:
        sys.modules.pop("app.backend.main", None)
        _restoreStubModules(previousModules)


@pytest.fixture
def client(mainModule) -> Iterator[TestClient]:
    # client
    with TestClient(mainModule.app) as testClient:
        yield testClient


@pytest.fixture
def loadMainModule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # loadMainModuleWithCustomEnv
    def _load(
        *,
        serveWeb: str = "0",
        apiMountPath: str = "/api",
        createIndexHtml: bool = False,
    ):
        scipionHome = tmp_path / "scipion_home"
        webDistPath = scipionHome / "web" / "dist"
        webDistPath.mkdir(parents=True, exist_ok=True)

        if createIndexHtml:
            (webDistPath / "index.html").write_text(
                "<!doctype html><html><body>web ok</body></html>",
                encoding="utf-8",
            )

        monkeypatch.setenv("SCIPION_HOME", str(scipionHome))
        monkeypatch.setenv("SERVE_WEB", serveWeb)
        monkeypatch.setenv("API_MOUNT_PATH", apiMountPath)
        monkeypatch.setenv("WEB_DIST_PATH", str(webDistPath))

        previousModules = _installStubModules()
        try:
            sys.modules.pop("app.backend.main", None)
            module = importlib.import_module("app.backend.main")
            return module
        finally:
            sys.modules.pop("app.backend.main", None)
            _restoreStubModules(previousModules)

    return _load


@pytest.fixture
def fakeMapper():
    # fakeMapperFixture
    return FakeMapper()


@pytest.fixture
def authClient(authTestEnv, fakeMapper, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # authClient
    import app.backend.api.routers.auth_router as authRouterModule

    monkeypatch.setattr(authRouterModule, "hashPassword", lambda password: f"hashed::{password}")
    monkeypatch.setattr(
        authRouterModule,
        "verifyPassword",
        lambda plainPassword, hashedPassword: hashedPassword == f"hashed::{plainPassword}",
    )
    monkeypatch.setattr(
        authRouterModule,
        "createAccessToken",
        lambda data: f"access::{data['sub']}",
    )
    monkeypatch.setattr(
        authRouterModule,
        "createRefreshToken",
        lambda data: f"refresh::{data['sub']}",
    )
    monkeypatch.setattr(
        authRouterModule,
        "verifyToken",
        lambda token, expected_type="refresh": {"sub": "user@example.com"} if token == "valid-refresh" else {},
    )

    sentEmails: list[tuple[str, str]] = []

    async def fakeSendVerificationEmail(email: str, code: str):
        sentEmails.append((email, code))

    monkeypatch.setattr(authRouterModule, "sendVerificationEmail", fakeSendVerificationEmail)

    app = FastAPI()
    app.include_router(authRouterModule.router)

    app.dependency_overrides[authRouterModule.getMapper] = lambda: fakeMapper
    app.dependency_overrides[authRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }

    app.state.sentEmails = sentEmails

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()

