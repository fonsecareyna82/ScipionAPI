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
ROUTERS_ROOT = PROJECT_ROOT / "app" / "backend" / "api" / "routers"

ALLOWED_DYNAMIC_LOADS = {
    ("project_router.py", "getProject"),
}


def _getKeywordValue(call: ast.Call, keywordName: str) -> Optional[ast.AST]:
    for keyword in call.keywords:
        if keyword.arg == keywordName:
            return keyword.value

    return None


def _isExplicitPostgresqlWorkflowLoad(value: Optional[ast.AST]) -> bool:
    return isinstance(value, ast.Constant) and value.value is True


def _isAllowedConsistencyLoad(
        relativePath: str,
        functionName: str,
        value: Optional[ast.AST],
) -> bool:
    if (relativePath, functionName) not in ALLOWED_DYNAMIC_LOADS:
        return False

    return (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, ast.Not)
        and isinstance(value.operand, ast.Name)
        and value.operand.id == "validateConsistency"
    )


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
        isGetProjectByIdCall = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "getProjectById"
        )

        if isGetProjectByIdCall:
            functionName = self.functionStack[-1] if self.functionStack else "<module>"
            loadWorkflowValue = _getKeywordValue(
                node,
                "loadWorkflowFromPostgresql",
            )

            isAllowed = (
                _isExplicitPostgresqlWorkflowLoad(loadWorkflowValue)
                or _isAllowedConsistencyLoad(
                    relativePath=self.relativePath,
                    functionName=functionName,
                    value=loadWorkflowValue,
                )
            )

            if not isAllowed:
                self.violations.append(
                    f"{self.relativePath}:{node.lineno}:{functionName}"
                )

        self.generic_visit(node)


def _findUnsafeProjectLoads(source: str, relativePath: str) -> List[str]:
    tree = ast.parse(source, filename=relativePath)
    visitor = ProjectRouteLoadingVisitor(relativePath)
    visitor.visit(tree)

    return visitor.violations


def test_ProjectRouteLoadingGuardRejectsUnsafeLegacyLoad():
    source = """
def unsafeRoute(service):
    return service.getProjectById(None, 1, {})
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="unsafe_router.py",
    ) == [
        "unsafe_router.py:3:unsafeRoute",
    ]


def test_ProjectRouteLoadingGuardAllowsExplicitPostgresqlLoads():
    source = """
def refreshWorkflow(service):
    return service.getProjectById(
        None,
        1,
        {},
        loadWorkflowFromPostgresql=True,
    )


def getProject(service, validateConsistency):
    return service.getProjectById(
        None,
        1,
        {},
        loadWorkflowFromPostgresql=not validateConsistency,
    )
"""

    assert _findUnsafeProjectLoads(
        source=source,
        relativePath="project_router.py",
    ) == []


def test_ProjectRoutersDoNotUseUnsafeLegacyProjectLoads():
    violations: List[str] = []

    for sourcePath in sorted(ROUTERS_ROOT.rglob("*.py")):
        relativePath = sourcePath.relative_to(ROUTERS_ROOT).as_posix()
        source = sourcePath.read_text(encoding="utf-8")

        violations.extend(
            _findUnsafeProjectLoads(
                source=source,
                relativePath=relativePath,
            )
        )

    assert not violations, (
        "Unsafe getProjectById() calls were found in API routers.\n"
        "Runtime routes must use loadPostgresqlRuntimeProjectForMutation(), "
        "getProjectDbRow(), or explicitly pass "
        "loadWorkflowFromPostgresql=True.\n"
        "Only the project consistency endpoint may use "
        "loadWorkflowFromPostgresql=not validateConsistency.\n"
        + "\n".join(violations)
    )