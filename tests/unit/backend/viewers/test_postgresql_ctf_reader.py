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


def makeReader():
    module = importlib.import_module(
        "app.backend.viewers.postgresql_ctf_reader"
    )

    return module.PostgresqlCtfReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCTF",
    )


def test_PostgresqlCtfReaderBuildsCtfRow(authTestEnv):
    reader = makeReader()

    row = reader._buildCtfRow(
        {
            "scipionItemId": 17,
            "enabled": True,
            "label": "mic_001",
            "values": {
                "_defocusU": 22000,
                "_defocusV": 21000,
                "_defocusAngle": 37.5,
                "_defocusRatio": 1.047619,
                "_phaseShift": 0.15,
                "_resolution": 4.2,
                "_fitQuality": 0.91,
                "_psdFile": "Runs/000500_CTF/extra/psd_001.mrc",
            },
        },
        position=3,
    )

    assert row["ctfId"] == "17"
    assert row["position"] == 3
    assert row["micrographId"] == "17"
    assert row["micrographName"] == "mic_001"
    assert row["defocusU"] == 22000
    assert row["defocusV"] == 21000
    assert row["astigmatism"] == 1000
    assert row["defocusAngle"] == 37.5
    assert row["defocusRatio"] == 1.047619
    assert row["phaseShift"] == 0.15
    assert row["resolution"] == 4.2
    assert row["fitQuality"] == 0.91
    assert row["psdFile"] == "Runs/000500_CTF/extra/psd_001.mrc"
    assert row["failed"] is False
    assert row["excluded"] is False


def test_PostgresqlCtfReaderDetectsFailedCtf(authTestEnv):
    reader = makeReader()

    row = reader._buildCtfRow(
        {
            "scipionItemId": 18,
            "enabled": True,
            "values": {
                "_defocusU": -999,
                "_defocusV": -1,
            },
        },
        position=0,
    )

    assert row["failed"] is True
    assert "astigmatism" not in row
    assert "defocusRatio" not in row


def test_PostgresqlCtfReaderUsesEnabledColumn(authTestEnv):
    reader = makeReader()

    row = reader._buildCtfRow(
        {
            "scipionItemId": 19,
            "enabled": False,
            "values": {
                "_defocusU": 20000,
                "_defocusV": 19000,
                "_enabled": True,
            },
        },
        position=0,
    )

    assert row["excluded"] is True


def test_PostgresqlCtfReaderRejectsCtftomoSet(authTestEnv):
    reader = makeReader()

    assert reader._isCtfStoredSet({
        "setClassName": "SetOfCTF",
        "itemClassName": "CTFModel",
    }) is True

    assert reader._isCtfStoredSet({
        "setClassName": "SetOfCTFTomoSeries",
        "itemClassName": "CTFTomoSeries",
    }) is False


def test_PostgresqlCtfReaderResolvesMicrographFromSourceRelation(
        authTestEnv,
        monkeypatch,
):
    reader = makeReader()

    monkeypatch.setattr(
        reader,
        "_getStoredSet",
        lambda: {
            "id": 33,
            "setClassName": "SetOfCTF",
            "itemClassName": "CTFModel",
        },
    )

    calls = []

    class MapperStub:
        def getStoredSetItemBySourceRelation(
                self,
                projectId,
                childSetId,
                scipionItemId,
        ):
            calls.append(
                (
                    projectId,
                    childSetId,
                    scipionItemId,
                )
            )

            return {
                "label": "mic_010",
                "values": {
                    "_filename": (
                        "Runs/000001_Import/"
                        "extra/mic_010.mrc"
                    ),
                },
            }

        def getStoredMicrographItemFromProtocolInputGraph(
                self,
                *args,
                **kwargs,
        ):
            raise AssertionError(
                "Input graph fallback should not be needed"
            )

    reader.setMapper = MapperStub()

    result = reader.getMicrographImageInfo(10)

    assert result == {
        "micrographId": "10",
        "micrographName": "mic_010",
        "fileName": (
            "Runs/000001_Import/"
            "extra/mic_010.mrc"
        ),
        "locationIndex": None,
    }

    assert calls == [
        (
            1,
            33,
            10,
        )
    ]


def test_PostgresqlCtfReaderFallsBackToProtocolInputGraph(
        authTestEnv,
        monkeypatch,
):
    reader = makeReader()

    monkeypatch.setattr(
        reader,
        "_getStoredSet",
        lambda: {
            "id": 33,
            "setClassName": "SetOfCTF",
            "itemClassName": "CTFModel",
        },
    )

    class MapperStub:
        def getStoredSetItemBySourceRelation(
                self,
                **kwargs,
        ):
            return None

        def getStoredMicrographItemFromProtocolInputGraph(
                self,
                projectId,
                protocolDbId,
                scipionItemId,
        ):
            assert projectId == 1
            assert protocolDbId == 500
            assert scipionItemId == 10

            return {
                "label": "mic_010",
                "values": {
                    "_location": (
                        "1@Runs/000001_Import/"
                        "extra/mic_stack.mrcs"
                    ),
                },
            }

    reader.setMapper = MapperStub()

    result = reader.getMicrographImageInfo(10)

    assert result["fileName"] == (
        "Runs/000001_Import/"
        "extra/mic_stack.mrcs"
    )
    assert result["locationIndex"] == 1