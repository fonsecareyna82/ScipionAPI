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
import os
from pathlib import Path

import pytest


class FakeManager:
    # fakeManager
    def __init__(self, projectsRoot):
        self.PROJECTS = str(projectsRoot)

    def getProjectPath(self, name):
        return str(Path(self.PROJECTS) / name)


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def projectService(projectServiceModule, tmp_path):
    # projectService
    projectsRoot = tmp_path / "projects"
    projectsRoot.mkdir(parents=True, exist_ok=True)

    service = object.__new__(projectServiceModule.ProjectService)
    service.manager = FakeManager(projectsRoot)
    service.objectManager = None
    return service


def test_SanitizeProjectNameReturnsFallbackForNone(projectServiceModule):
    assert projectServiceModule.ProjectService.sanitizeProjectName(None) == "project"


def test_SanitizeProjectNameStripsWhitespaceAndInvalidChars(projectServiceModule):
    value = projectServiceModule.ProjectService.sanitizeProjectName("  my project / v1  ")
    assert value == "my_project_v1"


def test_SanitizeProjectNameCollapsesUnderscores(projectServiceModule):
    value = projectServiceModule.ProjectService.sanitizeProjectName("a***b   c")
    assert value == "a_b_c"


def test_SanitizeProjectNameStripsLeadingDotsAndUnderscores(projectServiceModule):
    value = projectServiceModule.ProjectService.sanitizeProjectName(".___demo.__")
    assert value == "demo"


def test_NormalizeProjectPathKeepsAbsolutePath(projectService, tmp_path):
    absolutePath = tmp_path / "somewhere" / "project-a"
    normalized = projectService._normalizeProjectPath(str(absolutePath))

    assert normalized == os.path.abspath(str(absolutePath))


def test_NormalizeProjectPathResolvesRelativeWithManager(projectService):
    normalized = projectService._normalizeProjectPath("demo-project")

    assert normalized == os.path.abspath(
        os.path.join(projectService.manager.PROJECTS, "demo-project")
    )


def test_IsManagedProjectPathReturnsTrueForManagedEntry(projectService):
    managedPath = os.path.join(projectService.manager.PROJECTS, "demo-project")

    assert projectService._isManagedProjectPath(managedPath) is True


def test_IsManagedProjectPathReturnsFalseForExternalEntry(projectService, tmp_path):
    externalPath = tmp_path / "external" / "demo-project"

    assert projectService._isManagedProjectPath(str(externalPath)) is False


def test_IsManagedProjectPathTreatsSymlinkEntryInsideWorkspaceAsManaged(projectService, tmp_path):
    externalTarget = tmp_path / "external-target"
    externalTarget.mkdir(parents=True, exist_ok=True)

    symlinkEntry = Path(projectService.manager.PROJECTS) / "linked-project"
    symlinkEntry.symlink_to(externalTarget, target_is_directory=True)

    assert projectService._isManagedProjectPath(str(symlinkEntry)) is True


def test_IsLinkedProjectPathReturnsTrueForSymlink(projectService, tmp_path):
    target = tmp_path / "target-project"
    target.mkdir(parents=True, exist_ok=True)

    linkPath = Path(projectService.manager.PROJECTS) / "linked-project"
    linkPath.symlink_to(target, target_is_directory=True)

    assert projectService._isLinkedProjectPath(str(linkPath)) is True


def test_IsLinkedProjectPathReturnsFalseForRegularDirectory(projectService):
    projectDir = Path(projectService.manager.PROJECTS) / "normal-project"
    projectDir.mkdir(parents=True, exist_ok=True)

    assert projectService._isLinkedProjectPath(str(projectDir)) is False


def test_CountProtocolsCountsOnlyDirectories(projectServiceModule, tmp_path):
    runsDir = tmp_path / "Runs"
    runsDir.mkdir(parents=True, exist_ok=True)

    (runsDir / "000001_ProtImport").mkdir()
    (runsDir / "000002_ProtCTF").mkdir()
    (runsDir / "notes.txt").write_text("not a protocol directory", encoding="utf-8")

    count = projectServiceModule.ProjectService.countProtocols(str(runsDir))

    assert count == 2


def test_CountProtocolsReturnsZeroWhenPathDoesNotExist(projectServiceModule, tmp_path):
    missingRuns = tmp_path / "MissingRuns"

    count = projectServiceModule.ProjectService.countProtocols(str(missingRuns))

    assert count == 0


def test_BuildProjectThumbnailVersionUsesRunsMtime(projectServiceModule, tmp_path):
    projectPath = tmp_path / "project-a"
    runsPath = projectPath / "Runs"
    runsPath.mkdir(parents=True, exist_ok=True)

    version = projectServiceModule.ProjectService._buildProjectThumbnailVersion(
        projectPath=str(projectPath),
        projectId=7,
        updatedAt="2026-04-15T10:00:00",
        protocolsCount=3,
    )

    assert version.startswith("7:2026-04-15T10:00:00:3:")
    assert version.split(":")[-1].isdigit()


def test_BuildProjectThumbnailVersionUsesZeroWhenRunsMissing(projectServiceModule, tmp_path):
    projectPath = tmp_path / "project-b"
    projectPath.mkdir(parents=True, exist_ok=True)

    version = projectServiceModule.ProjectService._buildProjectThumbnailVersion(
        projectPath=str(projectPath),
        projectId=8,
        updatedAt=None,
        protocolsCount=0,
    )

    assert version == "8::0:0"


def test_GetProtocolColorReturnsKnownStatusColor(projectServiceModule):
    color = projectServiceModule.ProjectService.getProtocolColor("finished")
    assert color == "#D2F5CB"


def test_GetProtocolColorReturnsDefaultColorForUnknownStatus(projectServiceModule):
    color = projectServiceModule.ProjectService.getProtocolColor("something-else")
    assert color == "#9e9e9e"


def test_ProjectThumbnailUrlsAreBuiltAsExpected(projectServiceModule):
    assert projectServiceModule.ProjectService.buildProjectThumbnailUrl(3) == "/projects/3/thumbnail"
    assert projectServiceModule.ProjectService.buildProjectThumbnailRebuildUrl(3) == "/projects/3/thumbnail/rebuild"
    assert projectServiceModule.ProjectService.buildProjectThumbnailItemsUrl(3) == "/projects/3/thumbnail-items"


def test_ProtocolThumbnailUrlsAreBuiltAsExpected(projectServiceModule):
    assert (
        projectServiceModule.ProjectService.buildProtocolThumbnailUrl(3, 11)
        == "/projects/3/protocols/11/thumbnail"
    )
    assert (
        projectServiceModule.ProjectService.buildProtocolThumbnailRebuildUrl(3, 11)
        == "/projects/3/protocols/11/thumbnail/rebuild"
    )
    assert (
        projectServiceModule.ProjectService.buildProtocolOutputThumbnailUrl(3, 11, "outputParticles")
        == "/projects/3/protocols/11/outputs/outputParticles/thumbnail"
    )


def test_GetContextMenuVisibilityPolicyReturnsAllExpectedFlags(projectService):
    policy = projectService.getContextMenuVisibilityPolicy()

    expectedKeys = {
        "open",
        "browse",
        "rename",
        "duplicate",
        "copyWorkflow",
        "pasteWorkflow",
        "delete",
        "restart",
        "continue",
        "reset",
        "stop",
        "selectFrom",
        "selectTo",
        "manageTags",
        "export",
        "upload",
        "nextSteps",
    }

    assert set(policy.keys()) == expectedKeys
    assert all(value is True for value in policy.values())


def test_IsGlobalFsBrowserModeRecognizesMinusOne(projectService):
    assert projectService._isGlobalFsBrowserMode("-1") is True
    assert projectService._isGlobalFsBrowserMode(123) is False


def test_GetGlobalFsBrowserRootUsesEnvironment(projectService, monkeypatch, tmp_path):
    browserRoot = tmp_path / "browser-root"
    browserRoot.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(browserRoot))

    resolved = projectService._getGlobalFsBrowserRoot()

    assert resolved == browserRoot.resolve()


def test_PostgresqlReadFallbackIsDisabledByDefault(
        projectServiceModule,
        monkeypatch,
):
    monkeypatch.delenv(
        "SCIPIONWEB_ENABLE_SQLITE_READ_FALLBACK",
        raising=False,
    )

    assert (
        projectServiceModule.ProjectService
        ._shouldEnablePostgresqlReadFallback()
        is False
    )


@pytest.mark.parametrize(
    "value",
    [
        "1",
        "true",
        "TRUE",
        " yes ",
        "on",
    ],
)
def test_PostgresqlReadFallbackCanBeEnabledExplicitly(
        projectServiceModule,
        monkeypatch,
        value,
):
    monkeypatch.setenv(
        "SCIPIONWEB_ENABLE_SQLITE_READ_FALLBACK",
        value,
    )

    assert (
        projectServiceModule.ProjectService
        ._shouldEnablePostgresqlReadFallback()
        is True
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0",
        "false",
        "no",
        "off",
        "whatever",
    ],
)
def test_PostgresqlReadFallbackRejectsFalseValues(
        projectServiceModule,
        monkeypatch,
        value,
):
    monkeypatch.setenv(
        "SCIPIONWEB_ENABLE_SQLITE_READ_FALLBACK",
        value,
    )

    assert (
        projectServiceModule.ProjectService
        ._shouldEnablePostgresqlReadFallback()
        is False
    )


def test_LoadPostgresqlRuntimeProjectForMutationDisablesReadFallbackByDefault(
        projectService,
        projectServiceModule,
        monkeypatch,
        tmp_path,
):
    projectPath = tmp_path / "runtime-project"
    projectPath.mkdir()

    captured = {}

    class FakePostgresqlProject:
        def __init__(
                self,
                domain,
                path,
                projectId,
                flatMapper,
                enableReadFallback,
                enableWriteFallback,
        ):
            captured.update({
                "domain": domain,
                "path": path,
                "projectId": projectId,
                "flatMapper": flatMapper,
                "enableReadFallback": enableReadFallback,
                "enableWriteFallback": enableWriteFallback,
            })

        def load(self, chdir=False):
            captured["loadChdir"] = chdir

        def closeMapper(self):
            captured["closed"] = True

    monkeypatch.delenv(
        "SCIPIONWEB_ENABLE_SQLITE_READ_FALLBACK",
        raising=False,
    )

    monkeypatch.setattr(
        projectServiceModule,
        "PostgresqlProject",
        FakePostgresqlProject,
    )

    monkeypatch.setattr(
        projectServiceModule.pyworkflow.Config,
        "getDomain",
        lambda: "test-domain",
    )

    projectService.getProjectDbRow = lambda **kwargs: {
        "id": 7,
        "name": str(projectPath),
    }

    mapper = object()

    result = (
        projectService
        .loadPostgresqlRuntimeProjectForMutation(
            mapper=mapper,
            projectId=7,
            currentUser={"id": 3},
            enableWriteFallback=True,
        )
    )

    assert result == {
        "id": 7,
        "name": str(projectPath),
    }

    assert captured == {
        "domain": "test-domain",
        "path": str(projectPath),
        "projectId": 7,
        "flatMapper": mapper,
        "enableReadFallback": False,
        "enableWriteFallback": True,
        "loadChdir": True,
    }

    assert (
        projectService.currentProject.__class__
        is FakePostgresqlProject
    )


