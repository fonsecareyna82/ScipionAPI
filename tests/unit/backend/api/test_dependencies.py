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
from inspect import signature

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.routers.project_router import renderVolumeSlice
from app.backend.database import getMapperDependency


def test_volume_slice_auth_reuses_request_scoped_mapper_dependency():
    authDependency = signature(
        getCurrentUser
    ).parameters["mapper"].default

    sliceDependency = signature(
        renderVolumeSlice
    ).parameters["mapper"].default

    assert authDependency.dependency is getMapperDependency
    assert sliceDependency.dependency is getMapperDependency
    assert authDependency.dependency is sliceDependency.dependency