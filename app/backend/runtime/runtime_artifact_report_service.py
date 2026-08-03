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
import glob
import os
from typing import Any, Callable, Dict, Optional


class RuntimeArtifactReportService:
    """Build diagnostic reports for PostgreSQL runtime legacy artifacts."""

    def buildPostgresqlRuntimeArtifactReport(
            self,
            mapper,
            projectId: int,
            protocolId,
            protocol=None,
            resolveScipionProtocolIdCallback: Optional[Callable] = None,
            getProtocolByRuntimeIdCallback: Optional[Callable] = None,
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Report legacy runtime artifacts still present for one PostgreSQL-runtime protocol.

        This method does not delete anything.

        It classifies:
          - run.db: Scipion runtime protocol database.
          - logs/steps.sqlite: Scipion runtime steps database.
          - output sqlite files: legacy Set mapper files already persisted to PostgreSQL.
          - unknown sqlite files: anything else under the protocol working directory.

        The goal is to understand which files are still produced and which ones may
        become cleanup candidates once PostgreSQL readers no longer depend on them.
        """
        persistedSqliteReferences = set()
        workingDir = None
        projectPath = None

        def rowToDict(row):
            if row is None:
                return {}

            try:
                return dict(row)
            except Exception:
                result = {}

                try:
                    for key in row.keys():
                        result[key] = row[key]
                except Exception:
                    pass

                return result

        def safeSize(filePath):
            try:
                if filePath and os.path.exists(str(filePath)):
                    return os.path.getsize(str(filePath))
            except Exception:
                pass

            return None

        def normalizePathKey(value):
            text = str(value or "").strip()

            if not text:
                return None

            # Some mapper paths come as "path.sqlite, "
            text = text.strip().strip(",")

            if not text:
                return None

            return text

        def buildPostgresqlViewerReadiness(storedSet):
            if not storedSet:
                return {
                    "ready": False,
                    "reason": "stored_set_not_found",
                }

            setClassName = str(storedSet.get("setClassName") or "")
            itemClassName = str(storedSet.get("itemClassName") or "")
            classText = ("%s %s" % (setClassName, itemClassName)).replace(" ", "").lower()

            itemsCount = None
            properties = storedSet.get("properties") or {}

            if isinstance(properties, dict):
                itemsCount = properties.get("itemsCount") or properties.get("_size")

            try:
                itemsCount = int(itemsCount)
            except Exception:
                itemsCount = None

            setId = storedSet.get("id")
            rootItemsCount = None
            tablesCount = None
            tableItemsCount = None

            try:
                if setId is not None:
                    row = mapper.db.fetchOne(
                        """
                        SELECT COUNT(*) AS count
                          FROM scipion_set_items
                         WHERE "setId" = %s
                        """,
                        (int(setId),),
                    )
                    rootItemsCount = int(row.get("count") or 0) if row else 0
            except Exception:
                rootItemsCount = None

            try:
                if setId is not None:
                    row = mapper.db.fetchOne(
                        """
                        SELECT COUNT(*) AS count
                          FROM scipion_set_tables
                         WHERE "setId" = %s
                        """,
                        (int(setId),),
                    )
                    tablesCount = int(row.get("count") or 0) if row else 0
            except Exception:
                tablesCount = None

            try:
                if setId is not None:
                    row = mapper.db.fetchOne(
                        """
                        SELECT COUNT(ti.id) AS count
                          FROM scipion_set_tables t
                          JOIN scipion_set_table_items ti
                            ON ti."tableId" = t.id
                         WHERE t."setId" = %s
                        """,
                        (int(setId),),
                    )
                    tableItemsCount = int(row.get("count") or 0) if row else 0
            except Exception:
                tableItemsCount = None

            supportedReader = None

            if "tiltseries" in classText and "ctftomo" not in classText:
                supportedReader = "PostgresqlTiltSeriesReader"
            elif "ctftomo" in classText:
                supportedReader = "PostgresqlCtftomoReader"
            elif "coordinates3d" in classText or "coordinate3d" in classText:
                supportedReader = "PostgresqlCoords3dReader"
            elif "tomogram" in classText or "volume" in classText:
                supportedReader = "PostgresqlIntegratedContextReader"

            hasRootItems = rootItemsCount is not None and rootItemsCount > 0
            hasLogicalTables = tablesCount is not None and tablesCount > 0
            hasTableItems = tableItemsCount is not None and tableItemsCount > 0

            ready = bool(
                supportedReader
                and (
                        hasRootItems
                        or hasTableItems
                        or itemsCount is not None
                )
            )

            reason = "postgresql_reader_available" if ready else "postgresql_reader_or_items_missing"

            return {
                "ready": ready,
                "reason": reason,
                "reader": supportedReader,
                "setClassName": setClassName,
                "itemClassName": itemClassName,
                "itemsCount": itemsCount,
                "rootItemsCount": rootItemsCount,
                "tablesCount": tablesCount,
                "tableItemsCount": tableItemsCount,
            }

        def addPersistedSqliteReference(value):
            if not value:
                return

            # _mapperPath may contain comma-separated values.
            for part in str(value).split(","):
                part = normalizePathKey(part)

                if not part:
                    continue

                persistedSqliteReferences.add(part)
                persistedSqliteReferences.add(os.path.basename(part))

                if os.path.isabs(part):
                    persistedSqliteReferences.add(os.path.abspath(part))
                    continue

                # Values like Runs/001175_ProtImportTsMovies/TiltSeriesM.sqlite
                # are project-relative, not workingDir-relative.
                try:
                    if projectPath:
                        persistedSqliteReferences.add(
                            os.path.abspath(os.path.join(str(projectPath), part))
                        )
                except Exception:
                    pass

                # Values like TiltSeriesM.sqlite are workingDir-relative.
                try:
                    if workingDir and not str(part).startswith("Runs/"):
                        persistedSqliteReferences.add(
                            os.path.abspath(os.path.join(str(workingDir), part))
                        )
                except Exception:
                    pass

        if callable(resolveScipionProtocolIdCallback):
            scipionProtocolId = resolveScipionProtocolIdCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        else:
            scipionProtocolId = protocolId

        if protocol is None and callable(getProtocolByRuntimeIdCallback):
            try:
                protocol = getProtocolByRuntimeIdCallback(scipionProtocolId)
            except Exception:
                protocol = None

        if callable(getCurrentProjectPathCallback):
            try:
                projectPath = getCurrentProjectPathCallback()
            except Exception:
                projectPath = None

        runDbPath = None

        if protocol is not None:
            try:
                workingDir = protocol.getWorkingDir()
            except Exception:
                workingDir = None

            try:
                runDbPath = protocol.getDbPath()
            except Exception:
                runDbPath = None

        if workingDir and projectPath and not os.path.isabs(str(workingDir)):
            workingDir = os.path.abspath(
                os.path.join(str(projectPath), str(workingDir))
            )

        if runDbPath:
            runDbPath = str(runDbPath)

            if not os.path.isabs(runDbPath):
                if workingDir:
                    runDbPath = os.path.abspath(
                        os.path.join(
                            str(workingDir),
                            "logs",
                            os.path.basename(runDbPath),
                        )
                    )
                elif projectPath:
                    runDbPath = os.path.abspath(
                        os.path.join(str(projectPath), runDbPath)
                    )

        if not runDbPath and workingDir:
            runDbPath = os.path.abspath(
                os.path.join(str(workingDir), "logs", "run.db")
            )

        runDbExists = bool(runDbPath and os.path.exists(str(runDbPath)))

        persistedSetRows = mapper.db.fetchAll(
            """
            SELECT
                s.id,
                s."projectId",
                s."protocolDbId",
                s."objectId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties
              FROM scipion_sets s
              JOIN protocols p
                ON p.id = s."protocolDbId"
             WHERE s."projectId" = %s
               AND p."protocolId" = %s
             ORDER BY s."outputName"
            """,
            (projectId, str(scipionProtocolId)),
        )

        persistedObjectRows = mapper.db.fetchAll(
            """
            SELECT
                o.name,
                o.path,
                o."className",
                o."scipionObjId"
              FROM scipion_objects o
              JOIN protocols p
                ON p.id = o."protocolDbId"
             WHERE o."projectId" = %s
               AND p."protocolId" = %s
               AND o."parentObjectId" IS NULL
             ORDER BY o.path, o.name
            """,
            (projectId, str(scipionProtocolId)),
        )

        persistedSets = [rowToDict(row) for row in (persistedSetRows or [])]
        persistedObjects = [rowToDict(row) for row in (persistedObjectRows or [])]

        outputsPersisted = bool(persistedSets or persistedObjects)

        for row in persistedSets:
            properties = row.get("properties") or {}

            if not isinstance(properties, dict):
                continue

            addPersistedSqliteReference(properties.get("fileName"))
            addPersistedSqliteReference(properties.get("_mapperPath"))

        sqliteFiles = []
        runtimeSqlites = []
        outputSqlites = []
        unknownSqlites = []

        if workingDir and os.path.exists(str(workingDir)):
            for filePath in glob.glob(
                    os.path.join(str(workingDir), "**", "*.sqlite"),
                    recursive=True,
            ):
                try:
                    relativePath = os.path.relpath(filePath, str(workingDir))
                except Exception:
                    relativePath = os.path.basename(filePath)

                sqliteItem = {
                    "path": filePath,
                    "relativePath": relativePath,
                    "sizeBytes": safeSize(filePath),
                }

                sqliteFiles.append(sqliteItem)

        viewerReadinessBySqliteRef = {}

        for row in persistedSets:
            properties = row.get("properties") or {}

            if not isinstance(properties, dict):
                continue

            readiness = buildPostgresqlViewerReadiness(row)

            for key in ("fileName", "_mapperPath"):
                value = properties.get(key)

                if not value:
                    continue

                for part in str(value).split(","):
                    part = normalizePathKey(part)

                    if not part:
                        continue

                    refs = {
                        part,
                        os.path.basename(part),
                    }

                    if os.path.isabs(part):
                        refs.add(os.path.abspath(part))
                    else:
                        if projectPath:
                            refs.add(os.path.abspath(os.path.join(str(projectPath), part)))

                        if workingDir and not str(part).startswith("Runs/"):
                            refs.add(os.path.abspath(os.path.join(str(workingDir), part)))

                    for ref in refs:
                        viewerReadinessBySqliteRef[ref] = readiness

        for sqliteItem in sqliteFiles:
            filePath = sqliteItem.get("path") or ""
            relativePath = sqliteItem.get("relativePath") or ""
            basename = os.path.basename(relativePath)

            normalizedFilePath = os.path.abspath(filePath) if filePath else ""
            normalizedRelativePath = normalizePathKey(relativePath)

            isStepsSqlite = normalizedRelativePath == "logs/steps.sqlite"

            isPersistedOutputSqlite = any([
                normalizedFilePath in persistedSqliteReferences,
                normalizedRelativePath in persistedSqliteReferences,
                basename in persistedSqliteReferences,
            ])

            if isStepsSqlite:
                sqliteItem["legacyRole"] = "steps"
                sqliteItem["legacyRequired"] = True
                sqliteItem["cleanupCandidate"] = False
                sqliteItem["safeToDelete"] = False
                sqliteItem["reason"] = (
                    "Scipion runtime may still use steps.sqlite for protocol "
                    "steps, restart and runtime inspection"
                )

                runtimeSqlites.append(sqliteItem)

            elif isPersistedOutputSqlite:
                viewerReadiness = (
                        viewerReadinessBySqliteRef.get(normalizedFilePath)
                        or viewerReadinessBySqliteRef.get(normalizedRelativePath)
                        or viewerReadinessBySqliteRef.get(basename)
                        or {
                            "ready": False,
                            "reason": "viewer_readiness_not_resolved",
                        }
                )

                sqliteItem["legacyRole"] = "output_set"
                sqliteItem["legacyRequired"] = True
                sqliteItem["cleanupCandidate"] = True
                sqliteItem["postgresqlViewerReady"] = bool(viewerReadiness.get("ready"))
                sqliteItem["viewerReadiness"] = viewerReadiness
                sqliteItem["safeToDeleteForViewers"] = bool(viewerReadiness.get("ready"))
                sqliteItem["safeToDeleteForRuntime"] = False
                sqliteItem["safeToDelete"] = False
                sqliteItem["reason"] = (
                    "Output is persisted in PostgreSQL and PostgreSQL viewer readers appear ready, "
                    "but runtime cleanup is still disabled"
                    if viewerReadiness.get("ready")
                    else
                    "Output is persisted in PostgreSQL, but PostgreSQL viewer readiness could not be confirmed"
                )

                outputSqlites.append(sqliteItem)

            else:
                sqliteItem["legacyRole"] = "unknown"
                sqliteItem["legacyRequired"] = True
                sqliteItem["cleanupCandidate"] = False
                sqliteItem["safeToDelete"] = False
                sqliteItem["reason"] = "Unclassified sqlite artifact"

                unknownSqlites.append(sqliteItem)

        outputSqlitesCandidateForCleanup = [
            item
            for item in outputSqlites
            if item.get("cleanupCandidate")
        ]

        return {
            "projectId": int(projectId),
            "protocolId": str(scipionProtocolId),
            "workingDir": str(workingDir) if workingDir else None,

            "runDb": {
                "path": str(runDbPath) if runDbPath else None,
                "exists": runDbExists,
                "sizeBytes": safeSize(runDbPath) if runDbExists else None,
                "legacyRequired": True,
                "cleanupCandidate": False,
                "safeToDelete": False,
                "reason": (
                    "Scipion runtime still loads protocol/status/steps from run.db"
                ),
            },

            "sqliteFiles": sqliteFiles,
            "sqliteFilesCount": len(sqliteFiles),

            "legacyArtifactsByRole": {
                "runtimeSqlites": runtimeSqlites,
                "outputSqlites": outputSqlites,
                "unknownSqlites": unknownSqlites,
            },

            "postgresqlOutputs": {
                "sets": persistedSets,
                "objects": persistedObjects,
                "outputsPersisted": outputsPersisted,
            },

            "persistedSqliteReferences": sorted(persistedSqliteReferences),

            "outputSqlitesCandidateForCleanup": outputSqlitesCandidateForCleanup,

            "safeToDeleteOutputSqlites": False,
            "safeToDeleteRunDb": False,

            "notes": [
                "Do not delete legacy artifacts yet.",
                "run.db is still required by the Scipion runtime path.",
                "steps.sqlite is still considered runtime-owned.",
                "output sqlite files are only cleanup candidates after PostgreSQL readers stop using fileName/_mapperPath.",
            ],
        }