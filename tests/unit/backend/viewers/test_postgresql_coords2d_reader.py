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
from app.backend.viewers.postgresql_coords2d_reader import PostgresqlCoords2dReader


def make_reader(stored_set):
    reader = PostgresqlCoords2dReader(
        db=None,
        projectId=1,
        protocolId=2,
        outputName="coordinates",
    )
    reader._storedSet = stored_set
    return reader


def test_PostgresqlCoords2dReaderListsMicrographs():
    reader = make_reader(
        {
            "setClassName": "SetOfCoordinates",
            "itemClassName": "Coordinate",
            "properties": {"boxSize": 128},
            "items": [
                {
                    "scipionItemId": 1,
                    "values": {
                        "_micId": 10,
                        "_x": 11.5,
                        "_y": 22.5,
                    },
                },
                {
                    "scipionItemId": 2,
                    "values": {
                        "_micId": 10,
                        "_x": 12.5,
                        "_y": 23.5,
                    },
                },
                {
                    "scipionItemId": 3,
                    "values": {
                        "_micId": 20,
                        "_x": 5.0,
                        "_y": 6.0,
                    },
                },
            ],
        }
    )

    payload = reader.listMicrographs()

    assert payload == {
        "micrographs": [
            {
                "id": "10",
                "index": 1,
                "fileName": "",
                "label": "Micrograph 10",
                "particles": 2,
                "updated": False,
                "width": None,
                "height": None,
                "locationIndex": None,
                "thumbnailUrl": None,
            },
            {
                "id": "20",
                "index": 2,
                "fileName": "",
                "label": "Micrograph 20",
                "particles": 1,
                "updated": False,
                "width": None,
                "height": None,
                "locationIndex": None,
                "thumbnailUrl": None,
            },
        ],
        "totalMicrographs": 2,
        "totalPicks": 3,
        "boxSize": 128,
    }


def test_PostgresqlCoords2dReaderListsCoordinatesForMicrograph():
    reader = make_reader(
        {
            "setClassName": "SetOfCoordinates",
            "itemClassName": "Coordinate",
            "items": [
                {
                    "scipionItemId": 1,
                    "values": {
                        "_micId": 10,
                        "_x": 11.5,
                        "_y": 22.5,
                        "_score": 0.9,
                        "_classId": 2,
                    },
                },
                {
                    "scipionItemId": 2,
                    "values": {
                        "_micId": 20,
                        "_x": 5.0,
                        "_y": 6.0,
                    },
                },
            ],
        }
    )

    payload = reader.listCoordinatesForMicrograph("10")

    assert payload == {
        "coordinates": [
            {
                "id": 1,
                "micId": "10",
                "x": 11.5,
                "y": 22.5,
                "score": 0.9,
                "classLabel": "2",
            }
        ]
    }


def test_PostgresqlCoords2dReaderRejectsCoords3dStoredSet():
    reader = make_reader(
        {
            "setClassName": "SetOfCoordinates3D",
            "itemClassName": "Coordinate3D",
            "items": [],
        }
    )

    assert reader.hasOutput() is False


class FakeMicrographDb:
    def fetchOne(self, query, params=None):
        normalizedQuery = " ".join(str(query).split())

        if "FROM scipion_sets stored_set" not in normalizedQuery:
            return None

        if int(params[-1]) != 10:
            return None

        return {
            "scipionItemId": 10,
            "label": "Micrograph 10",
            "comment": "",
            "values": {
                "_location._index": 1,
                "_location._filename": "Runs/000001_Import/extra/micrograph_10.mrc",
                "_micName": "micrograph_10",
            },
            "outputName": "outputMicrographs",
            "protocolId": "1",
        }


def test_PostgresqlCoords2dReaderResolvesLinkedMicrographImage():
    reader = PostgresqlCoords2dReader(
        db=FakeMicrographDb(),
        projectId=1,
        protocolId=2,
        outputName="coordinates",
    )

    reader._storedSet = {
        "setClassName": "SetOfCoordinates",
        "itemClassName": "Coordinate",
        "properties": {
            "_micrographsPointer": {
                "version": 1,
                "kind": "pointer",
                "targetObjectId": 3000000050,
                "targetParentObjectId": 1,
                "targetObjectName": "1.outputMicrographs",
                "targetClassName": "SetOfMicrographs",
                "extended": "",
            },
        },
        "items": [],
    }

    result = reader.getMicrographImageInfo("10")

    assert result == {
        "id": "10",
        "fileName": "Runs/000001_Import/extra/micrograph_10.mrc",
        "locationIndex": 1,
        "label": "micrograph_10",
    }

