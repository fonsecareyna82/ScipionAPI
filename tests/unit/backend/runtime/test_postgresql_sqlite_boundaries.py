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


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPOSITORY_ROOT / "app" / "backend"

SQLITE3_IMPORT_ALLOWLIST = {
    Path("app/backend/api/services/project_service.py"),
    Path("app/backend/utils/file_handlers.py"),
}

PYWORKFLOW_SQLITE_IMPORT_ALLOWLIST = {
    Path("app/backend/mapper/postgresql_runtime_mapper.py"),
}

PROJECT_DBNAME_IMPORT_ALLOWLIST = {
    Path("app/backend/runtime/project_relation_sync_service.py"),
}

LEGACY_PROJECT_MAPPER_ALLOWLIST = {
    Path("app/backend/runtime/project_relation_sync_service.py"),
}

LEGACY_PROTOCOL_DB_ACCESS_ALLOWLIST = {
    Path("app/backend/runtime/legacy_protocol_loader_service.py"),
}

PROJECT_SERVICE_DB_PATH_METHOD_ALLOWLIST = {
    "_validateImportableScipionProject",
    "_loadLegacyProjectForImport",
    "_migrateImportedProjectToPostgresql",
    "createProject",
}

PROJECT_SERVICE_SQLITE_METHOD_ALLOWLIST = {
    "_migrateImportedProjectToPostgresql",
}


def _iterBackendPythonFiles():
    return sorted(BACKEND_ROOT.rglob("*.py"))


def _relativePath(filePath):
    return filePath.relative_to(REPOSITORY_ROOT)


def _parseFile(filePath):
    return ast.parse(
        filePath.read_text(encoding="utf-8"),
        filename=str(filePath),
    )


def _collectSqliteImports():
    sqlite3Imports = set()
    pyworkflowSqliteImports = set()

    for filePath in _iterBackendPythonFiles():
        tree = _parseFile(filePath)
        relativePath = _relativePath(filePath)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "sqlite3" for alias in node.names):
                    sqlite3Imports.add(relativePath)

            elif isinstance(node, ast.ImportFrom):
                moduleName = str(node.module or "")

                if moduleName == "sqlite3":
                    sqlite3Imports.add(relativePath)

                if moduleName == "pyworkflow.mapper.sqlite" or moduleName.startswith("pyworkflow.mapper.sqlite."):
                    pyworkflowSqliteImports.add(relativePath)

    return sqlite3Imports, pyworkflowSqliteImports


def _collectProjectServiceSqliteMethods():
    filePath = BACKEND_ROOT / "api" / "services" / "project_service.py"
    tree = _parseFile(filePath)
    methods = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        usesSqlite3 = any(
            isinstance(child, ast.Name)
            and child.id == "sqlite3"
            for child in ast.walk(node)
        )

        if usesSqlite3:
            methods.add(node.name)

    return methods


def _collectLegacyProjectMapperAccess():
    projectDbNameImports = set()
    projectMapperCalls = set()

    for filePath in _iterBackendPythonFiles():
        tree = _parseFile(filePath)
        relativePath = _relativePath(filePath)
        projectAliases = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue

            moduleName = str(node.module or "")

            if moduleName == "pyworkflow":
                if any(alias.name == "PROJECT_DBNAME" for alias in node.names):
                    projectDbNameImports.add(relativePath)

            if moduleName in {
                "pyworkflow.project",
                "pyworkflow.project.project",
            }:
                for alias in node.names:
                    if alias.name == "Project":
                        projectAliases.add(alias.asname or alias.name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            function = node.func

            if not isinstance(function, ast.Attribute):
                continue

            if function.attr != "createMapper":
                continue

            owner = function.value

            if isinstance(owner, ast.Name) and owner.id in projectAliases:
                projectMapperCalls.add(relativePath)

    return projectDbNameImports, projectMapperCalls


def _collectLegacyProtocolDbAccess():
    protocolDbLoaderImports = set()
    protocolDbPathCalls = set()
    projectServiceDbPathMethods = set()
    projectServicePath = Path("app/backend/api/services/project_service.py")

    for filePath in _iterBackendPythonFiles():
        tree = _parseFile(filePath)
        relativePath = _relativePath(filePath)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                moduleName = str(node.module or "")

                if moduleName == "pyworkflow.protocol.protocol":
                    if any(alias.name == "getProtocolFromDb" for alias in node.names):
                        protocolDbLoaderImports.add(relativePath)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            usesGetDbPath = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "getDbPath"
                for child in ast.walk(node)
            )

            if not usesGetDbPath:
                continue

            if relativePath == projectServicePath:
                projectServiceDbPathMethods.add(node.name)
            else:
                protocolDbPathCalls.add(relativePath)

    return {
        "loaderImports": protocolDbLoaderImports,
        "dbPathFiles": protocolDbPathCalls,
        "projectServiceDbPathMethods": projectServiceDbPathMethods,
    }


def test_SqliteDirectImportsStayInsideApprovedCompatibilityBoundaries():
    sqlite3Imports, pyworkflowSqliteImports = _collectSqliteImports()

    unexpectedSqlite3Imports = sqlite3Imports - SQLITE3_IMPORT_ALLOWLIST
    unexpectedPyworkflowSqliteImports = pyworkflowSqliteImports - PYWORKFLOW_SQLITE_IMPORT_ALLOWLIST

    assert not unexpectedSqlite3Imports, (
        "Unexpected sqlite3 imports outside compatibility boundaries: %s"
        % sorted(str(path) for path in unexpectedSqlite3Imports)
    )

    assert not unexpectedPyworkflowSqliteImports, (
        "Unexpected pyworkflow.mapper.sqlite imports outside compatibility boundaries: %s"
        % sorted(str(path) for path in unexpectedPyworkflowSqliteImports)
    )


def test_LegacyProjectMapperAccessStaysInsideMigrationBoundary():
    projectDbNameImports, projectMapperCalls = _collectLegacyProjectMapperAccess()

    unexpectedProjectDbNameImports = projectDbNameImports - PROJECT_DBNAME_IMPORT_ALLOWLIST
    unexpectedProjectMapperCalls = projectMapperCalls - LEGACY_PROJECT_MAPPER_ALLOWLIST

    assert not unexpectedProjectDbNameImports, (
        "Unexpected PROJECT_DBNAME imports outside legacy migration boundary: %s"
        % sorted(str(path) for path in unexpectedProjectDbNameImports)
    )

    assert not unexpectedProjectMapperCalls, (
        "Unexpected Project.createMapper calls outside legacy migration boundary: %s"
        % sorted(str(path) for path in unexpectedProjectMapperCalls)
    )


def test_ProjectServiceUsesSqliteOnlyForLegacyProjectMigration():
    sqliteMethods = _collectProjectServiceSqliteMethods()
    unexpectedMethods = sqliteMethods - PROJECT_SERVICE_SQLITE_METHOD_ALLOWLIST

    assert not unexpectedMethods, (
        "Unexpected sqlite3 usage in ProjectService outside legacy project migration: %s"
        % sorted(unexpectedMethods)
    )

    assert "_migrateImportedProjectToPostgresql" in sqliteMethods


def test_LegacyProtocolDatabaseAccessStaysInsideApprovedBoundaries():
    access = _collectLegacyProtocolDbAccess()

    unexpectedLoaderImports = access["loaderImports"] - LEGACY_PROTOCOL_DB_ACCESS_ALLOWLIST
    unexpectedDbPathFiles = access["dbPathFiles"] - LEGACY_PROTOCOL_DB_ACCESS_ALLOWLIST
    unexpectedProjectServiceMethods = (
            access["projectServiceDbPathMethods"]
            - PROJECT_SERVICE_DB_PATH_METHOD_ALLOWLIST
    )

    assert not unexpectedLoaderImports, (
        "Unexpected getProtocolFromDb imports outside legacy project import: %s"
        % sorted(str(path) for path in unexpectedLoaderImports)
    )

    assert not unexpectedDbPathFiles, (
        "Unexpected protocol.getDbPath calls outside legacy project import: %s"
        % sorted(str(path) for path in unexpectedDbPathFiles)
    )

    assert not unexpectedProjectServiceMethods, (
        "Unexpected protocol.getDbPath usage in ProjectService outside approved SQLite boundaries: %s"
        % sorted(unexpectedProjectServiceMethods)
    )