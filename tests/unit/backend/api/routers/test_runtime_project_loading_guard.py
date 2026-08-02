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
import ast
from pathlib import Path
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[5]

SCANNED_ROOTS = (
    PROJECT_ROOT / "app" / "backend" / "api" / "routers",
    PROJECT_ROOT / "app" / "backend" / "api" / "services",
    PROJECT_ROOT / "app" / "backend" / "runtime",
)


FORBIDDEN_LEGACY_PROJECT_LOAD_CALLS = {
    "loadProjectRuntimeContext",
}

RETIRED_PROJECT_LOADING_KEYWORDS = {
    "loadWorkflowFromPostgresql",
    "usePostgresqlRuntimeProject",
}


ALLOWED_PROJECT_DB_LOADS = {
    (
        "app/backend/api/services/project_service.py",
        "_validateImportableScipionProject",
    ),
    (
        "app/backend/api/services/project_service.py",
        "_loadLegacyProjectForImport",
    ),
    (
        "app/backend/api/services/project_consistency_service.py",
        "_loadLegacyProjectForConsistency",
    ),
}


def _getKeywordValue(call: ast.Call, keywordName: str) -> Optional[ast.AST]:
    for keyword in call.keywords:
        if keyword.arg == keywordName:
            return keyword.value

    return None


def _getCalledFunctionName(call: ast.Call) -> Optional[str]:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    if isinstance(call.func, ast.Name):
        return call.func.id

    return None


class ProjectRouteLoadingVisitor(ast.NodeVisitor):
    def __init__(self, relativePath: str):
        self.relativePath = relativePath
        self.functionStack: List[str] = []
        self.violations: List[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.functionStack.append(node.name)

        try:
            self.generic_visit(node)
        finally:
            self.functionStack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.functionStack.append(node.name)

        try:
            self.generic_visit(node)
        finally:
            self.functionStack.pop()

    def visit_Call(self, node: ast.Call):
        callName = _getCalledFunctionName(node)
        functionName = self.functionStack[-1] if self.functionStack else "<module>"
        location = self.relativePath, functionName
        if callName in {"getProjectById", "getProjectByIdCallback"}:
            usesRetiredKeyword = any(
                keyword.arg in RETIRED_PROJECT_LOADING_KEYWORDS
                for keyword in node.keywords
            )

            if usesRetiredKeyword:
                self.violations.append(
                    f"{self.relativePath}:{node.lineno}:{functionName}"
                )


        if callName in FORBIDDEN_LEGACY_PROJECT_LOAD_CALLS:
            self.violations.append(
                f"{self.relativePath}:{node.lineno}:{functionName}"
            )

        if callName == "loadProject":
            self.violations.append(
                f"{self.relativePath}:{node.lineno}:{functionName}"
            )

        if (
                callName == "load"
                and _getKeywordValue(node, "dbPath") is not None
                and location not in ALLOWED_PROJECT_DB_LOADS
        ):
            self.violations.append(
                f"{self.relativePath}:{node.lineno}:{functionName}"
            )

        self.generic_visit(node)


def _findUnsafeProjectLoads(source: str, relativePath: str) -> List[str]:
    tree = ast.parse(source, filename=relativePath)
    visitor = ProjectRouteLoadingVisitor(relativePath)
    visitor.visit(tree)

    return visitor.violations


def test_ProjectRuntimeLoadingGuardRejectsRemovedRuntimeContextLoader():
    source = """
def unsafeRuntime(service):
    return service.loadProjectRuntimeContext({})
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="unsafe_runtime.py",
    ) == [
        "unsafe_runtime.py:3:unsafeRuntime",
    ]


def test_ProjectRuntimeLoadingGuardRejectsRetiredProjectLoadingSwitches():
    source = """
def refreshWorkflow(service):
    return service.getProjectById(None, 1, {}, loadWorkflowFromPostgresql=True)


def refreshRuntime(getProjectByIdCallback):
    return getProjectByIdCallback(None, 1, {}, usePostgresqlRuntimeProject=True)
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="unsafe_runtime.py",
    ) == [
        "unsafe_runtime.py:3:refreshWorkflow",
        "unsafe_runtime.py:7:refreshRuntime",
    ]


def test_ProjectRuntimeLoadingGuardRejectsDirectProjectDbLoad():
    source = """
def unsafeRuntime(project):
    project.load(dbPath=project.getDbPath())
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="unsafe_service.py",
    ) == [
        "unsafe_service.py:3:unsafeRuntime",
    ]


def test_ProjectRuntimeLoadingGuardRejectsLegacyProjectLoader():
    source = """
def unsafeRuntime(service):
    return service.loadProject({})
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="unsafe_service.py",
    ) == [
        "unsafe_service.py:3:unsafeRuntime",
    ]


def test_ProjectRuntimeLoadingGuardAllowsPostgresqlProjectLoads():
    source = """
def refreshWorkflow(service):
    return service.getProjectById(
        None,
        1,
        {},
    )


def refreshRuntime(getProjectByIdCallback):
    return getProjectByIdCallback(
        None,
        1,
        {},
    )
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="postgresql_runtime.py",
    ) == []


def test_ProjectRuntimeLoadingGuardAllowsApprovedLegacyProjectDbLoads():
    projectServiceSource = """
def _validateImportableScipionProject(project):
    project.load(dbPath=project.getDbPath())


def _loadLegacyProjectForImport(project):
    project.load(dbPath=project.getDbPath())
"""

    assert _findUnsafeProjectLoads(
        source=projectServiceSource,
        relativePath="app/backend/api/services/project_service.py",
    ) == []

    consistencyServiceSource = """
def _loadLegacyProjectForConsistency(project, legacyDbPath):
    project.load(dbPath=str(legacyDbPath))
"""

    assert _findUnsafeProjectLoads(
        source=consistencyServiceSource,
        relativePath=(
            "app/backend/api/services/"
            "project_consistency_service.py"
        ),
    ) == []


def test_ProjectRuntimeLayersDoNotUseUnsafeLegacyProjectLoads():
    violations: List[str] = []

    for sourceRoot in SCANNED_ROOTS:
        for sourcePath in sorted(sourceRoot.rglob("*.py")):
            relativePath = sourcePath.relative_to(PROJECT_ROOT).as_posix()
            source = sourcePath.read_text(encoding="utf-8")

            violations.extend(
                _findUnsafeProjectLoads(
                    source=source,
                    relativePath=relativePath,
                )
            )

    assert not violations, (
            "Unsafe legacy project loads were found in API or runtime code.\n"
            "Runtime operations must use loadPostgresqlRuntimeProjectForMutation(), "
            "getProjectDbRow(), or PostgreSQL project loaders.\n"
            "Retired getProjectById loading switches must not be passed.\n"
            "Direct loadProject() calls are forbidden.\n"
            "Direct load(dbPath=...) calls are forbidden outside "
            "their approved legacy boundaries.\n"
            "loadProjectRuntimeContext() must not be restored.\n"
            + "\n".join(violations)
    )