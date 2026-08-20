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
import importlib
from inspect import signature


def test_volume_slice_auth_reuses_request_scoped_mapper_dependency(
    authTestEnv,
    projectRouterModule,
):
    dependenciesModule = importlib.import_module(
        "app.backend.api.dependencies"
    )
    databaseModule = importlib.import_module(
        "app.backend.database"
    )

    authDependency = signature(
        dependenciesModule.getCurrentUser
    ).parameters["mapper"].default

    sliceDependency = signature(
        projectRouterModule.renderVolumeSlice
    ).parameters["mapper"].default

    assert (
        authDependency.dependency
        is databaseModule.getMapperDependency
    )
    assert (
        sliceDependency.dependency
        is databaseModule.getMapperDependency
    )
    assert (
        authDependency.dependency
        is sliceDependency.dependency
    )