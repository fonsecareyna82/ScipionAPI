from fastapi import APIRouter, Depends, HTTPException, status, Path as PathParam, Query, Request
from typing import List, Any, Union, Optional, Literal, Dict

from app.backend.api.dependencies import getCurrentUser
from app.backend.database import getMapper
from app.backend.api.schemas.project_schema import ProjectCreate, ProjectOut, ProjectUpdate
from app.backend.api.services.project_service import ProjectService
from app.backend.models.protocol_model import (
    ProtocolRequest,
    ProtocolRenameIn,
    DuplicatePayload,
    DeletePayload,
)
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/projects", tags=["projects"])
service = ProjectService()


@router.post("/", response_model=ProjectOut)
def createProject(
    projectData: ProjectCreate,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    return service.createProject(mapper, projectData, currentUser)


@router.get("/", response_model=List[ProjectOut])
def listProjects(
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    return service.listProjects(mapper, currentUser)


@router.get("/{projectId}", response_model=Any)
def getProject(
    projectId: int,  # id in the DB
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{projectId}", response_model=ProjectOut, status_code=status.HTTP_200_OK)
def updateProject(
    projectId: int,
    projectData: ProjectUpdate,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    return service.updateProject(mapper, projectId, currentUser, projectData)


@router.delete("/{projectId}", status_code=status.HTTP_200_OK)
def deleteProject(
    projectId: int,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Delete a project owned by the authenticated user.
    """
    return service.deleteProject(mapper, currentUser, projectId)


@router.get(
    "/{projectId}/protocols",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def loadProtocols(
    projectId: int = PathParam(..., ge=1, title="Numeric project ID"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    protocols = service.getProtocols(mapper, projectId, currentUser)
    if not protocols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Protocols not found"
        )
    return protocols


@router.get("/{projectId}/protocols/{protocolId}", response_model=Any)
async def loadProtocol(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return service.getProtocolParams(projectId, protocolId)


@router.get("/{projectId}/protclass/{protClassName}", response_model=Any)
async def loadNewProtocol(
    projectId: int,
    protClassName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getNewProtocolParams(projectId, protClassName)


@router.post("/launch", response_model=Any)
async def launchProtocol(request: ProtocolRequest,
                         mapper: PostgresqlFlatMapper = Depends(getMapper)):
    try:
        protocolId = request.getProtocolId()
        protocolClassName = request.getProtocolClassName()
        params = request.getParams()
        service.launchProtocol(mapper, protocolId, protocolClassName, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save", response_model=Any)
async def saveProtocol(request: ProtocolRequest,
                       mapper: PostgresqlFlatMapper = Depends(getMapper)):
    try:
        protocolId = request.getProtocolId()
        protocolClassName = request.getProtocolClassName()
        params = request.getParams()
        service.saveProtocol(mapper, protocolId, protocolClassName, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{projectId}/protocols/{protocolId}/rename", response_model=Any, status_code=status.HTTP_200_OK)
def renameProtocol(
    projectId: int,
    protocolId: int,
    payload: ProtocolRenameIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return service.renameProtocol(protocolId, payload.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/duplicate", response_model=Any, status_code=status.HTTP_201_CREATED)
def duplicateProtocol(
    projectId: int,
    payload: DuplicatePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return service.duplicateProtocol(payload.items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/delete", response_model=Any, status_code=status.HTTP_200_OK)
def deleteProtocol(
    projectId: int,
    payload: DeletePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.deleteProtocol(payload.ids)
        return {"status": "ok", "message": "Protocol deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/{protocolId}/restart-all", response_model=Any, status_code=status.HTTP_200_OK)
def restartProtocolAll(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        errorList = service.restartProtocolAll(protocolId)
        if errorList:
            return {"status": "failed", "details": errorList}
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/{protocolId}/continue-all", response_model=Any, status_code=status.HTTP_200_OK)
def continueProtocolAll(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.continueProtocolAll(mapper, projectId, protocolId, currentUser)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/{protocolId}/reset-from", response_model=Any, status_code=status.HTTP_200_OK)
def resetProtocolFrom(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.resetProtocolFrom(protocolId)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/stop", response_model=Any, status_code=status.HTTP_200_OK)
def stopProtocol(
    projectId: int,
    payload: DeletePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.stopProtocol(payload.ids)
        return {"status": "ok", "message": "Protocol stoped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{projectId}/protocols/{protocolId}/fs/start-path", response_model=Any)
async def getProtocolPath(
    projectId: int,
    protocolId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getProtocolPath(protocolId)


# ======================================================================
#                FS REMOTE: list / preview / download
# ======================================================================

@router.get("/{projectId}/protocols/{protocolId}/fs/list", response_model=Any)
async def listProtocolDir(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query("", description="Relative path inside the protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.listProtocolDir(protocolId, path)


@router.get("/{projectId}/protocols/{protocolId}/fs/preview", response_model=None)
async def previewProtocolText(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.previewProtocolTextFile(protocolId, path)


@router.get("/{projectId}/protocols/{protocolId}/fs/download", response_model=None)
async def previewProtocolImageFile(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    inline: bool = Query(False, description="If true, send Content-Disposition inline"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.previewProtocolImageFile(protocolId, path, inline)


@router.get("/{projectId}/protocols/{protocolId}/outputpreview/{outputName}", response_model=None)
async def previewOutput(
    projectId: int,
    protocolId: Union[int, str],
    outputName: str,
    request: Request,
    currentUser=Depends(getCurrentUser),
    mapper=Depends(getMapper),
):

    # Prefer header; fallback to query param (?cmap=viridis or ?colormap=viridis)
    cmapHeader = (
        request.headers.get("x-scipion-colormap")
        or request.headers.get("x-preview-colormap")
        or request.headers.get("x-colormap")
        or request.headers.get("scipion-colormap")
        or request.headers.get("colormap")
    )
    cmapQuery = request.query_params.get("cmap") or request.query_params.get("colormap")

    return service.outputPreview(
        protocolId=protocolId,
        outputName=outputName,
        requestHeaders=dict(request.headers),
        colormap=cmapHeader or cmapQuery,
    )


# ==============================================================================
#                ANALYZE RESULTS: VOLUMES (Volume / VolumeMask / SetOfVolumes)
# ==============================================================================

@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes", response_model=Any, status_code=status.HTTP_200_OK)
def listOutputVolumes(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    items = service.listOutputVolumesService(projectId, protocolId, outputName)
    from fastapi.responses import JSONResponse
    resp = JSONResponse(items)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["X-Debug-VolumeCount"] = str(len(items or []))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/info",
            response_model=Any, status_code=status.HTTP_200_OK)
def getVolumeInfo(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],  # <-- accept string or int
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    info = service.getVolumeInfoService(projectId, protocolId, outputName, volumeId)
    from fastapi.responses import JSONResponse
    resp = JSONResponse(info)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/histogram",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getVolumeHistogram(
        projectId: int,
        protocolId: int,
        outputName: str,
        volumeId: Union[int, str],
        bins: int = Query(
            128,
            ge=4,
            le=8192,
            description="Number of histogram bins",
        ),
        currentUser=Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return intensity histogram for one volume.

    Expected response (example):
    {
      "binEdges": [e0, e1, ..., eN],   # or backend may use bin_edges
      "counts":   [c0, c1, ..., cN-1]  # or values
    }
    """
    hist = service.getVolumeHistogramService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        bins=bins,
    )

    from fastapi.responses import JSONResponse
    resp = JSONResponse(hist or {"binEdges": [], "counts": []})
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/slice",
            response_model=None)
def renderVolumeSlice(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],  # <-- accept string or int
    index: int = Query(0, ge=0),  # 0-based
    axis: str = Query("z", pattern="^(x|y|z)$"),
    # Accept BOTH but resolve to 'cmap' (front already sends cmap)
    cmapParam: Optional[str] = Query(None, alias="cmap"),
    colormapParam: Optional[str] = Query(None, alias="colormap"),
    # Accept BOTH but resolve to 'fmt'
    formatParam: Optional[str] = Query(None, alias="format"),
    fmtParam: Optional[str] = Query(None, alias="fmt"),
    normalize: Optional[str] = Query(None),
    scale: float = Query(1.0, gt=0),
    inline: bool = Query(True),
    thumb: Optional[int] = Query(None, ge=32, le=2048),
    fast: bool = Query(True),
    quality: int = Query(75, ge=1, le=100),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    cmap = cmapParam or colormapParam or "viridis"
    fmt = fmtParam or formatParam or "webp"

    resp = service.renderVolumeSliceService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        sliceIndex=index,
        axis=axis,
        colormap=cmap,
        normalize=normalize,
        scale=scale,
        inline=inline,
        fmt=fmt,
        thumb=thumb,
        fast=fast,
        quality=quality,
    )
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/data3d",
    summary="Get downsampled 3D volume data for Plotly preview",
)
def getVolumeData3d(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    maxDim: int = Query(160, ge=32, le=512, alias="maxDim"),
    method: Literal["binning", "stride", "none"] = Query("binning"),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    currentUser: Dict[str, Any] = Depends(getCurrentUser),
):

    return service.getVolumeData3dService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        maxDim=maxDim,
        method=method,
    )
# ==============================================================================
#        ANALYZE RESULTS: COORDINATES3D (SetOfCoordinates3D)
# ==============================================================================

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listCoordinates3dTomograms(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    List tomograms referenced by a SetOfCoordinates3D output.

    Response example:
    [
      { "id": "TS_1", "name": "TS_1" },
      { "id": "TS_2", "name": "TS_2" }
    ]
    """
    items = service.listCoordinates3dTomogramsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(items or [])
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms/{tomogramId}",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getCoordinates3dPoints(
    projectId: int,
    protocolId: int,
    outputName: str,
    tomogramId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return all 3D coordinates for one tomogram inside a SetOfCoordinates3D.

    Response example (backend currently returns a flat array of points):
    [
      { "x": 123.4, "y": 56.7, "z": 89.0, "id": 1, "score": 3.4, "tomoId": "TS_1" },
      ...
    ]
    """
    pts = service.getCoordinates3dPointsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tomogramId=tomogramId,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(pts or [])
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms/{tomogramId}/slice",
    status_code=status.HTTP_200_OK,
)
def renderCoords3dTomogramSlice(
    projectId: int,
    protocolId: int,
    outputName: str,
    tomogramId: str,
    index: int = Query(..., ge=0, description="0-based slice index along the selected axis", ),
    axis: str = Query("z", description="Axis along which to slice the tomogram: x, y or z",),
    cmap: Optional[str] = Query(None, alias="cmap", description="Optional colormap name (e.g. 'gray', 'viridis')",),
    normalize: Optional[str] = Query("minmax", description="Normalization mode: 'minmax' or 'zscore'",),
    scale: float = Query(1.0, description="Optional scaling factor applied to the 2D slice", ),
    inline: bool = Query(True, description="If true, returns the image as inline preview", ),
    fmt: str = Query("webp", alias="format", description="Output image format: png | webp | jpeg",),
    thumb: Optional[int] = Query(None, description="If set, max thumbnail size (pixels) for the longest dimension",),
    fast: bool = Query(True, description="Reserved flag for potential faster/approximate rendering",),
    quality: int = Query(75, description="JPEG/WEBP quality (1–100) when applicable",),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Render a 2D slice from a tomogram referenced by a SetOfCoordinates3D.

    The response is an image (PNG/WEBP/JPEG) similar in spirit to
    the volume slice endpoint, with X-Preview-* headers describing
    width/height/format/etc.
    """
    resp = service.renderCoords3dTomogramSliceService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tomogramId=tomogramId,
        sliceIndex=index,
        axis=axis,
        colormap=cmap,
        normalize=normalize,
        scale=scale,
        inline=inline,
        fmt=fmt,
        thumb=thumb,
        fast=fast,
        quality=quality,
    )

    # Keep auth-related headers consistent with the rest of the API
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp



# ==============================================================================
#            ANALYZE RESULTS: METADATA TABLES (.sqlite / .star / etc.)
# ==============================================================================

@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listOutputMetadataTables(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    List logical metadata tables (blocks) associated with a given output.
    Typical use case: STAR blocks, SQLITE tables, etc.

    Expected response (example):
    [
      {
        "name": "data_particles",
        "alias": "Particles",
        "rowCount": 123456,
        "hasColumnId": true
      },
      ...
    ]
    """
    items = service.listOutputMetadataTablesService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    from fastapi.responses import JSONResponse
    resp = JSONResponse(items)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/schema",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getMetadataTableSchema(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return logical schema for one metadata table: columns, renderers, flags.

    Expected response (example):
    {
      "name": "data_particles",
      "alias": "Particles",
      "hasColumnId": true,
      "columns": [
        {
          "name": "id",
          "alias": "id",
          "index": 0,
          "sortable": true,
          "visible": true,
          "rendererType": "int",          # int|float|bool|matrix|image|str
          "decimals": null,
          "hasTransformation": false
        },
        ...
      ]
    }
    """
    schema = service.getMetadataTableSchemaService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
    )

    from fastapi.responses import JSONResponse
    resp = JSONResponse(schema)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/page",
            response_model=Any,
            status_code=status.HTTP_200_OK,
)
def getMetadataTablePage(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    page: int = Query(1, ge=1, description="1-based page number"),
    pageSize: int = Query(100, ge=1, le=5000),
    sortBy: str = Query("id", description="Column name used for sorting"),
    asc: bool = Query(True, description="Sort ascending if true"),
    selectionOnly: bool = Query(
        False,
        description="If true, return only rows currently selected in this table (if implemented)",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return one logical page of rows for a metadata table.

    Expected response (example):
    {
      "pageNumber": 1,
      "pageSize": 100,
      "totalRows": 123456,
      "rows": [
        {
          "id": 1,
          "values": [
            1,             # int / float / bool / string
            "A value",
            { "kind": "image", "path": "path/to/img.mrc" },
            { "kind": "matrix", "value": [[1.0, 2.0], [3.0, 4.0]] }
          ]
        },
        ...
      ]
    }
    """
    pageData = service.getMetadataTablePageService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        page=page,
        pageSize=pageSize,
        sortBy=sortBy,
        asc=asc,
        selectionOnly=selectionOnly,
    )

    from fastapi.responses import JSONResponse
    resp = JSONResponse(pageData)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/export",
            response_model=None,)
def exportMetadataTable(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    fmt: str = Query(
        "csv",
        alias="format",
        pattern="^(csv|xlsx)$",
        description="Export format: csv or xlsx",
    ),
    selectionOnly: bool = Query(False, description="If true, export only selected rows (server-side selection, if implemented).",),
    ids: Optional[str] = Query(None, description="Optional comma-separated row ids to export; if provided, takes precedence over selectionOnly.",),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Export a metadata table (full or subset) as CSV/XLSX.

    - If `ids` is provided → use those ids.
    - Else if `selectionOnly` is true → use server-side selection.
    - Else → export the whole table.
    """
    idList: Optional[List[int]] = None
    if ids:
        try:
            idList = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 'ids' parameter. Expected comma-separated integers.",
            )

    resp = service.exportMetadataTableService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        fmt=fmt,
        selectionOnly=selectionOnly,
        ids=idList,
    )
    # resp should be a StreamingResponse / FileResponse
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/image",
            response_model=None,)
def renderMetadataImageCell(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    rowId: Optional[Union[int, str]] = Query(None, description="Logical row id (for selection/export workflows; optional in virtual scroll).",),
    rowIndex: Optional[int] = Query(None, ge=0, description="0-based row index in the current table order (preferred for virtual scroll).",),
    column: str = Query(..., description="Column name that contains the image path or reference.",),
    size: int = Query(256, ge=16, le=2048, description="Target thumbnail size in pixels.",),
    applyTransform: bool = Query(False, description="If true, apply geometric transformation (rotation) if available.",),
    inline: bool = Query(True, description="If true, send Content-Disposition inline (for browser display).",),
    fmt: str = Query("png", description="Image format to generate (png, jpeg, webp, etc.), implementation-dependent.",),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Render one image cell from a metadata table using the same logic as ImageRenderer:
    - Resize / normalize
    - Optional rotation / transformation

    Frontend will use this endpoint for cells whose rendererType == 'image'.
    """
    resp = service.renderMetadataImageCellService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        rowId=rowId,
        rowIndex=rowIndex,
        columnName=column,
        size=size,
        applyTransform=applyTransform,
        inline=inline,
        fmt=fmt,
    )
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/rows")
def get_metadata_window(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, gt=0),
    selectionOnly: bool = Query(False),
    currentUser=Depends(getCurrentUser),
):
    return service.getMetadataTableWindowService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        offset=offset,
        limit=limit,
        selectionOnly=selectionOnly,
    )


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/rows",
            response_model=Any,
            status_code=status.HTTP_200_OK,
)
def getMetadataTableWindow(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    offset: int = Query(
        0,
        ge=0,
        description="0-based starting row index in the current table order",
    ),
    limit: int = Query(
        2000,
        ge=1,
        le=10000,
        description="Maximum number of rows to return in this window",
    ),
    selectionOnly: bool = Query(
        False,
        description="If true, use server-side selection instead of the full table",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return a window (offset + limit) of rows for a metadata table.

    This endpoint is intended for virtual scrolling:
    - `offset` and `limit` are 0-based indices in the current table order.
    - The response exposes `totalRows` so the frontend can know the global size.
    - Each returned row has:
        - `id` / `index`: 0-based global index (stable for the viewer)
        - `rowId`: logical DAO id (if available)
        - `values`: JSON-friendly cell payloads
    """
    # Ensure project exists and belongs to the current user
    # project = service.getProjectById(mapper, projectId, currentUser)
    # if not project:
    #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    windowData = service.getMetadataTableWindowService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        offset=offset,
        limit=limit,
        selectionOnly=selectionOnly,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(windowData)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp

