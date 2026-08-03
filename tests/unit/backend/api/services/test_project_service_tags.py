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

import pytest
from fastapi import HTTPException


class FakeDb:
    def __init__(self):
        self.fetchOneCalls = []
        self.protocolRows = []

    def addProtocol(self, projectId, protocolDbId, protocolId):
        self.protocolRows.append({
            "projectId": int(projectId),
            "id": int(protocolDbId),
            "protocolId": str(protocolId),
        })

    def fetchOne(self, query, params=None):
        self.fetchOneCalls.append({
            "query": query,
            "params": params,
        })

        if params is None or len(params) != 2:
            return None

        queryText = " ".join(str(query).split())

        if "FROM protocols" not in queryText:
            return None

        projectId, protocolIdCandidate = params
        projectId = int(projectId)

        if "AND id = %s" in queryText:
            try:
                protocolDbId = int(protocolIdCandidate)
            except (TypeError, ValueError):
                return None

            for row in self.protocolRows:
                if (
                        row["projectId"] == projectId
                        and row["id"] == protocolDbId
                ):
                    return {
                        "id": row["id"],
                        "protocolId": row["protocolId"],
                    }

            return None

        if 'AND "protocolId" = %s' in queryText:
            runtimeProtocolIdText = str(
                protocolIdCandidate
            )

            for row in self.protocolRows:
                if (
                        row["projectId"] == projectId
                        and row["protocolId"]
                        == runtimeProtocolIdText
                ):
                    return {
                        "id": row["id"],
                        "protocolId": row["protocolId"],
                    }

        return None

    def getRuntimeProtocolId(self, projectId, protocolDbId):
        for row in self.protocolRows:
            if row["projectId"] == int(projectId) and row["id"] == int(protocolDbId):
                return row["protocolId"]

        return str(protocolDbId)


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()
        self.protocolTagIdsByProtocolDbId = {}
        self.getProtocolTagIdsCalls = []
        self.setProtocolTagIdsByProtocolDbIdCalls = []
        self.setProtocolTagIdsCalls = []
        self.raiseOnGetProtocolTagIds = None
        self.raiseOnSetProtocolTagIdsByProtocolDbId = None
        self.projectTags = []

    def listProjectTags(self, projectId):
        return list(self.projectTags)

    def getProtocolTagIds(self, projectId, protocolDbId):
        self.getProtocolTagIdsCalls.append({
            "projectId": projectId,
            "protocolDbId": protocolDbId,
        })

        if self.raiseOnGetProtocolTagIds is not None:
            raise self.raiseOnGetProtocolTagIds

        return list(self.protocolTagIdsByProtocolDbId.get(int(protocolDbId), []))

    def setProtocolTagIdsByProtocolDbId(self, projectId, protocolDbId, tagIds):
        self.setProtocolTagIdsByProtocolDbIdCalls.append({
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "tagIds": list(tagIds or []),
        })

        if self.raiseOnSetProtocolTagIdsByProtocolDbId is not None:
            raise self.raiseOnSetProtocolTagIdsByProtocolDbId

        cleanTagIds = sorted({
            str(tagId).strip()
            for tagId in (tagIds or [])
            if str(tagId).strip()
        })

        self.protocolTagIdsByProtocolDbId[int(protocolDbId)] = cleanTagIds

        return {
            "protocolId": self.db.getRuntimeProtocolId(projectId, protocolDbId),
            "protocolDbId": int(protocolDbId),
            "tagIds": cleanTagIds,
        }

    def setProtocolTagIds(self, projectId, protocolId, tagIds):
        self.setProtocolTagIdsCalls.append({
            "projectId": projectId,
            "protocolId": protocolId,
            "tagIds": list(tagIds or []),
        })

        for row in self.db.protocolRows:
            if row["projectId"] == int(projectId) and row["protocolId"] == str(protocolId):
                return self.setProtocolTagIdsByProtocolDbId(
                    projectId=projectId,
                    protocolDbId=row["id"],
                    tagIds=tagIds,
                )

        raise Exception("Protocol not found in project")


class FakeMapperWithoutDbIdSetter(FakeMapper):
    setProtocolTagIdsByProtocolDbId = None

    def setProtocolTagIds(self, projectId, protocolId, tagIds):
        self.setProtocolTagIdsCalls.append({
            "projectId": projectId,
            "protocolId": protocolId,
            "tagIds": list(tagIds or []),
        })

        for row in self.db.protocolRows:
            if row["projectId"] == int(projectId) and row["protocolId"] == str(protocolId):
                cleanTagIds = sorted({
                    str(tagId).strip()
                    for tagId in (tagIds or [])
                    if str(tagId).strip()
                })

                self.protocolTagIdsByProtocolDbId[int(row["id"])] = cleanTagIds

                return {
                    "protocolId": str(row["protocolId"]),
                    "protocolDbId": int(row["id"]),
                    "tagIds": cleanTagIds,
                }

        raise Exception("Protocol not found in project")


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    return projectServiceModule.ProjectService()


@pytest.fixture
def mapper():
    return FakeMapper()


@pytest.fixture
def currentUser():
    return {"id": 1}


def test_ListProjectTagsUsesMapperProjectTags(service, mapper, currentUser):
    mapper.projectTags = [
        {
            "id": "good",
            "title": "Good particles",
            "description": None,
            "color": "#00ff00",
        },
        {
            "id": "bad",
            "title": "Bad particles",
            "description": "Rejected items",
            "color": "#ff0000",
        },
    ]

    result = service.listProjectTags(
        mapper=mapper,
        projectId=1,
        currentUser=currentUser,
    )

    assert result == mapper.projectTags


def test_ListProtocolTagsResolvesPostgresqlProtocolDbId(
    service,
    mapper,
    currentUser,
):
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)
    mapper.protocolTagIdsByProtocolDbId[500] = ["good", "selected"]

    result = service.listProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        currentUser=currentUser,
    )

    assert result == {
        "protocolId": "500",
        "protocolDbId": 500,
        "tagIds": ["good", "selected"],
    }

    assert mapper.getProtocolTagIdsCalls == [
        {
            "projectId": 1,
            "protocolDbId": 500,
        }
    ]

    assert [
               call["params"]
               for call in mapper.db.fetchOneCalls
           ] == [
               (
                   1,
                   "500",
               ),
               (
                   1,
                   500,
               ),
           ]


def test_ListProtocolTagsAlsoAcceptsRuntimeProtocolId(
    service,
    mapper,
    currentUser,
):
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)
    mapper.protocolTagIdsByProtocolDbId[500] = ["movie-alignment"]

    result = service.listProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        currentUser=currentUser,
    )

    assert result == {
        "protocolId": "10",
        "protocolDbId": 500,
        "tagIds": ["movie-alignment"],
    }

    assert mapper.getProtocolTagIdsCalls == [
        {
            "projectId": 1,
            "protocolDbId": 500,
        }
    ]

    assert mapper.db.fetchOneCalls[0]["params"] == (1, "10")


def test_ListProtocolTagsRaises404WhenProtocolCannotBeResolved(
    service,
    mapper,
    currentUser,
):
    with pytest.raises(HTTPException) as exc:
        service.listProtocolTags(
            mapper=mapper,
            projectId=1,
            protocolId=999,
            currentUser=currentUser,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Protocol not found in PostgreSQL: 999"
    assert mapper.getProtocolTagIdsCalls == []


def test_ListProtocolTagsWrapsMapperErrors(
    service,
    mapper,
    currentUser,
):
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)
    mapper.raiseOnGetProtocolTagIds = RuntimeError("database error")

    with pytest.raises(HTTPException) as exc:
        service.listProtocolTags(
            mapper=mapper,
            projectId=1,
            protocolId=500,
            currentUser=currentUser,
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to list protocol tags: database error"

    assert mapper.getProtocolTagIdsCalls == [
        {
            "projectId": 1,
            "protocolDbId": 500,
        }
    ]


def test_SetProtocolTagsResolvesPostgresqlProtocolDbId(
    service,
    mapper,
    currentUser,
):
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)

    result = service.setProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        tagIds=[" selected ", "good", "good", ""],
        currentUser=currentUser,
    )

    assert result == {
        "protocolId": "10",
        "protocolDbId": 500,
        "tagIds": ["good", "selected"],
    }

    assert mapper.setProtocolTagIdsByProtocolDbIdCalls == [
        {
            "projectId": 1,
            "protocolDbId": 500,
            "tagIds": [" selected ", "good", "good", ""],
        }
    ]

    assert mapper.setProtocolTagIdsCalls == []
    assert mapper.protocolTagIdsByProtocolDbId[500] == ["good", "selected"]
    assert [
               call["params"]
               for call in mapper.db.fetchOneCalls
           ] == [
               (
                   1,
                   "500",
               ),
               (
                   1,
                   500,
               ),
           ]


def test_SetProtocolTagsAlsoAcceptsRuntimeProtocolId(
    service,
    mapper,
    currentUser,
):
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)

    result = service.setProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        tagIds=["movie-alignment"],
        currentUser=currentUser,
    )

    assert result == {
        "protocolId": "10",
        "protocolDbId": 500,
        "tagIds": ["movie-alignment"],
    }

    assert mapper.setProtocolTagIdsByProtocolDbIdCalls == [
        {
            "projectId": 1,
            "protocolDbId": 500,
            "tagIds": ["movie-alignment"],
        }
    ]

    assert mapper.setProtocolTagIdsCalls == []
    assert mapper.db.fetchOneCalls[0]["params"] == (1, "10")


def test_SetProtocolTagsRaises404WhenProtocolCannotBeResolved(
    service,
    mapper,
    currentUser,
):
    with pytest.raises(HTTPException) as exc:
        service.setProtocolTags(
            mapper=mapper,
            projectId=1,
            protocolId=999,
            tagIds=["good"],
            currentUser=currentUser,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Protocol not found in PostgreSQL: 999"
    assert mapper.setProtocolTagIdsByProtocolDbIdCalls == []
    assert mapper.setProtocolTagIdsCalls == []


def test_SetProtocolTagsWrapsMapperErrors(
    service,
    mapper,
    currentUser,
):
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)
    mapper.raiseOnSetProtocolTagIdsByProtocolDbId = RuntimeError("write failed")

    with pytest.raises(HTTPException) as exc:
        service.setProtocolTags(
            mapper=mapper,
            projectId=1,
            protocolId=500,
            tagIds=["good"],
            currentUser=currentUser,
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to set protocol tags: write failed"

    assert mapper.setProtocolTagIdsByProtocolDbIdCalls == [
        {
            "projectId": 1,
            "protocolDbId": 500,
            "tagIds": ["good"],
        }
    ]


def test_SetProtocolTagsFallsBackToRuntimeSetterWhenDbIdSetterIsMissing(
    projectServiceModule,
    currentUser,
):
    service = projectServiceModule.ProjectService()
    mapper = FakeMapperWithoutDbIdSetter()
    mapper.db.addProtocol(projectId=1, protocolDbId=500, protocolId=10)

    result = service.setProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        tagIds=["good"],
        currentUser=currentUser,
    )

    assert result == {
        "protocolId": "10",
        "protocolDbId": 500,
        "tagIds": ["good"],
    }

    assert mapper.setProtocolTagIdsCalls == [
        {
            "projectId": 1,
            "protocolId": 10,
            "tagIds": ["good"],
        }
    ]