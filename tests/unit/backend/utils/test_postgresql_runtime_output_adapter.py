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
from app.backend.utils.postgresql_runtime_output_adapter import (
    PostgresqlRuntimeOutputProxy,
)


class FakeDb:
    pass


class FakeParentProtocol:
    def getObjId(self):
        return 1175


def newProxy(outputInfo):
    return PostgresqlRuntimeOutputProxy(
        db=FakeDb(),
        parent=FakeParentProtocol(),
        outputName="outputParticles",
        outputInfo=outputInfo,
    )


def test_GetObjIdUsesRuntimeObjectId():
    proxy = newProxy({
        "objectId": "9001",
        "runtimeObjectId": "245",
    })

    assert proxy.getObjId() == 245


def test_GetObjIdDoesNotExposeCanonicalIdWhenRuntimeIdIsMissing():
    proxy = newProxy({
        "objectId": "9001",
        "runtimeObjectId": None,
    })

    assert proxy.getObjId() is None


def test_GetObjIdSupportsLegacyOutputInfo():
    proxy = newProxy({
        "objectId": "245",
    })

    assert proxy.getObjId() == 245