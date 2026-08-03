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


MUTATION_HANDLER_NAMES = {
    "launchProtocol",
    "saveProtocol",
    "suggestionProtocol",
    "renameProtocol",
    "duplicateProtocol",
    "deleteProtocol",
    "restartProtocolAll",
    "continueProtocolAll",
    "resetProtocolFrom",
    "stopProtocol",
}


def _getProjectRouterSyntaxTree():
    for parentPath in Path(__file__).resolve().parents:
        routerPath = parentPath / "app/backend/api/routers/project_router.py"

        if routerPath.is_file():
            return ast.parse(
                routerPath.read_text(encoding="utf-8"),
                filename=str(routerPath),
            )

    raise AssertionError("Could not locate app/backend/api/routers/project_router.py")


def _getFunctionArgumentNames(functionNode):
    arguments = functionNode.args
    argumentNodes = (
        list(arguments.posonlyargs)
        + list(arguments.args)
        + list(arguments.kwonlyargs)
    )

    argumentNames = {
        argument.arg
        for argument in argumentNodes
    }

    if arguments.vararg is not None:
        argumentNames.add(arguments.vararg.arg)

    if arguments.kwarg is not None:
        argumentNames.add(arguments.kwarg.arg)

    return argumentNames


def test_ProtocolMutationRoutesDoNotExposeLegacyRuntimeSwitch():
    syntaxTree = _getProjectRouterSyntaxTree()

    functionNodes = {
        node.name: node
        for node in syntaxTree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    missingHandlers = (
        MUTATION_HANDLER_NAMES
        - set(functionNodes)
    )

    assert not missingHandlers, (
        "Missing protocol mutation handlers: %s"
        % sorted(missingHandlers)
    )

    for handlerName in sorted(MUTATION_HANDLER_NAMES):
        argumentNames = _getFunctionArgumentNames(
            functionNodes[handlerName]
        )

        assert "usePostgresqlRuntimeProject" not in argumentNames, (
            "%s still exposes the legacy runtime switch"
            % handlerName
        )