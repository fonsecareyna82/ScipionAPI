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
from app.backend.runtime.pointer_resolver import RuntimePointerResolver


class FakeParentProtocol:
    def __init__(self, protocolId):
        self.protocolId = protocolId

    def getObjId(self):
        return self.protocolId


class FakeImportedPointer:
    def __init__(self, parentProtocol, outputName):
        self.parentProtocol = parentProtocol
        self.outputName = outputName

    def get(self):
        # The parent protocol has not produced the output yet.
        return None

    def getObjValue(self):
        return self.parentProtocol

    def getExtended(self):
        return self.outputName


class FakeImportedProtocol:
    def __init__(self, inputPointers):
        self.inputPointers = inputPointers

    def iterInputPointers(self):
        return iter(self.inputPointers)

    def iterInputAttributes(self):
        raise AssertionError(
            "Imported workflow pointers must be collected with iterInputPointers"
        )


def test_MergeImportedWorkflowPointerParamsBeforeParentOutputsExist():
    parentProtocol = FakeParentProtocol(300001)

    protocol = FakeImportedProtocol([
        (
            "inputParticles",
            FakeImportedPointer(
                parentProtocol=parentProtocol,
                outputName="outputParticles",
            ),
        ),
    ])

    resolver = RuntimePointerResolver()

    result = resolver.mergePointerParamsWithProtocolState(
        protocol=protocol,
        params=None,
    )

    assert result == {
        "inputParticles": "300001.outputParticles",
    }


def test_MergeImportedWorkflowMultiPointerParamsWithoutOverwritingItems():
    firstParentProtocol = FakeParentProtocol(300001)
    secondParentProtocol = FakeParentProtocol(300002)

    protocol = FakeImportedProtocol([
        (
            "inputVolumes",
            FakeImportedPointer(
                parentProtocol=firstParentProtocol,
                outputName="outputVolume",
            ),
        ),
        (
            "inputVolumes",
            FakeImportedPointer(
                parentProtocol=secondParentProtocol,
                outputName="outputVolume",
            ),
        ),
    ])

    resolver = RuntimePointerResolver()

    result = resolver.mergePointerParamsWithProtocolState(
        protocol=protocol,
        params=None,
    )

    assert result == {
        "inputVolumes": [
            "300001.outputVolume",
            "300002.outputVolume",
        ],
    }


def test_ExplicitlyClearedPointerParamsAreNotRestored():
    parentProtocol = FakeParentProtocol(300001)

    protocol = FakeImportedProtocol([
        (
            "inputParticles",
            FakeImportedPointer(
                parentProtocol=parentProtocol,
                outputName="outputParticles",
            ),
        ),
    ])

    resolver = RuntimePointerResolver()

    result = resolver.mergePointerParamsWithProtocolState(
        protocol=protocol,
        params={
            "inputParticles": None,
        },
    )

    assert result == {
        "inputParticles": None,
    }