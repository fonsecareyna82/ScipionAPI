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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.backend.api.routers.project_router import router as projects
from app.backend.api.routers.protocol_router import router as protocols
from app.backend.api.routers.plugin_router import router as plugins
from app.backend.api.routers.auth_router import router as auth
from app.backend.api.routers.user_router import router as users
from app.backend.api.services.environment import prepareEnvironment
from app.backend.utils.error_handlers import registerAllErrorHandlers

app = FastAPI(title="Scipion API", debug=True)

# Register custom error handlers
registerAllErrorHandlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # o ["*"] para desarrollo
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
    ],
)

prepareEnvironment()
app.include_router(projects)
app.include_router(protocols)
app.include_router(plugins)
app.include_router(auth)
app.include_router(users)


@app.get("/health")
def health_check():
    return {"status": "ok"}

