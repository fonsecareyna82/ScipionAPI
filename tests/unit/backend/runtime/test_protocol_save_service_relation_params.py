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
from types import SimpleNamespace

from app.backend.runtime.protocol_save_service import (
    RuntimeProtocolSaveService,
)


class FakePointerParam:
    pass


class FakeMultiPointerParam:
    pass


class FakeRelationParam:
    def __init__(self):
        self.label = SimpleNamespace(
            get=lambda: "CTF estimation"
        )


class ProtocolStub:
    def __init__(self, relationParam):
        self.relationParam = relationParam

    def getParam(self, name):
        if name == "ctfRelations":
            return self.relationParam

        return None


def test_RelationParamUsesSinglePointerApplication(
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.runtime.protocol_save_service"
    )

    monkeypatch.setattr(
        module,
        "PointerParam",
        FakePointerParam,
    )

    monkeypatch.setattr(
        module,
        "MultiPointerParam",
        FakeMultiPointerParam,
    )

    monkeypatch.setattr(
        module,
        "RelationParam",
        FakeRelationParam,
    )

    relationParam = FakeRelationParam()

    protocol = ProtocolStub(
        relationParam
    )

    service = (
        RuntimeProtocolSaveService()
    )

    calls = []

    def applyPointerParam(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(
        service,
        "_applyPointerParam",
        applyPointerParam,
    )

    errors = (
        service
        .applyPointerParamsToProtocol(
            mapper=object(),
            projectId=7,
            protocol=protocol,
            params={
                "ctfRelations":
                    "21.outputCTF",
            },
            resolvePointerParentProtocolCallback=(
                lambda *args, **kwargs: None
            ),
            resolveParentOutputCallback=(
                lambda *args, **kwargs: None
            ),
        )
    )

    assert errors == []

    assert len(calls) == 1

    assert calls[0][
        "inputName"
    ] == "ctfRelations"

    assert calls[0][
        "rawValue"
    ] == "21.outputCTF"

    assert calls[0][
        "param"
    ] is relationParam