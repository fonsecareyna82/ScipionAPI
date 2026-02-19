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
import os
from pathlib import Path

from app.backend.bootstrap import bootstrapEnv

# bootstrapEnvFirst
bootstrapEnv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from app.backend.api.routers.project_router import router as projects
from app.backend.api.routers.protocol_router import router as protocols
from app.backend.api.routers.plugin_router import router as plugins
from app.backend.api.routers.auth_router import router as auth
from app.backend.api.routers.user_router import router as users
from app.backend.api.routers.settings_router import router as settingsRouter
from app.backend.api.services.environment import prepareEnvironment
from app.backend.utils.error_handlers import registerAllErrorHandlers


class SpaStaticFiles(StaticFiles):
    # spaStaticFilesFallbackToIndex
    async def get_response(self, path: str, scope):
        # getResponseOrFallbackToIndexHtml
        response = await super().get_response(path, scope)
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


def _buildApiApp() -> FastAPI:
    # buildApiApp
    apiApp = FastAPI(title="Scipion API", debug=True)

    # registerCustomErrorHandlers
    registerAllErrorHandlers(apiApp)

    apiApp.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=[
            "*",
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "X-Scipion-Colormap",
            "X-Preview-Colormap",
            "X-Colormap",
            "Scipion-Colormap",
            "Colormap",
            "X-Preview-Schema",
            "X-Preview-Name"
        ],
        expose_headers=[
            "Content-Disposition",
            "X-Preview-Mime",
            "X-Preview-Width",
            "X-Preview-Height",
            "X-Preview-Depth",
            "X-Preview-Colormap",
            "X-Preview-Colormap-Note",
            "X-Preview-Tiles",
            "X-Preview-SizeBytes",
            "X-Preview-Columns",
            "X-Preview-RowCount",
            "X-Archive-Kind",
            "X-Preview-VoxelSize",
            "X-Preview-Schema",
            "X-Preview-Name",
        ],
    )

    # prepareScipionEnvironment
    prepareEnvironment()

    # includeRouters
    apiApp.include_router(projects)
    apiApp.include_router(protocols)
    apiApp.include_router(plugins)
    apiApp.include_router(auth)
    apiApp.include_router(users)
    apiApp.include_router(settingsRouter)

    @apiApp.get("/health")
    def health_check():
        # healthCheck
        return {"status": "ok"}

    return apiApp


def _normalizeMountPath(value: str) -> str:
    # normalizeMountPath
    mountPath = (value or "/api").strip()
    if not mountPath.startswith("/"):
        mountPath = f"/{mountPath}"
    if mountPath != "/" and mountPath.endswith("/"):
        mountPath = mountPath.rstrip("/")
    return mountPath


def _shouldServeWeb() -> bool:
    # shouldServeWeb
    return (os.getenv("SERVE_WEB") or "").strip() == "1"


def _resolveWebDistPath() -> Path:
    # resolveWebDistPath
    raw = (os.getenv("WEB_DIST_PATH") or "").strip()
    if not raw:
        return Path("")
    return Path(raw).expanduser().resolve()


apiApp = _buildApiApp()

serveWeb = _shouldServeWeb()
webDistPath = _resolveWebDistPath()
apiMountPath = _normalizeMountPath(os.getenv("API_MOUNT_PATH") or "/api")

# alwaysMountApiUnderApiMountPath
app = FastAPI(title="Scipion Web", debug=True)

app.mount(apiMountPath, apiApp)

@app.get("/health", include_in_schema=False)
def health_check():
    # healthCheckRoot
    return {"status": "ok", "mode": "api-only" if not serveWeb else "combined", "apiMountPath": apiMountPath}


# optional: keepConvenienceRedirects
@app.get("/docs", include_in_schema=False)
def docs_redirect():
    # redirectDocsToApiDocs
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{apiMountPath}/docs")


@app.get("/openapi.json", include_in_schema=False)
def openapi_redirect():
    # redirectOpenApiToApiOpenApi
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{apiMountPath}/openapi.json")


if serveWeb and webDistPath and (webDistPath / "index.html").exists():
    # mountSpaStaticRootLast
    app.mount("/", SpaStaticFiles(directory=str(webDistPath), html=True), name="web")

