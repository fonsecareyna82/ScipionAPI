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
from contextlib import contextmanager

from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)


class FakeCursor:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class FakeDatabase:
    def __init__(
            self,
            deletedSet=None,
            sharedSet=None,
            deletedRelationsCount=0,
            deletedObjectsCount=0,
    ):
        self.deletedSet = deletedSet
        self.sharedSet = sharedSet
        self.deletedRelationsCount = deletedRelationsCount
        self.deletedObjectsCount = deletedObjectsCount

        self.calls = []
        self.transactionCalls = 0

    @contextmanager
    def transaction(self):
        self.transactionCalls += 1
        yield self

    def fetchOne(
            self,
            query,
            values,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.calls.append({
            "operation": "fetchOne",
            "query": normalizedQuery,
            "values": values,
        })

        if normalizedQuery.startswith(
                "DELETE FROM scipion_sets"
        ):
            return (
                dict(self.deletedSet)
                if self.deletedSet is not None
                else None
            )

        if normalizedQuery.startswith(
                "SELECT id FROM scipion_sets"
        ):
            return (
                dict(self.sharedSet)
                if self.sharedSet is not None
                else None
            )

        return None

    def execute(
            self,
            query,
            values,
            commit=True,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.calls.append({
            "operation": "execute",
            "query": normalizedQuery,
            "values": values,
            "commit": commit,
        })

        if normalizedQuery.startswith(
                "DELETE FROM scipion_relations"
        ):
            return FakeCursor(
                self.deletedRelationsCount
            )

        if normalizedQuery.startswith(
                "DELETE FROM scipion_objects"
        ):
            return FakeCursor(
                self.deletedObjectsCount
            )

        return FakeCursor()


def test_DeleteStoredSetOutputDeletesCompleteRepresentation():
    database = FakeDatabase(
        deletedSet={
            "id": 31,
            "objectId": 900,
        },
        deletedRelationsCount=2,
        deletedObjectsCount=1,
    )

    mapper = ScipionSetPostgresqlMapper(
        database
    )

    result = mapper.deleteStoredSetOutput(
        projectId=7,
        setId=31,
        objectId=900,
        runtimeObjectId=700,
    )

    assert result == {
        "deletedSetsCount": 1,
        "deletedObjectsCount": 1,
        "deletedRelationsCount": 2,
    }

    assert database.transactionCalls == 1
    assert len(database.calls) == 4

    assert database.calls[0]["values"] == (
        31,
        7,
        900,
    )

    assert database.calls[1]["values"] == (
        900,
    )

    assert database.calls[2]["values"] == (
        7,
        700,
        700,
        700,
    )

    assert database.calls[2]["commit"] is False

    assert database.calls[3]["values"] == (
        900,
        7,
        700,
    )

    assert database.calls[3]["commit"] is False


def test_DeleteStoredSetOutputRejectsSharedCanonicalRoot():
    database = FakeDatabase(
        deletedSet={
            "id": 31,
            "objectId": 900,
        },
        sharedSet={
            "id": 32,
        },
    )

    mapper = ScipionSetPostgresqlMapper(
        database
    )

    try:
        mapper.deleteStoredSetOutput(
            projectId=7,
            setId=31,
            objectId=900,
            runtimeObjectId=700,
        )
    except RuntimeError as error:
        assert str(error) == (
            "Cannot delete PostgreSQL Set 31 because "
            "canonical object 900 is still referenced "
            "by Set 32."
        )
    else:
        raise AssertionError(
            "Expected shared canonical Set root "
            "to raise RuntimeError"
        )

    assert len(database.calls) == 2



def test_DeleteStoredSetOutputRejectsMissingStoredSet():
    database = FakeDatabase(
        deletedSet=None,
    )

    mapper = ScipionSetPostgresqlMapper(
        database
    )

    try:
        mapper.deleteStoredSetOutput(
            projectId=7,
            setId=31,
            objectId=900,
            runtimeObjectId=700,
        )
    except RuntimeError as error:
        assert str(error) == (
            "Could not delete PostgreSQL Set 31 "
            "with canonical object 900."
        )
    else:
        raise AssertionError(
            "Expected missing PostgreSQL Set deletion "
            "to raise RuntimeError"
        )

    assert database.transactionCalls == 1
    assert len(database.calls) == 1