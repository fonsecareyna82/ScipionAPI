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
from app.backend.project.postgresql_project import (
    PostgresqlProject,
)


class FakeRuntimeMapper:
    def __init__(self, labels=None):
        self.labels = list(labels or [])
        self.labelCalls = 0

    def getPostgresqlProtocolLabels(self):
        self.labelCalls += 1
        return list(self.labels)


class FakeProtocol:
    CLASS_LABEL = "Import movies"

    def __init__(
            self,
            project=None,
            objLabel=None,
    ):
        self._project = project
        self._mapper = None
        self._objLabel = objLabel or ""

    def getClassLabel(self):
        return self.CLASS_LABEL

    def getObjLabel(self):
        return self._objLabel

    def setObjLabel(self, value):
        self._objLabel = value

    def setMapper(self, mapper):
        self._mapper = mapper

    def getMapper(self):
        return self._mapper

    def setProject(self, project):
        self._project = project

    def getProject(self):
        return self._project


def buildProject(labels=None):
    project = object.__new__(
        PostgresqlProject
    )

    project.mapper = FakeRuntimeMapper(
        labels
    )

    project.usingPostgresqlRuntimeMapper = (
        lambda: True
    )

    return project


def test_NewProtocolCalculatesLabelFromPostgresql():
    project = buildProject([
        "Import movies",
        "Import movies (2)",
        "Import particles",
        "Import movies (4)",
    ])

    protocol = project.newProtocol(
        FakeProtocol
    )

    assert protocol.getObjLabel() == (
        "Import movies (5)"
    )

    assert protocol.getMapper() is (
        project.mapper
    )

    assert protocol.getProject() is project
    assert project.mapper.labelCalls == 1


def test_NewProtocolUsesDefaultLabelWhenNoMatchingProtocolExists():
    project = buildProject([
        "Import particles",
    ])

    protocol = project.newProtocol(
        FakeProtocol
    )

    assert protocol.getObjLabel() == (
        "Import movies"
    )

    assert project.mapper.labelCalls == 1


def test_NewProtocolPreservesExplicitLabel():
    project = buildProject([
        "Import movies",
        "Import movies (2)",
    ])

    protocol = project.newProtocol(
        FakeProtocol,
        objLabel="My custom import",
    )

    assert protocol.getObjLabel() == (
        "My custom import"
    )

    # Existing explicit labels do not require reading other labels.
    assert project.mapper.labelCalls == 0