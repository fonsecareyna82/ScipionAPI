import ast
from pathlib import Path

import pytest


ROUTER_STRICT_SERVICE_CALLS = {
    "getProtocolPath": {"getProtocolPath"},
    "listProtocolDir": {"listProtocolDir"},
    "previewProtocolText": {"previewProtocolTextFile"},
    "previewRemoteEntry": {"previewRemoteEntry"},
    "previewProtocolImageFile": {"previewProtocolImageFile"},
    "writeRemoteFile": {"writeRemoteFileService"},
    "resolveAnalyzeViewer": {"resolveAnalyzeViewerDecision"},
    "listOutputVolumes": {"listOutputVolumesService"},
    "getVolumeInfo": {"getVolumeInfoService"},
    "getVolumeHistogram": {"getVolumeHistogramService"},
    "renderVolumeSlice": {"renderVolumeSliceService"},
    "renderVolumeSlicesBatch": {"renderVolumeSlicesBatchService"},
    "getVolumeData3d": {"getVolumeData3dService"},
    "getVolumeSurfaceMesh": {"getVolumeSurfaceMesh"},
    "listOutputTiltSeries": {"listOutputTiltSeriesService"},
    "getTiltSeriesFrames": {"getTiltSeriesFramesService"},
    "renderTiltSeriesImage": {"renderTiltSeriesImageService"},
    "renderTiltSeriesImagesBatch": {"renderTiltSeriesImagesBatchService"},
    "createNewSetOfTiltSeries": {"createNewSetOfTiltSeriesService"},
    "listCtfModels": {"listOutputCtfService"},
    "renderCtfPsdImage": {"renderCtfPsdImageService"},
    "renderCtfMicrographImage": {"renderCtfMicrographImageService"},
    "listCtftomoSeries": {"listOutputCtftomoSeriesService"},
    "getCtftomoSeriesViews": {"getCtftomoSeriesViewsService"},
    "createNewSetOfCtftomoSeries": {"createNewSetOfCtftomoSeriesService"},
    "renderCtftomoPsdImage": {"renderCtfTomoPsdImageService"},
    "listCoordinates3dTomograms": {"listCoordinates3dTomogramsService"},
    "getCoordinates3dPoints": {"getCoordinates3dPointsService"},
    "renderCoords3dTomogramSlice": {"renderCoords3dTomogramSliceService"},
    "renderCoords3dTomogramGallery": {"renderCoords3dTomogramGalleryService"},
    "createCoords3dOutputFromPoints": {"createCoords3dOutputFromPointsService"},
    "getIntegratedAnalyzeContext": {"getIntegratedAnalyzeContextService"},
    "getTomogramReviewContext": {"getTomogramReviewContextService"},
    "putTomogramReviewSchema": {"saveTomogramReviewSchemaService"},
    "patchTomogramReview": {"saveTomogramReviewService"},
    "createTomogramReviewSubset": {"createTomogramReviewSubsetService"},
    "getFscRows": {"getFscRowsService"},
    "listOutputMetadataTables": {"listOutputMetadataTablesService"},
    "getMetadataTableSchema": {"getMetadataTableSchemaService"},
    "runMetadataTableAction": {"runMetadataTableActionService"},
    "getMetadataTablePage": {"getMetadataTablePageService"},
    "exportMetadataTable": {"exportMetadataTableService"},
    "getMetadataRowPosition": {"getMetadataRowPositionService"},
    "renderMetadataImageCell": {"renderMetadataImageCellCachedService"},
    "renderMetadataImageCellsBatch": {"renderMetadataImageCellsBatchService"},
    "getMetadataTableWindow": {"getMetadataTableWindowService"},
    "listExternalViewers": {"listExternalViewers"},
    "launchExternalViewer": {"launchExternalViewer"},
    "listProtocolTags": {"listProtocolTags"},
    "setProtocolTags": {"setProtocolTags"},
}


PUBLIC_SERVICE_METHODS = sorted({
    service_name
    for service_names in ROUTER_STRICT_SERVICE_CALLS.values()
    for service_name in service_names
})


def _repo_root():
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (
            parent / "app/backend/api/routers/project_router.py"
        ).exists():
            return parent

    raise AssertionError("ScipionAPI repository root not found")


def _load_ast(relative_path):
    path = _repo_root() / relative_path
    return ast.parse(
        path.read_text(),
        filename=str(path),
    )


def _find_function(tree, function_name):
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name == function_name
    ]
    assert len(matches) == 1, (
        f"{function_name}: expected exactly one function, "
        f"found {len(matches)}"
    )
    return matches[0]


def _is_service_call(node, method_name):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method_name
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "service"
    )


def _function_accepts_parameter(function, parameter_name):
    args = function.args
    names = [
        arg.arg
        for arg in (
            list(args.posonlyargs)
            + list(args.args)
            + list(args.kwonlyargs)
        )
    ]
    return parameter_name in names


@pytest.mark.parametrize(
    ("router_function", "service_method"),
    [
        (router_function, service_method)
        for router_function, service_methods
        in ROUTER_STRICT_SERVICE_CALLS.items()
        for service_method in sorted(service_methods)
    ],
)
def test_ProtocolRoutePassesExplicitScipionIdentity(
        router_function,
        service_method,
):
    tree = _load_ast(
        "app/backend/api/routers/project_router.py"
    )
    function = _find_function(
        tree,
        router_function,
    )

    calls = [
        node
        for node in ast.walk(function)
        if _is_service_call(
            node,
            service_method,
        )
    ]

    assert calls, (
        f"{router_function}: no call to service."
        f"{service_method} was found"
    )

    for call in calls:
        strict_keyword = next(
            (
                keyword
                for keyword in call.keywords
                if keyword.arg
                == "protocolIdIsScipionId"
            ),
            None,
        )

        assert strict_keyword is not None, (
            f"{router_function} -> {service_method} "
            "must pass protocolIdIsScipionId=True"
        )

        assert (
            isinstance(
                strict_keyword.value,
                ast.Constant,
            )
            and strict_keyword.value.value is True
        ), (
            f"{router_function} -> {service_method} "
            "must pass protocolIdIsScipionId=True"
        )


@pytest.mark.parametrize(
    "method_name",
    PUBLIC_SERVICE_METHODS,
)
def test_ProtocolRouteServiceAcceptsExplicitScipionIdentity(
        method_name,
):
    tree = _load_ast(
        "app/backend/api/services/project_service.py"
    )
    function = _find_function(
        tree,
        method_name,
    )

    assert _function_accepts_parameter(
        function,
        "protocolIdIsScipionId",
    ), (
        f"{method_name} must accept "
        "protocolIdIsScipionId"
    )
