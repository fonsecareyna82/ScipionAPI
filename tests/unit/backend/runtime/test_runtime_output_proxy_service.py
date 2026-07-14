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
from types import SimpleNamespace

from app.backend.runtime.postgresql_runtime_set_factory import (
    PostgresqlRuntimeSetFactory,
)
from app.backend.runtime.runtime_output_proxy_service import (
    RuntimeOutputProxyService,
)
from app.backend.utils.postgresql_runtime_output_adapter import (
    PostgresqlRuntimeOutputProxy,
)


def test_SetOutputUsesNativeRuntimeSetFactory(
        monkeypatch,
):
    db = object()
    mapper = SimpleNamespace(
        db=db
    )
    parent = SimpleNamespace()
    runtimeSet = object()
    captured = {}

    def fakeBuild(
            self,
            db,
            parent,
            outputName,
            outputInfo,
            classes=None,
    ):
        captured["db"] = db
        captured["parent"] = parent
        captured["outputName"] = outputName
        captured["outputInfo"] = outputInfo

        return runtimeSet

    monkeypatch.setattr(
        PostgresqlRuntimeSetFactory,
        "build",
        fakeBuild,
    )

    outputInfo = {
        "setId": 31,
        "className": "SetOfParticles",
        "itemClassName": "Particle",
    }

    result = (
        RuntimeOutputProxyService()
        .attachPostgresqlRuntimeOutputProxy(
            parentProtocol=parent,
            outputName="outputParticles",
            outputInfo=outputInfo,
            mapper=mapper,
        )
    )

    assert result is runtimeSet
    assert parent.outputParticles is runtimeSet

    assert captured == {
        "db": db,
        "parent": parent,
        "outputName": "outputParticles",
        "outputInfo": outputInfo,
    }


def test_NonSetOutputKeepsGenericRuntimeProxy():
    mapper = SimpleNamespace(
        db=object()
    )
    parent = SimpleNamespace()

    result = (
        RuntimeOutputProxyService()
        .attachPostgresqlRuntimeOutputProxy(
            parentProtocol=parent,
            outputName="outputVolume",
            outputInfo={
                "objectId": 41,
                "className": "Volume",
            },
            mapper=mapper,
        )
    )

    assert isinstance(
        result,
        PostgresqlRuntimeOutputProxy,
    )

    assert parent.outputVolume is result