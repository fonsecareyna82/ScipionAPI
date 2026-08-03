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
from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository


class DatabaseStub:
    def __init__(self):
        self.calls = []

    def fetchOne(self, query, params=None):
        queryText = " ".join(str(query).split())

        self.calls.append({
            "query": queryText,
            "params": params,
        })

        return {
            "projects": "1",
            "protocols": "2",
            "dependencies": "3",
            "inputRefs": "4",
            "steps": "5",
            "outputs": "6",
            "objects": "7",
            "sets": "8",
            "setItems": "9",
            "relations": "10",
        }


class MapperStub:
    def __init__(self):
        self.db = DatabaseStub()


def test_GetProjectRuntimeResourceCounts():
    mapper = MapperStub()

    result = ProjectRuntimeRepository().getProjectRuntimeResourceCounts(mapper=mapper, projectId=7)

    assert result == {
        "projects": 1,
        "protocols": 2,
        "dependencies": 3,
        "inputRefs": 4,
        "steps": 5,
        "outputs": 6,
        "objects": 7,
        "sets": 8,
        "setItems": 9,
        "relations": 10,
    }

    assert len(mapper.db.calls) == 1

    call = mapper.db.calls[0]

    assert call["params"] == (7,) * 10

    query = call["query"]

    assert "FROM projects" in query
    assert "FROM protocols" in query
    assert "FROM protocol_dependencies" in query
    assert "FROM protocol_input_refs" in query
    assert "FROM protocol_steps" in query
    assert "FROM scipion_objects" in query
    assert '"parentObjectId" IS NULL' in query
    assert "FROM scipion_sets" in query
    assert "FROM scipion_set_items set_item" in query
    assert 'stored_set.id = set_item."setId"' in query
    assert "FROM scipion_relations" in query

