# postgresql.py

import json
import threading
from datetime import datetime

import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Iterator, Tuple
from pyworkflow.mapper.mapper import Mapper  # Base class from Scipion

POSTGRESQL_PROTOCOL_ID_START = 2
POSTGRESQL_RUNTIME_OBJECT_ID_START = 1_000_000

PROTOCOL_STEP_EFFECTIVE_ELAPSED_SQL = """
    CASE
        WHEN LOWER(COALESCE(status, '')) = 'running' AND "initTime" IS NOT NULL
        THEN GREATEST(
            COALESCE("elapsedSeconds", 0.0),
            GREATEST(0.0, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - "initTime"))::double precision)
        )

        WHEN LOWER(COALESCE(status, '')) IN ('finished', 'failed', 'aborted', 'interactive', 'done') AND "initTime" IS NOT NULL
        THEN GREATEST(
            COALESCE("elapsedSeconds", 0.0),
            GREATEST(0.0, EXTRACT(EPOCH FROM (COALESCE("endTime", "updatedAt") - "initTime"))::double precision)
        )

        ELSE COALESCE("elapsedSeconds", 0.0)
    END
"""


def _toJsonParam(value: Any) -> Any:
    # toJsonParam
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value, dumps=json.dumps)
    return value


class PostgresqlDb:
    """Handle PostgreSQL connections and basic operations."""

    def __init__(
            self,
            dbName: str,
            user: str,
            password: str,
            host: str = "localhost",
            port: int = 5432,
    ):
        self._connectionParams = {
            "dbname": dbName,
            "user": user,
            "password": password,
            "host": host,
            "port": port,
        }

        self._threadLocal = threading.local()
        self._resourcesLock = threading.RLock()
        self._connections = []
        self._cursors = []
        self._closed = False

        # Preserve the previous fail-fast behavior: creating the
        # mapper validates the main-thread connection immediately.
        _ = self.cursor

    @property
    def conn(self):
        return self._getThreadConnection()

    @property
    def isClosed(self) -> bool:
        with self._resourcesLock:
            return bool(self._closed)

    @property
    def cursor(self):
        with self._resourcesLock:
            if self._closed:
                raise psycopg2.InterfaceError(
                    "PostgreSQL database is closed."
                )

            connection = self._getThreadConnection()
            cursor = getattr(self._threadLocal, "cursor", None)

            if cursor is None or bool(getattr(cursor, "closed", False)):
                cursor = connection.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                )

                self._threadLocal.cursor = cursor
                self._cursors.append(cursor)

            return cursor

    def _getThreadConnection(self):
        with self._resourcesLock:
            if self._closed:
                raise psycopg2.InterfaceError(
                    "PostgreSQL database is closed."
                )

            connection = getattr(
                self._threadLocal,
                "connection",
                None,
            )

            if connection is not None and not bool(
                    getattr(connection, "closed", False)
            ):
                return connection

            connection = psycopg2.connect(
                **self._connectionParams
            )

            self._threadLocal.connection = connection
            self._threadLocal.cursor = None
            self._connections.append(connection)

            return connection

    def execute(
            self,
            query: str,
            params: Optional[tuple] = None,
            commit: bool = True,
    ) -> Any:
        """Execute a SQL command."""
        cursor = self.cursor
        connection = self.conn

        cursor.execute(query, params)

        if commit:
            connection.commit()

        return cursor

    def executeReturningOne(
            self,
            query: str,
            params: Optional[tuple] = None,
    ) -> Optional[Dict]:
        """
        Execute a write statement with RETURNING and commit it.

        The returned row is fetched before committing.
        """
        cursor = self.cursor
        connection = self.conn

        try:
            cursor.execute(query, params)
            row = cursor.fetchone()
            connection.commit()

            return row

        except Exception:
            connection.rollback()
            raise

    @contextmanager
    def transaction(self) -> Iterator["PostgresqlDb"]:
        connection = self.conn

        try:
            yield self
            connection.commit()

        except Exception:
            connection.rollback()
            raise

    def rollback(self) -> None:
        """
        Roll back the active transaction owned by the current thread.
        """
        self.conn.rollback()

    def fetchOne(
            self,
            query: str,
            params: Optional[tuple] = None,
    ) -> Optional[Dict]:
        """Fetch a single row."""
        cursor = self.cursor
        cursor.execute(query, params)

        return cursor.fetchone()

    def fetchAll(
            self,
            query: str,
            params: Optional[tuple] = None,
    ) -> List[Dict]:
        """Fetch all rows."""
        cursor = self.cursor
        cursor.execute(query, params)

        return cursor.fetchall()

    def close(self):
        with self._resourcesLock:
            if self._closed:
                return

            self._closed = True

            cursors = list(self._cursors)
            connections = list(self._connections)

            self._cursors.clear()
            self._connections.clear()
            self._threadLocal = threading.local()

        firstError = None

        for cursor in cursors:
            try:
                if not bool(getattr(cursor, "closed", False)):
                    cursor.close()

            except Exception as error:
                if firstError is None:
                    firstError = error

        for connection in connections:
            try:
                if not bool(getattr(connection, "closed", False)):
                    connection.close()

            except Exception as error:
                if firstError is None:
                    firstError = error

        if firstError is not None:
            raise firstError


class PostgresqlFlatMapper(Mapper):
    """Flat mapper to handle Users, Projects and Protocols in PostgreSQL."""

    def __init__(self, db: PostgresqlDb):
        super().__init__()
        self.db = db
        # self.initTables()

    def initTables(self):
        """Create tables if they do not exist (protocols kept as legacy schema)."""

        # CreateUsersTableFirst because projects and project_shares reference users(id)
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                "hashedPassword" TEXT NOT NULL,
                "isActive" BOOLEAN NOT NULL DEFAULT TRUE,
                role TEXT NOT NULL DEFAULT 'user',

                "firstName" TEXT,
                "lastName" TEXT,
                institution TEXT,
                phone TEXT,
                position TEXT,
                country TEXT,
                city TEXT,
                "postalCode" TEXT,

                "isVerified" BOOLEAN NOT NULL DEFAULT FALSE,
                "verificationCode" TEXT,

                "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ
            );
            """
        )

        # CreateProjectsTable with mandatory ownerId
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                "ownerId" INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                createdAt TIMESTAMP DEFAULT NOW(),
                updatedAt TIMESTAMP
            );
            """
        )

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS project_object_id_counters (
                "projectId" INTEGER PRIMARY KEY
                    REFERENCES projects(id)
                    ON DELETE CASCADE,

                "nextObjectId" INTEGER NOT NULL
                    DEFAULT 1000000,

                "nextProtocolId" INTEGER NOT NULL
                    DEFAULT 2,

                "createdAt" TIMESTAMPTZ NOT NULL
                    DEFAULT NOW(),

                "updatedAt" TIMESTAMPTZ NOT NULL
                    DEFAULT NOW()
            );

            ALTER TABLE project_object_id_counters
                ADD COLUMN IF NOT EXISTS "nextProtocolId"
                INTEGER NOT NULL DEFAULT 2;

            ALTER TABLE project_object_id_counters
                ALTER COLUMN "nextObjectId"
                SET DEFAULT 1000000;
            """
        )

        # CreateProtocolsTableLegacy
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS protocols (
                id SERIAL PRIMARY KEY,
                "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                "protocolId" TEXT NOT NULL,
                "protocolClassName" TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                params JSONB,
                "parentIds" INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
                "childIds" INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
                "relationsSynchronized" BOOLEAN NOT NULL DEFAULT FALSE,
                "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ
            );

            CREATE UNIQUE INDEX IF NOT EXISTS protocols_project_protocol_ux
              ON protocols("projectId", "protocolId");

            CREATE UNIQUE INDEX IF NOT EXISTS protocols_project_dbid_ux
              ON protocols("projectId", id);
              
            ALTER TABLE protocols
                ADD COLUMN IF NOT EXISTS "relationsSynchronized"
                BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )

        # CreateProtocolDependenciesTable
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_dependencies (
                "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                "parentProtocolDbId" INTEGER NOT NULL,
                "childProtocolDbId" INTEGER NOT NULL,
                "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                PRIMARY KEY ("projectId", "parentProtocolDbId", "childProtocolDbId"),

                FOREIGN KEY ("projectId", "parentProtocolDbId")
                  REFERENCES protocols("projectId", id)
                  ON DELETE CASCADE,

                FOREIGN KEY ("projectId", "childProtocolDbId")
                  REFERENCES protocols("projectId", id)
                  ON DELETE CASCADE,

                CHECK ("parentProtocolDbId" <> "childProtocolDbId")
            );

            CREATE INDEX IF NOT EXISTS protocol_dependencies_by_parent
              ON protocol_dependencies("projectId", "parentProtocolDbId");

            CREATE INDEX IF NOT EXISTS protocol_dependencies_by_child
              ON protocol_dependencies("projectId", "childProtocolDbId");
            """
        )

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_input_refs (
                "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                "protocolDbId" INTEGER NOT NULL,
                "protocolId" TEXT NOT NULL,
                "inputName" TEXT NOT NULL,
                "itemIndex" INTEGER NOT NULL DEFAULT 0,
                "parentProtocolDbId" INTEGER,
                "parentProtocolId" TEXT,
                "parentOutputName" TEXT,
                "objectClassName" TEXT,
                "objectId" TEXT,
                "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                PRIMARY KEY ("projectId", "protocolDbId", "inputName", "itemIndex"),

                FOREIGN KEY ("projectId", "protocolDbId")
                  REFERENCES protocols("projectId", id)
                  ON DELETE CASCADE,

                FOREIGN KEY ("projectId", "parentProtocolDbId")
                  REFERENCES protocols("projectId", id)
                  ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_protocol_input_refs_protocol
              ON protocol_input_refs("projectId", "protocolDbId");

            CREATE INDEX IF NOT EXISTS idx_protocol_input_refs_parent
              ON protocol_input_refs("projectId", "parentProtocolDbId", "parentOutputName");

            CREATE INDEX IF NOT EXISTS idx_protocol_input_refs_parent_protocol_id
              ON protocol_input_refs("projectId", "parentProtocolId", "parentOutputName");
            """
        )

        self.db.execute("""
            CREATE TABLE IF NOT EXISTS protocol_steps (
                id SERIAL PRIMARY KEY,
                "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                "protocolDbId" INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
                "protocolId" TEXT NOT NULL,
                "stepIndex" INTEGER NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                prerequisites JSONB NOT NULL DEFAULT '[]'::jsonb,
                args JSONB,
                "initTime" TIMESTAMPTZ,
                "endTime" TIMESTAMPTZ,
                "elapsedSeconds" DOUBLE PRECISION,
                error TEXT,
                interactive BOOLEAN NOT NULL DEFAULT FALSE,
                "needsGpu" BOOLEAN NOT NULL DEFAULT TRUE,
                event TEXT,
                "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE ("projectId", "protocolDbId", "stepIndex")
            );

            CREATE INDEX IF NOT EXISTS protocol_steps_by_protocol
              ON protocol_steps("projectId", "protocolDbId", "stepIndex");
        """)

        # CreateProjectSharesTable (requires users and projects)
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS project_shares (
                id SERIAL PRIMARY KEY,
                "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                "permission" TEXT NOT NULL DEFAULT 'full',
                "createdAt" TIMESTAMP DEFAULT NOW(),
                "updatedAt" TIMESTAMP,
                UNIQUE ("projectId", "userId")
            );
            """
        )

        # Create ProjectTags
        self.db.execute("""
                          CREATE TABLE IF NOT EXISTS protocol_tags (
                          id TEXT PRIMARY KEY,
                          "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                          title TEXT NOT NULL,
                          description TEXT,
                          color TEXT,
                          "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                          "updatedAt" TIMESTAMPTZ
                        );
                        
                        CREATE UNIQUE INDEX IF NOT EXISTS protocol_tags_project_title_ux
                          ON protocol_tags("projectId", lower(title));
                        """)

        self.db.execute("""
                          CREATE TABLE IF NOT EXISTS protocol_tag_assignments (
                              "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                              "protocolDbId" INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
                              "tagId" TEXT NOT NULL REFERENCES protocol_tags(id) ON DELETE CASCADE,
                              "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                              PRIMARY KEY ("projectId", "protocolDbId", "tagId")
                            );
                        
                        CREATE INDEX IF NOT EXISTS protocol_tag_assignments_by_tag
                          ON protocol_tag_assignments("projectId", "tagId");
                        
                        CREATE INDEX IF NOT EXISTS protocol_tag_assignments_by_protocol
                          ON protocol_tag_assignments("projectId", "protocolDbId");

                               """)
        # CreateUserSettingsTable
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                "userId" INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )

        # CreateInstanceSettingsTable (singleton row id=1)
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS instance_settings (
                id SMALLINT PRIMARY KEY,
                settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT instance_settings_singleton CHECK (id = 1)
            );
            """
        )

        # EnsureSingletonRow
        self.db.execute(
            """
            INSERT INTO instance_settings (id, settings)
            VALUES (1, '{}'::jsonb)
            ON CONFLICT (id) DO NOTHING;
            """
        )

        # JsonbIndexes (optional but recommended)
        self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_settings_settings_gin
              ON user_settings USING GIN (settings);
            """
        )
        self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_instance_settings_settings_gin
              ON instance_settings USING GIN (settings);
            """
        )

    # -----------------------------
    # Tags Methods
    # -----------------------------

    def listProtocolTags(self, projectId: int) -> List[Dict[str, Any]]:
        # listProtocolTags
        return self.db.fetchAll(
            """
            SELECT id, "projectId", title, description, color, "createdAt", "updatedAt"
              FROM protocol_tags
             WHERE "projectId" = %s
             ORDER BY lower(title) ASC
            """,
            (projectId,),
        )

    def upsertProtocolTag(self, projectId: int, tag: Dict[str, Any]) -> Dict[str, Any]:
        # upsertProtocolTag
        tagId = (tag or {}).get("id")
        title = (tag or {}).get("title")

        if not tagId:
            raise ValueError("Missing required field: tag.id")
        if not title:
            raise ValueError("Missing required field: tag.title")

        description = (tag or {}).get("description")
        color = (tag or {}).get("color")

        cur = self.db.execute(
            """
            INSERT INTO protocol_tags (id, "projectId", title, description, color)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id)
            DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                color = EXCLUDED.color,
                "updatedAt" = NOW()
            RETURNING id, "projectId", title, description, color, "createdAt", "updatedAt"
            """,
            (str(tagId), projectId, title, description, color),
        )
        return cur.fetchone()

    def deleteProtocolTag(self, projectId: int, tagId: str) -> bool:
        # deleteProtocolTag
        cur = self.db.execute(
            """
            DELETE FROM protocol_tags
             WHERE id = %s
               AND "projectId" = %s
            """,
            (str(tagId), projectId),
        )
        return cur.rowcount > 0

    def getProtocolTagIds(self, projectId: int, protocolDbId: int) -> List[str]:
        # getProtocolTagIds
        rows = self.db.fetchAll(
            """
            SELECT pta."tagId"
              FROM protocol_tag_assignments pta
              JOIN protocols p ON p.id = pta."protocolDbId"
             WHERE p."projectId" = %s
               AND pta."protocolDbId" = %s
             ORDER BY pta."tagId" ASC
            """,
            (projectId, protocolDbId),
        )
        return [r["tagId"] for r in rows if r.get("tagId")]

    def setProtocolTagIdsByProtocolDbId(self, projectId: int, protocolDbId: int, tagIds: List[str]) -> dict:
        # setProtocolTagIdsByProtocolDbId
        clean = sorted({str(t).strip() for t in (tagIds or []) if str(t).strip()})

        row = self.db.fetchOne(
            """
            SELECT id, "protocolId"
              FROM protocols
             WHERE id = %s
               AND "projectId" = %s
            """,
            (int(protocolDbId), projectId),
        )
        if not row:
            raise Exception("Protocol not found in project")

        self.db.execute(
            """
            DELETE FROM protocol_tag_assignments
             WHERE "protocolDbId" = %s
            """,
            (int(protocolDbId),),
        )

        if clean:
            self.db.execute(
                """
                INSERT INTO protocol_tag_assignments ("protocolDbId", "tagId")
                SELECT %s, x
                  FROM unnest(%s::text[]) AS x
                ON CONFLICT ("protocolDbId", "tagId") DO NOTHING
                """,
                (int(protocolDbId), clean),
            )

        return {
            "protocolId": str(row["protocolId"]),
            "protocolDbId": int(protocolDbId),
            "tagIds": clean,
        }

    def setProtocolTagIds(self, projectId: int, protocolId: int, tagIds: List[str]) -> dict:
        # setProtocolTagIds
        row = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "protocolId" = %s
               AND "projectId" = %s
            """,
            (str(protocolId), projectId),
        )
        if not row:
            raise Exception("Protocol not found in project")

        return self.setProtocolTagIdsByProtocolDbId(
            projectId=projectId,
            protocolDbId=int(row["id"]),
            tagIds=tagIds,
        )

    def getProjectProtocolTagIdsByProtocolId(self, projectId: int, includeEmpty: bool = False) -> Dict[str, List[str]]:
        # getProjectProtocolTagIdsByProtocolId
        rows = self.db.fetchAll(
            """
            SELECT
                p."protocolId" AS "protocolId",
                COALESCE(
                    array_agg(DISTINCT pta."tagId" ORDER BY pta."tagId")
                    FILTER (WHERE pta."tagId" IS NOT NULL),
                    ARRAY[]::text[]
                ) AS "tagIds"
            FROM protocols p
            LEFT JOIN protocol_tag_assignments pta
              ON pta."protocolDbId" = p.id
            LEFT JOIN protocol_tags pt
              ON pt.id = pta."tagId"
             AND pt."projectId" = p."projectId"
            WHERE p."projectId" = %s
            GROUP BY p."protocolId"
            ORDER BY MIN(p.id)
            """,
            (projectId,),
        )

        result: Dict[str, List[str]] = {}
        for r in rows:
            # buildResultMap
            protocolId = str(r["protocolId"])
            tagIds = list(r.get("tagIds") or [])
            if (not includeEmpty) and (not tagIds):
                continue
            result[protocolId] = tagIds

        return result

    # -----------------------------
    # Auth Methods
    # -----------------------------
    def getUserByEmail(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Returns a dict with the user's columns or None if it does not exist.
          - email
          - hashedPassword
          - isVerified
        """
        return self.db.fetchOne(
            """
            SELECT *
              FROM users
             WHERE email = %s
            """,
            (email,),
        )

    def insertUser(
        self,
        email: str,
        hashedPassword: str,
        firstName: str,
        lastName: str,
        institution: Optional[str],
        role: str,
        isActive: bool,
        isVerified: bool,
        verificationCode: str,
    ) -> int:
        """
        Insert a new user and return its id.
        """
        cur = self.db.execute(
            """
            INSERT INTO users (
              email,
              "hashedPassword",
              "firstName",
              "lastName",
              institution,
              role,
              "isActive",
              "isVerified",
              "verificationCode"
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                email,
                hashedPassword,
                firstName,
                lastName,
                institution,
                role,
                isActive,
                isVerified,
                verificationCode,
            ),
        )
        return cur.fetchone()["id"]

    def getUserByVerificationCode(self, verificationCode: str) -> Optional[Dict[str, Any]]:
        """
        Return a user row matching the given verification code,
        or None if no such user exists.
        Expects columns: id, email, hashedPassword, isVerified, verificationCode.
        """
        return self.db.fetchOne(
            """
            SELECT
              id,
              email,
              "hashedPassword"   AS hashedPassword,
              "isVerified"      AS isVerified,
              "verificationCode" AS verificationCode
            FROM users
            WHERE "verificationCode" = %s
            """,
            (verificationCode,),
        )

    def verifyUser(self, userId: int) -> None:
        """
        Mark the user as verified and clear their verification code.
        """
        self.db.execute(
            """
            UPDATE users
               SET "isVerified" = TRUE,
                   "verificationCode" = NULL
             WHERE id = %s
            """,
            (userId,),
        )

    def updateUserVerificationCode(self, userId: int, verificationCode: str) -> None:
        """
        Update the verificationCode column for the given user ID.
        """
        self.db.execute(
            """
            UPDATE users
               SET "verificationCode" = %s
             WHERE id = %s
            """,
            (verificationCode, userId),
        )

    def getUserById(self, userId: int) -> Optional[Dict[str, Any]]:
        """
        Fetch a user profile by its ID.
        Returns a dict containing only public fields, or None if not found.
        """
        return self.db.fetchOne(
            """
            SELECT  *
            FROM users
            WHERE id = %s
            """,
            (userId,),
        )

    def updateUserFields(self, userId: int, fields: dict) -> None:
        """
        Update the given fields on the users table for the specified userId.
        `fields` is a dict mapping column names (camelCase) to new values.
        """
        if not fields:
            return

        setClauses = []
        params = []
        for col, val in fields.items():
            setClauses.append(f'"{col}" = %s')
            params.append(val)

        sql = f"""
            UPDATE users
               SET {", ".join(setClauses)}
             WHERE id = %s
        """
        params.append(userId)
        self.db.execute(sql, tuple(params))

    def listUsers(self, excludeUserId: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return a list of users for selection in the UI.
        If excludeUserId is provided, that user will be filtered out.
        """
        if excludeUserId is None:
            return self.db.fetchAll(
                """
                SELECT
                  id,
                  email,
                  "firstName",
                  "lastName",
                  institution,
                  role
                FROM users
                ORDER BY "firstName", "lastName", email
                """
            )

        return self.db.fetchAll(
            """
            SELECT
              id,
              email,
              "firstName",
              "lastName",
              institution,
              role
            FROM users
            WHERE id <> %s
            ORDER BY "firstName", "lastName", email
            """,
            (excludeUserId,),
        )

    # -----------------------------
    # Project Methods
    # -----------------------------
    def insertProject(self, ownerId: int, name: str, description: Optional[str] = None, status: str = "active") -> int:
        """Insert a new project and return its id."""
        cur = self.db.execute(
            'INSERT INTO projects ("ownerId", name, description, status) VALUES (%s, %s, %s, %s) RETURNING id',
            (ownerId, name, description, status),
        )
        return cur.fetchone()["id"]

    def getProject(self, projectId: int, userId: int) -> Optional[Dict]:
        """
        Retrieve a project by id that is accessible to the given user.
        A project is accessible if:
          - The user is the owner, or
          - There is an entry in project_shares for (projectId, userId).

        It also annotates the row with:
          - isOwner: bool
          - isShared: bool
          - permission: text
        """
        query = """
            SELECT
                p.*,
                (p."ownerId" = %s) AS "isOwner",
                EXISTS (
                    SELECT 1
                    FROM project_shares s
                    WHERE s."projectId" = p.id
                      AND s."userId" = %s
                ) AS "isShared",
                COALESCE(
                    (
                        SELECT s."permission"
                        FROM project_shares s
                        WHERE s."projectId" = p.id
                          AND s."userId" = %s
                        LIMIT 1
                    ),
                    'full'
                ) AS "permission"
            FROM projects p
            WHERE p.id = %s
              AND (
                  p."ownerId" = %s
                  OR EXISTS (
                      SELECT 1
                      FROM project_shares s
                      WHERE s."projectId" = p.id
                        AND s."userId" = %s
                  )
              )
        """
        params = (
            userId,
            userId,
            userId,
            projectId,
            userId,
            userId,
        )
        return self.db.fetchOne(query, params)

    def getProjectRuntimeMetadata(
            self,
            projectId: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Return project metadata required by the Scipion runtime mapper.

        Older databases may expose unquoted PostgreSQL columns as
        createdat/updatedat, while migrated schemas may preserve camelCase.
        Normalize both representations here.
        """
        row = self.db.fetchOne(
            """
            SELECT *
              FROM projects
             WHERE id = %s
            """,
            (int(projectId),),
        )

        if row is None:
            return None

        result = dict(row)

        if result.get("createdAt") is None:
            result["createdAt"] = result.get("createdat")

        if result.get("updatedAt") is None:
            result["updatedAt"] = result.get("updatedat")

        return result

    def updateProjectProtocolStatus(
            self,
            projectId: int,
            protocolId: int,
            statusValue,
    ) -> bool:
        cur = self.db.execute(
            """
            UPDATE protocols
               SET status = %s,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                str(statusValue),
                int(projectId),
                str(protocolId),
            ),
        )
        return cur.rowcount > 0

    def upsertProjectProtocolStatus(
            self,
            projectId: int,
            protocolId: int,
            protocolClassName: str,
            statusValue,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO protocols (
                "projectId",
                "protocolId",
                "protocolClassName",
                status,
                params,
                "parentIds",
                "childIds",
                "updatedAt"
            )
            VALUES (%s, %s, %s, %s, '{}'::jsonb, %s, %s, NOW())
            ON CONFLICT ("projectId", "protocolId")
            DO UPDATE SET
                status = EXCLUDED.status,
                "updatedAt" = NOW()
            RETURNING id
            """,
            (
                int(projectId),
                str(protocolId),
                str(protocolClassName),
                str(statusValue),
                [],
                [],
            ),
        )
        return int(cur.fetchone()["id"])

    # -----------------------------
    # Project share methods
    # -----------------------------
    def shareProjectWithUser(self, projectId: int, targetUserId: int, permission: str = "full") -> Dict[str, Any]:
        """
        Create or update a project share entry between projectId and targetUserId.
        """
        cur = self.db.execute(
            """
            INSERT INTO project_shares ("projectId", "userId", "permission")
            VALUES (%s, %s, %s)
            ON CONFLICT ("projectId", "userId")
            DO UPDATE SET
                "permission" = EXCLUDED."permission",
                "updatedAt" = NOW()
            RETURNING id,
                      "projectId",
                      "userId",
                      "permission",
                      "createdAt",
                      "updatedAt"
            """,
            (projectId, targetUserId, permission),
        )
        return cur.fetchone()

    def revokeProjectShare(self, projectId: int, userId: int) -> bool:
        """Remove a share from project_shares."""
        cursor = self.db.execute(
            """
            DELETE FROM project_shares
             WHERE "projectId" = %s
               AND "userId" = %s
            """,
            (projectId, userId),
        )
        return cursor.rowcount > 0

    def listProjectShares(self, projectId: int) -> List[Dict[str, Any]]:
        """List all shares for a given project."""
        return self.db.fetchAll(
            """
            SELECT id,
                   "projectId",
                   "userId",
                   "permission",
                   "createdAt",
                   "updatedAt"
              FROM project_shares
             WHERE "projectId" = %s
             ORDER BY "createdAt" ASC
            """,
            (projectId,),
        )

    def listProjects(self, ownerId: int) -> List[Dict]:
        """
        List all projects the user can see (owned + shared).
        """
        return self.db.fetchAll(
            """
            SELECT *
            FROM (
                SELECT
                    p.*,
                    TRUE  AS "isOwner",
                    FALSE AS "isShared",
                    'owner'::text AS "permission"
                FROM projects p
                WHERE p."ownerId" = %s

                UNION ALL

                SELECT
                    p.*,
                    FALSE AS "isOwner",
                    TRUE  AS "isShared",
                    COALESCE(ps."permission", 'full') AS "permission"
                FROM projects p
                JOIN project_shares ps
                  ON ps."projectId" = p.id
                WHERE ps."userId" = %s
                  AND p."ownerId" <> %s
            ) AS sub
            ORDER BY "updatedAt" DESC
            """,
            (ownerId, ownerId, ownerId),
        )

    def updateProject(
        self,
        projectId: int,
        ownerId: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update the given fields on a project owned by ownerId."""
        setClauses = []
        params: list[Any] = []

        if name is not None:
            setClauses.append('"name" = %s')
            params.append(name)

        if description is not None:
            setClauses.append('"description" = %s')
            params.append(description)

        if status is not None:
            setClauses.append('"status" = %s')
            params.append(status)

        if not setClauses:
            return self.getProject(projectId, ownerId)

        setClauses.append('"updatedAt" = NOW()')

        sql = f"""
            UPDATE "projects"
               SET {", ".join(setClauses)}
             WHERE "id" = %s
               AND "ownerId" = %s
        """
        params.extend([projectId, ownerId])
        self.db.execute(sql, tuple(params))
        return self.getProject(projectId, ownerId)

    def updateProjectModificationTime(
        self,
        projectId: int,
        ownerId: int,
        updateAt: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Update the given fields on a project owned by ownerId."""
        setClauses = []
        params = []

        setClauses.append('"updatedAt" = %s')
        params.append(updateAt)

        sql = f"""
            UPDATE "projects"
               SET {", ".join(setClauses)}
             WHERE "id" = %s
               AND "ownerId" = %s
        """
        params.extend([projectId, ownerId])
        self.db.execute(sql, tuple(params))
        return self.getProject(projectId, ownerId)

    def deleteProject(self, projectId: int, ownerId: int) -> bool:
        """Delete the project for a given owner."""
        cursor = self.db.execute(
            'DELETE FROM "projects" WHERE "id" = %s AND "ownerId" = %s',
            (projectId, ownerId),
        )
        return cursor.rowcount > 0

    def deleteProjectRuntimeData(
            self,
            projectId: int,
    ) -> Dict[str, int]:
        """
        Delete every runtime Mapper object owned by one project.

        The project row, shares, protocol tag definitions and global object
        type schemas are deliberately preserved.
        """
        projectId = int(projectId)

        with self.db.transaction():
            projectRow = self.db.fetchOne(
                """
                SELECT id
                  FROM projects
                 WHERE id = %s
                 FOR UPDATE
                """,
                (
                    projectId,
                ),
            )

            if projectRow is None:
                raise RuntimeError(
                    "Cannot delete runtime data because "
                    "PostgreSQL project %s does not exist."
                    % projectId
                )

            relationsCursor = self.db.execute(
                """
                DELETE FROM scipion_relations
                 WHERE "projectId" = %s
                """,
                (
                    projectId,
                ),
                commit=False,
            )

            deletedRelationsCount = int(
                getattr(
                    relationsCursor,
                    "rowcount",
                    0,
                )
                or 0
            )

            setsCursor = self.db.execute(
                """
                DELETE FROM scipion_sets
                 WHERE "projectId" = %s
                """,
                (
                    projectId,
                ),
                commit=False,
            )

            deletedSetsCount = int(
                getattr(
                    setsCursor,
                    "rowcount",
                    0,
                )
                or 0
            )

            objectsCursor = self.db.execute(
                """
                DELETE FROM scipion_objects
                 WHERE "projectId" = %s
                """,
                (
                    projectId,
                ),
                commit=False,
            )

            deletedObjectsCount = int(
                getattr(
                    objectsCursor,
                    "rowcount",
                    0,
                )
                or 0
            )

            protocolsCursor = self.db.execute(
                """
                DELETE FROM protocols
                 WHERE "projectId" = %s
                """,
                (
                    projectId,
                ),
                commit=False,
            )

            deletedProtocolsCount = int(
                getattr(
                    protocolsCursor,
                    "rowcount",
                    0,
                )
                or 0
            )

            self.db.execute(
                """
                INSERT INTO project_object_id_counters (
                    "projectId",
                    "nextObjectId",
                    "nextProtocolId"
                )
                VALUES (%s, %s, %s)
                ON CONFLICT ("projectId")
                DO UPDATE SET
                    "nextObjectId" = EXCLUDED."nextObjectId",
                    "nextProtocolId" = EXCLUDED."nextProtocolId",
                    "updatedAt" = NOW()
                """,
                (
                    projectId,
                    POSTGRESQL_RUNTIME_OBJECT_ID_START,
                    POSTGRESQL_PROTOCOL_ID_START,
                ),
                commit=False,
            )

        return {
            "deletedRelationsCount": (
                deletedRelationsCount
            ),
            "deletedSetsCount": (
                deletedSetsCount
            ),
            "deletedObjectsCount": (
                deletedObjectsCount
            ),
            "deletedProtocolsCount": (
                deletedProtocolsCount
            ),
        }

    def getProjectSharedUsers(self, projectId: int) -> List[int]:
        """Return the list of userIds with whom the given project is shared."""
        rows = self.db.fetchAll(
            """
            SELECT "userId"
              FROM project_shares
             WHERE "projectId" = %s
             ORDER BY "userId"
            """,
            (projectId,),
        )
        return [row["userId"] for row in rows]

    def setProjectSharedUsers(self, projectId: int, ownerId: int, userIds: List[int]) -> None:
        """Replace the share list of a project with the given userIds."""
        project = self.getProject(projectId, ownerId)
        if not project:
            raise ValueError("Project does not exist or is not owned by this user")

        cleanedUserIds: List[int] = []
        for rawId in userIds or []:
            try:
                uid = int(rawId)
            except (TypeError, ValueError):
                continue
            if uid not in cleanedUserIds:
                cleanedUserIds.append(uid)

        self.db.execute(
            """
            DELETE FROM project_shares
             WHERE "projectId" = %s
            """,
            (projectId,),
        )

        if not cleanedUserIds:
            return

        valuesSql = ",".join(["(%s, %s)"] * len(cleanedUserIds))
        params: List[Any] = []
        for uid in cleanedUserIds:
            params.extend([projectId, uid])

        self.db.execute(
            f"""
            INSERT INTO project_shares ("projectId", "userId")
            VALUES {valuesSql}
            """,
            tuple(params),
        )

    def ensureProjectProtocolIdFloor(
            self,
            projectId: int,
            nextProtocolId: int,
    ) -> int:
        """
        Ensure that future PostgreSQL protocol ids do not collide with
        objects already present in an imported project.sqlite.

        Scipion's SQLite Objects table uses one global id namespace for
        protocols and all their stored child objects.
        """
        projectId = int(projectId)

        nextProtocolId = max(
            int(nextProtocolId),
            POSTGRESQL_PROTOCOL_ID_START,
        )

        with self.db.transaction():
            cursor = self.db.execute(
                """
                INSERT INTO project_object_id_counters (
                    "projectId",
                    "nextObjectId",
                    "nextProtocolId"
                )
                VALUES (%s, %s, %s)
                ON CONFLICT ("projectId")
                DO UPDATE SET
                    "nextProtocolId" = GREATEST(
                        project_object_id_counters."nextProtocolId",
                        EXCLUDED."nextProtocolId"
                    ),
                    "updatedAt" = NOW()
                RETURNING "nextProtocolId"
                """,
                (
                    projectId,
                    POSTGRESQL_RUNTIME_OBJECT_ID_START,
                    nextProtocolId,
                ),
                commit=False,
            )

            row = cursor.fetchone()

        if (
                not row
                or row.get("nextProtocolId") is None
        ):
            raise RuntimeError(
                "Could not initialize protocol id floor "
                "for project %s"
                % projectId
            )

        return int(
            row["nextProtocolId"]
        )

    def allocateProjectProtocolId(
            self,
            projectId: int,
    ) -> int:
        """
        Allocate one compact PostgreSQL-owned protocol id.

        Protocol ids remain below the PostgreSQL runtime-object
        namespace. A legacy imported counter that was initialized from
        MAX(project.sqlite.Objects.id) is automatically rebased.

        SQLite collisions are handled by PostgresqlRuntimeMapper before
        assigning the candidate to a new protocol.
        """
        projectId = int(
            projectId
        )

        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO project_object_id_counters (
                    "projectId",
                    "nextObjectId",
                    "nextProtocolId"
                )
                VALUES (%s, %s, %s)
                ON CONFLICT ("projectId")
                DO NOTHING
                """,
                (
                    projectId,
                    POSTGRESQL_RUNTIME_OBJECT_ID_START,
                    POSTGRESQL_PROTOCOL_ID_START,
                ),
                commit=False,
            )

            counterRow = self.db.fetchOne(
                """
                SELECT "nextProtocolId"
                  FROM project_object_id_counters
                 WHERE "projectId" = %s
                   FOR UPDATE
                """,
                (
                    projectId,
                ),
            )

            if (
                    not counterRow
                    or counterRow.get(
                "nextProtocolId"
            ) is None
            ):
                raise RuntimeError(
                    "Could not lock protocol id counter "
                    "for project %s."
                    % projectId
                )

            maxRow = self.db.fetchOne(
                """
                SELECT COALESCE(
                           MAX(
                               CASE
                                   WHEN "protocolId"
                                        ~ '^[0-9]+$'
                                   THEN
                                       CASE
                                           WHEN
                                               ("protocolId")::numeric
                                               < %s
                                           THEN
                                               ("protocolId")::integer
                                           ELSE NULL
                                       END
                                   ELSE NULL
                               END
                           ),
                           1
                       ) AS value
                  FROM protocols
                 WHERE "projectId" = %s
                """,
                (
                    POSTGRESQL_RUNTIME_OBJECT_ID_START,
                    projectId,
                ),
            )

            existingCompactMax = int(
                (maxRow or {}).get(
                    "value"
                )
                or 1
            )

            minimumCandidate = max(
                existingCompactMax + 1,
                POSTGRESQL_PROTOCOL_ID_START,
            )

            storedCandidate = int(
                counterRow.get(
                    "nextProtocolId"
                )
                or POSTGRESQL_PROTOCOL_ID_START
            )

            # Previous imports initialized this counter using
            # MAX(project.sqlite.Objects.id), which could put protocol
            # ids inside the runtime-object namespace.
            if (
                    storedCandidate
                    >= POSTGRESQL_RUNTIME_OBJECT_ID_START
            ):
                protocolId = (
                    minimumCandidate
                )
            else:
                protocolId = max(
                    storedCandidate,
                    minimumCandidate,
                )

            if (
                    protocolId
                    >= POSTGRESQL_RUNTIME_OBJECT_ID_START
            ):
                raise RuntimeError(
                    "Compact protocol id namespace exhausted "
                    "for project %s. candidate=%s limit=%s"
                    % (
                        projectId,
                        protocolId,
                        POSTGRESQL_RUNTIME_OBJECT_ID_START,
                    )
                )

            self.db.execute(
                """
                UPDATE project_object_id_counters
                   SET "nextProtocolId" = %s,
                       "updatedAt" = NOW()
                 WHERE "projectId" = %s
                """,
                (
                    protocolId + 1,
                    projectId,
                ),
                commit=False,
            )

        return int(
            protocolId
        )

    def allocateProjectObjectId(
            self,
            projectId: int,
    ) -> int:
        """
        Allocate an id for a non-protocol Scipion runtime object.

        Runtime objects intentionally use a namespace separate from
        protocol ids.
        """
        projectId = int(projectId)

        with self.db.transaction():
            maxRow = self.db.fetchOne(
                """
                SELECT COALESCE(
                           MAX("scipionObjId"),
                           0
                       )::integer AS value
                  FROM scipion_objects
                 WHERE "projectId" = %s
                   AND "scipionObjId" IS NOT NULL
                """,
                (
                    projectId,
                ),
            )

            existingMax = int(
                (maxRow or {}).get("value")
                or 0
            )

            nextCandidate = max(
                existingMax + 1,
                POSTGRESQL_RUNTIME_OBJECT_ID_START,
            )

            self.db.execute(
                """
                INSERT INTO project_object_id_counters (
                    "projectId",
                    "nextObjectId",
                    "nextProtocolId"
                )
                VALUES (%s, %s, %s)
                ON CONFLICT ("projectId")
                DO UPDATE SET
                    "nextObjectId" = GREATEST(
                        project_object_id_counters."nextObjectId",
                        EXCLUDED."nextObjectId"
                    ),
                    "updatedAt" = NOW()
                """,
                (
                    projectId,
                    nextCandidate,
                    POSTGRESQL_PROTOCOL_ID_START,
                ),
                commit=False,
            )

            row = self.db.fetchOne(
                """
                UPDATE project_object_id_counters
                   SET "nextObjectId" =
                           "nextObjectId" + 1,
                       "updatedAt" = NOW()
                 WHERE "projectId" = %s
                 RETURNING
                       "nextObjectId" - 1
                       AS "objectId"
                """,
                (
                    projectId,
                ),
            )

        if not row or row.get("objectId") is None:
            raise RuntimeError(
                "Could not allocate Scipion object id "
                "for project %s."
                % projectId
            )

        return int(
            row["objectId"]
        )

    # -----------------------------
    # Protocol Methods
    # -----------------------------
    def saveProtocol(self, protocol: Dict[str, Any]) -> int:
        """Insert a new protocol row or update it if it already exists, then return its database id."""
        protocolId = protocol["info"].get("protocolId")
        projectId = protocol["info"].get("projectId")
        protocolClassName = protocol["info"].get("protocolClassName")

        if not protocolId:
            raise ValueError("Missing required field: protocolId")
        if not projectId:
            raise ValueError("Missing required field: projectId")
        if not protocolClassName:
            raise ValueError("Missing required field: protocolClassName")

        status = protocol["info"].get("status", "pending")
        params = protocol.get("values")
        parentIds = protocol.get("parentIds", []) or []
        childIds = protocol.get("childIds", []) or []

        # serializeParamsToJson
        paramsJson = None
        if params is not None:
            paramsJson = json.dumps(params, ensure_ascii=False)

        cur = self.db.execute(
            """
            INSERT INTO protocols (
                "projectId",
                "protocolId",
                "protocolClassName",
                "status",
                "params",
                "parentIds",
                "childIds"
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT ("projectId", "protocolId")
            DO UPDATE SET
                "status" = EXCLUDED."status",
                "params" = EXCLUDED."params",
                "parentIds" = EXCLUDED."parentIds",
                "childIds" = EXCLUDED."childIds"
            RETURNING id
            """,
            (
                projectId,
                str(protocolId),
                protocolClassName,
                status,
                paramsJson,
                parentIds,
                childIds,
            ),
        )
        return cur.fetchone()["id"]

    def getProjectProtocolDbIdMap(self, projectId: int) -> Dict[str, int]:
        rows = self.db.fetchAll(
            """
            SELECT id, "protocolId"
              FROM protocols
             WHERE "projectId" = %s
            """,
            (projectId,),
        )

        return {
            str(row["protocolId"]): int(row["id"])
            for row in rows
            if row.get("protocolId") is not None and row.get("id") is not None
        }

    def replaceProjectProtocolInputRefs(
            self,
            projectId: int,
            refs: List[Dict[str, Any]],
    ) -> int:
        def toOptionalInt(value: Any) -> Optional[int]:
            if value is None or value == "":
                return None

            try:
                return int(value)
            except Exception:
                try:
                    return int(float(value))
                except Exception:
                    return None

        self.db.execute(
            """
            DELETE FROM protocol_input_refs
             WHERE "projectId" = %s
            """,
            (projectId,),
        )

        cleanRefs: List[Dict[str, Any]] = []
        seen = set()

        for ref in refs or []:
            protocolDbId = toOptionalInt(ref.get("protocolDbId"))
            if protocolDbId is None or protocolDbId <= 0:
                continue

            inputName = str(ref.get("inputName") or "").strip()
            if not inputName:
                continue

            itemIndex = toOptionalInt(ref.get("itemIndex"))
            if itemIndex is None or itemIndex < 0:
                itemIndex = 0

            protocolId = str(ref.get("protocolId") or "").strip()
            if not protocolId:
                continue

            key = (protocolDbId, inputName, itemIndex)
            if key in seen:
                continue

            seen.add(key)

            parentProtocolDbId = toOptionalInt(ref.get("parentProtocolDbId"))
            if parentProtocolDbId is not None and parentProtocolDbId <= 0:
                parentProtocolDbId = None

            cleanRefs.append({
                "projectId": int(projectId),
                "protocolDbId": protocolDbId,
                "protocolId": protocolId,
                "inputName": inputName,
                "itemIndex": itemIndex,
                "parentProtocolDbId": parentProtocolDbId,
                "parentProtocolId": str(ref.get("parentProtocolId")).strip()
                if ref.get("parentProtocolId") not in (None, "") else None,
                "parentOutputName": str(ref.get("parentOutputName")).strip()
                if ref.get("parentOutputName") not in (None, "") else None,
                "objectClassName": str(ref.get("objectClassName")).strip()
                if ref.get("objectClassName") not in (None, "") else None,
                "objectId": str(ref.get("objectId")).strip()
                if ref.get("objectId") not in (None, "") else None,
            })

        if not cleanRefs:
            return 0

        valuesSql = ",".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(cleanRefs))
        params: List[Any] = []

        for ref in cleanRefs:
            params.extend([
                ref["projectId"],
                ref["protocolDbId"],
                ref["protocolId"],
                ref["inputName"],
                ref["itemIndex"],
                ref["parentProtocolDbId"],
                ref["parentProtocolId"],
                ref["parentOutputName"],
                ref["objectClassName"],
                ref["objectId"],
            ])

        self.db.execute(
            f"""
            INSERT INTO protocol_input_refs (
                "projectId",
                "protocolDbId",
                "protocolId",
                "inputName",
                "itemIndex",
                "parentProtocolDbId",
                "parentProtocolId",
                "parentOutputName",
                "objectClassName",
                "objectId"
            )
            VALUES {valuesSql}
            ON CONFLICT ("projectId", "protocolDbId", "inputName", "itemIndex")
            DO UPDATE SET
                "protocolId" = EXCLUDED."protocolId",
                "parentProtocolDbId" = EXCLUDED."parentProtocolDbId",
                "parentProtocolId" = EXCLUDED."parentProtocolId",
                "parentOutputName" = EXCLUDED."parentOutputName",
                "objectClassName" = EXCLUDED."objectClassName",
                "objectId" = EXCLUDED."objectId",
                "updatedAt" = NOW()
            """,
            tuple(params),
        )

        return len(cleanRefs)

    def listProtocolInputRefs(
            self,
            projectId: int,
            protocolDbId: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if protocolDbId is None:
            return self.db.fetchAll(
                """
                SELECT *
                  FROM protocol_input_refs
                 WHERE "projectId" = %s
                 ORDER BY "protocolDbId", "inputName", "itemIndex"
                """,
                (projectId,),
            )

        return self.db.fetchAll(
            """
            SELECT *
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "inputName", "itemIndex"
            """,
            (projectId, protocolDbId),
        )

    def replaceProjectProtocolDependencies(
            self,
            projectId: int,
            edges: List[Tuple[int, int]],
    ) -> int:
        self.db.execute(
            """
            DELETE FROM protocol_dependencies
             WHERE "projectId" = %s
            """,
            (projectId,),
        )

        cleanEdges: List[Tuple[int, int]] = []
        seen = set()

        for parentDbId, childDbId in edges or []:
            try:
                parentDbId = int(parentDbId)
                childDbId = int(childDbId)
            except Exception:
                continue

            if parentDbId <= 0 or childDbId <= 0:
                continue
            if parentDbId == childDbId:
                continue

            key = (parentDbId, childDbId)
            if key in seen:
                continue

            seen.add(key)
            cleanEdges.append(key)

        if not cleanEdges:
            return 0

        valuesSql = ",".join(["(%s, %s, %s)"] * len(cleanEdges))
        params: List[Any] = []

        for parentDbId, childDbId in cleanEdges:
            params.extend([projectId, parentDbId, childDbId])

        self.db.execute(
            f"""
            INSERT INTO protocol_dependencies (
                "projectId",
                "parentProtocolDbId",
                "childProtocolDbId"
            )
            VALUES {valuesSql}
            """,
            tuple(params),
        )

        return len(cleanEdges)

    def listProjectProtocolDependencies(self, projectId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT
                "projectId",
                "parentProtocolDbId",
                "childProtocolDbId",
                "createdAt"
              FROM protocol_dependencies
             WHERE "projectId" = %s
             ORDER BY "parentProtocolDbId", "childProtocolDbId"
            """,
            (projectId,),
        )

    def getProjectProtocolAdjacencyMap(self, projectId: int) -> Dict[str, Dict[str, List[str]]]:
        rows = self.db.fetchAll(
            """
            SELECT
                parent."protocolId" AS "parentProtocolId",
                child."protocolId" AS "childProtocolId"
            FROM protocol_dependencies d
            JOIN protocols parent
              ON parent.id = d."parentProtocolDbId"
             AND parent."projectId" = d."projectId"
            JOIN protocols child
              ON child.id = d."childProtocolDbId"
             AND child."projectId" = d."projectId"
            WHERE d."projectId" = %s
            ORDER BY child.id, parent.id
            """,
            (projectId,),
        )

        adjacency: Dict[str, Dict[str, List[str]]] = {}

        for row in rows:
            parentProtocolId = row.get("parentProtocolId")
            childProtocolId = row.get("childProtocolId")

            if parentProtocolId is None or childProtocolId is None:
                continue

            parentProtocolId = str(parentProtocolId)
            childProtocolId = str(childProtocolId)

            adjacency.setdefault(parentProtocolId, {"parents": [], "children": []})
            adjacency.setdefault(childProtocolId, {"parents": [], "children": []})

            if childProtocolId not in adjacency[parentProtocolId]["children"]:
                adjacency[parentProtocolId]["children"].append(childProtocolId)

            if parentProtocolId not in adjacency[childProtocolId]["parents"]:
                adjacency[childProtocolId]["parents"].append(parentProtocolId)

        return adjacency

    def getProtocolByProtocolId(self, protocolId: int, projectId: int) -> Optional[Dict]:
        """Retrieve a protocol by id."""
        return self.db.fetchOne(
            'SELECT * FROM protocols WHERE "protocolId" = %s AND "projectId" = %s',
            (str(protocolId), projectId),
        )

    def getProtocols(self, projectId: Optional[int] = None) -> List[Dict]:
        """List all protocols, optionally filtered by projectId."""
        if projectId is None:
            return self.db.fetchAll('SELECT * FROM protocols ORDER BY "createdAt" DESC')
        return self.db.fetchAll(
            'SELECT * FROM protocols WHERE "projectId"=%s ORDER BY "createdAt" DESC',
            (projectId,),
        )

    def getProjectProtocolByProtocolId(
            self,
            projectId: int,
            protocolId: int,
    ) -> Optional[Dict[str, Any]]:
        return self.db.fetchOne(
            """
            SELECT
                id,
                "projectId",
                "protocolId",
                "protocolClassName",
                status,
                params,
                "parentIds",
                "childIds",
                "relationsSynchronized",
                "createdAt",
                "updatedAt"
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
             LIMIT 1
            """,
            (int(projectId), str(protocolId)),
        )

    def countProjectProtocols(self, projectId: int) -> int:
        row = self.db.fetchOne(
            """
            SELECT COUNT(*) AS count
              FROM protocols
             WHERE "projectId" = %s
            """,
            (projectId,),
        )

        if not row:
            return 0

        value = row.get("count") if isinstance(row, dict) else row[0]
        return int(value or 0)

    def updateProtocol(self, protocol: Dict[str, Any]) -> None:
        """Update protocol fields dynamically."""
        updates = []
        params = []

        if "protocolClassName" in protocol and protocol["protocolClassName"] is not None:
            updates.append('"protocolClassName"=%s')
            params.append(protocol["protocolClassName"])

        if "params" in protocol and protocol["params"] is not None:
            updates.append("params=%s")
            params.append(protocol["params"])

        if "status" in protocol and protocol["status"] is not None:
            updates.append("status=%s")
            params.append(protocol["status"])

        if not updates:
            return

        params.append(protocol["id"])
        sql = f"""
            UPDATE protocols
               SET {", ".join(updates)},
                   "updatedAt" = NOW()
             WHERE "id"=%s
        """
        self.db.execute(sql, tuple(params))

    def deleteProtocol(self, projectId, protocolList: Any) -> bool:
        """Delete protocols"""
        for prot in protocolList:
            protId = prot.getObjId()
            self.db.execute(
                'DELETE FROM protocols  WHERE "protocolId" = %s AND "projectId" = %s',
                (str(protId), projectId),
            )
        return True

    def updateProtocolDependencies(self, protocolId: str, parentIds: list, childIds: list):
        query = 'UPDATE protocols SET "parentIds" = %s, "childIds" = %s, "updatedAt" = NOW() WHERE "protocolId" = %s'
        self.db.execute(query, (parentIds, childIds, protocolId))

    def deleteProjectProtocolsNotInProtocolIds(
        self,
        projectId: int,
        protocolIdsToKeep: List[str],
    ) -> int:
        keepSet = {
            str(protocolId).strip()
            for protocolId in (protocolIdsToKeep or [])
            if str(protocolId).strip()
        }

        rows = self.db.fetchAll(
            """
            SELECT id, "protocolId"
              FROM protocols
             WHERE "projectId" = %s
            """,
            (projectId,),
        )

        staleDbIds = [
            int(row["id"])
            for row in rows
            if str(row.get("protocolId", "")).strip() not in keepSet
        ]

        if not staleDbIds:
            return 0

        self.db.execute(
            """
            DELETE FROM protocols
             WHERE "projectId" = %s
               AND id = ANY(%s)
            """,
            (projectId, staleDbIds),
        )

        return len(staleDbIds)

    def resolveProtocolStepTarget(self, projectPath: str, protocolId: int) -> Optional[Dict[str, Any]]:
        return self.db.fetchOne(
            """
            SELECT p."projectId", p.id AS "protocolDbId", p."protocolId"
              FROM protocols p
              JOIN projects pr ON pr.id = p."projectId"
             WHERE p."protocolId" = %s
               AND pr.name = %s
             LIMIT 1
            """,
            (str(protocolId), str(projectPath)),
        )

    def deleteProtocolSteps(
            self,
            projectId: int,
            protocolId: int,
    ) -> int:
        cursor = self.db.execute(
            """
            DELETE FROM protocol_steps
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                int(projectId),
                str(protocolId),
            ),
        )

        return int(
            cursor.rowcount
            or 0
        )

    def prepareProtocolStepsForContinue(
            self,
            projectId: int,
            protocolId: int,
            statusValue,
            event: str = "continue_resume",
    ) -> int:
        cursor = self.db.execute(
            """
            UPDATE protocol_steps
               SET status = %s,
                   "initTime" = NULL,
                   "endTime" = NULL,
                   "elapsedSeconds" = 0,
                   error = NULL,
                   event = %s,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                str(statusValue),
                str(event),
                int(projectId),
                str(protocolId),
            ),
        )

        return int(cursor.rowcount or 0)

    def replaceProtocolSteps(self, projectId: int, protocolDbId: int, protocolId: int,
                             steps: List[Dict[str, Any]]) -> None:
        steps = list(steps or [])
        stepIndexes = [int(step["index"]) for step in steps]

        for step in steps:
            self.upsertProtocolStep(projectId, protocolDbId, protocolId, step)

        if stepIndexes:
            self.db.execute(
                """
                DELETE FROM protocol_steps
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                   AND NOT ("stepIndex" = ANY(%s))
                """,
                (projectId, protocolDbId, stepIndexes),
            )
        else:
            self.db.execute(
                'DELETE FROM protocol_steps WHERE "projectId" = %s AND "protocolDbId" = %s',
                (projectId, protocolDbId),
            )

    def upsertProtocolStep(
            self,
            projectId: int,
            protocolDbId: int,
            protocolId: int,
            step: Dict[str, Any],
    ) -> None:
        statusText = str(step.get("status") or "").strip().lower()
        terminalStep = statusText in {"finished", "failed", "aborted", "interactive", "done"}
        self.db.execute(
            """
            INSERT INTO protocol_steps (
                "projectId",
                "protocolDbId",
                "protocolId",
                "stepIndex",
                "stepClassName",
                name,
                status,
                prerequisites,
                args,
                "argsText",
                "resultFiles",
                "initTime",
                "endTime",
                "elapsedSeconds",
                error,
                interactive,
                "needsGpu",
                event,
                "schemaVersion"
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb,
                %s::jsonb, %s, %s::jsonb,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (
                "projectId",
                "protocolDbId",
                "stepIndex"
            )
            DO UPDATE SET
                "stepClassName" =
                    EXCLUDED."stepClassName",
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                prerequisites =
                    EXCLUDED.prerequisites,
                args = EXCLUDED.args,
                "argsText" =
                    EXCLUDED."argsText",
                "resultFiles" =
                    EXCLUDED."resultFiles",
                "initTime" = COALESCE(EXCLUDED."initTime", protocol_steps."initTime"),
                "endTime" = COALESCE(EXCLUDED."endTime", protocol_steps."endTime"),
                "elapsedSeconds" = GREATEST(COALESCE(protocol_steps."elapsedSeconds", 0.0), COALESCE(EXCLUDED."elapsedSeconds", 0.0)),
                error = EXCLUDED.error,
                interactive =
                    EXCLUDED.interactive,
                "needsGpu" =
                    EXCLUDED."needsGpu",
                event = EXCLUDED.event,
                "schemaVersion" =
                    EXCLUDED."schemaVersion",
                "updatedAt" = NOW()
            """,
            (
                projectId,
                protocolDbId,
                str(protocolId),
                step["index"],
                step.get(
                    "stepClassName"
                ),
                step["name"],
                step["status"],
                json.dumps(
                    step.get(
                        "prerequisites"
                    )
                    or []
                ),
                json.dumps(
                    step.get("args")
                ),
                step.get(
                    "argsText"
                ),
                json.dumps(
                    step.get(
                        "resultFiles"
                    )
                ),
                step.get(
                    "initTime"
                ),
                step.get(
                    "endTime"
                ),
                step.get(
                    "elapsedSeconds"
                ),
                step.get(
                    "error"
                ),
                bool(
                    step.get(
                        "interactive"
                    )
                ),
                bool(
                    step.get(
                        "needsGpu",
                        True,
                    )
                ),
                step.get(
                    "event"
                ),
                int(
                    step.get(
                        "schemaVersion",
                        2,
                    )
                ),
            ),
        )
        if terminalStep:
            self.db.execute(
                """
                UPDATE protocol_steps
                   SET "endTime" = CASE
                           WHEN "initTime" IS NULL THEN "endTime"
                           ELSE COALESCE("endTime", CURRENT_TIMESTAMP)
                       END,
                       "elapsedSeconds" = GREATEST(
                           COALESCE("elapsedSeconds", 0.0),
                           CASE
                               WHEN "initTime" IS NULL THEN 0.0
                               ELSE GREATEST(
                                   0.0,
                                   EXTRACT(EPOCH FROM (COALESCE("endTime", CURRENT_TIMESTAMP) - "initTime"))::double precision
                               )
                           END
                       ),
                       "updatedAt" = CURRENT_TIMESTAMP
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                   AND "stepIndex" = %s
                """,
                (projectId, protocolDbId, step["index"]),
            )

    def listProtocolSteps(
            self,
            projectId: int,
            protocolId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            f"""
            SELECT
                "stepIndex" AS index,
                "stepClassName",
                name,
                status,
                prerequisites,
                args,
                "argsText",
                "resultFiles",
                "initTime",
                "endTime",
                {
                    PROTOCOL_STEP_EFFECTIVE_ELAPSED_SQL
                } AS "elapsedSeconds",
                error,
                interactive,
                "needsGpu",
                event,
                "schemaVersion",
                "updatedAt"
            FROM protocol_steps
            WHERE "projectId" = %s
              AND "protocolId" = %s
            ORDER BY "stepIndex" ASC
            """,
            (
                projectId,
                str(protocolId),
            ),
        )

    def updateProtocolStepStatus(
            self,
            projectId: int,
            protocolId: int,
            stepIndex: int,
            stepStatus: str,
    ) -> Optional[Dict[str, Any]]:
        return self.db.executeReturningOne(
            """
            UPDATE protocol_steps
               SET status = %s,
                   event = 'manual-status-update',
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "protocolId" = %s
               AND "stepIndex" = %s
            RETURNING
                "stepIndex" AS index,
                "stepClassName",
                name,
                status,
                prerequisites,
                args,
                "argsText",
                "resultFiles",
                "initTime",
                "endTime",
                "elapsedSeconds",
                error,
                interactive,
                "needsGpu",
                event,
                "schemaVersion",
                "updatedAt"
            """,
            (
                stepStatus,
                projectId,
                str(protocolId),
                stepIndex,
            ),
        )

    def getProjectProtocolStepsByProtocolId(
            self,
            projectId: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        rows = self.db.fetchAll(
            f"""
            SELECT
                "protocolId",
                "stepIndex" AS "index",
                name,
                status,
                prerequisites,
                args,
                "initTime",
                "endTime",
                {
                    PROTOCOL_STEP_EFFECTIVE_ELAPSED_SQL
                } AS "elapsedSeconds",
                error,
                interactive,
                "needsGpu",
                event,
                "updatedAt"
            FROM protocol_steps
            WHERE "projectId" = %s
            ORDER BY
                "protocolId",
                "stepIndex" ASC
            """,
            (
                projectId,
            ),
        )

        result: Dict[str,  List[Dict[str, Any]],] = {}

        for row in rows:
            protocolId = str(row["protocolId"])
            step = dict(row)

            step.pop("protocolId", None,)

            result.setdefault(protocolId,  [],).append(step)

        return result

    def getProjectProtocolStepSummaryByProtocolId(
            self,
            projectId: int,
    ) -> Dict[str, Dict[str, Any]]:
        rows = self.db.fetchAll(
            f"""
            WITH effective_steps AS (
                SELECT
                    "protocolId",
                    status,
                    interactive,
                    "updatedAt",
                    {
                        PROTOCOL_STEP_EFFECTIVE_ELAPSED_SQL
                    } AS "effectiveElapsedSeconds"
                FROM protocol_steps
                WHERE "projectId" = %s
            )
            SELECT
                "protocolId",

                COUNT(*)::int
                    AS "numberOfSteps",

                COUNT(*) FILTER (
                    WHERE LOWER(
                        COALESCE(
                            status,
                            ''
                        )
                    ) IN (
                        'finished',
                        'done'
                    )
                )::int
                    AS "stepsDone",

                COALESCE(
                    SUM(
                        "effectiveElapsedSeconds"
                    ),
                    0.0
                )::double precision
                    AS "elapsedSeconds",

                BOOL_OR(
                    interactive
                ) AS "isInteractive",

                MAX(
                    "updatedAt"
                ) AS "updatedAt"

            FROM effective_steps
            GROUP BY "protocolId"
            ORDER BY "protocolId"
            """,
            (
                projectId,
            ),
        )

        result: Dict[
            str,
            Dict[str, Any],
        ] = {}

        for row in rows or []:
            protocolId = str(
                row.get(
                    "protocolId"
                )
                or ""
            ).strip()

            if not protocolId:
                continue

            result[
                protocolId
            ] = {
                "numberOfSteps": int(
                    row.get(
                        "numberOfSteps"
                    )
                    or 0
                ),
                "stepsDone": int(
                    row.get(
                        "stepsDone"
                    )
                    or 0
                ),
                "elapsedSeconds": (
                    row.get(
                        "elapsedSeconds"
                    )
                ),
                "isInteractive": bool(
                    row.get(
                        "isInteractive"
                    )
                ),
                "updatedAt": row.get(
                    "updatedAt"
                ),
            }

        return result

    # -----------------------------
    # Settings Methods
    # -----------------------------
    def getUserSettings(self, userId: int) -> Dict[str, Any]:
        # getUserSettings
        row = self.db.fetchOne(
            """
            SELECT settings
              FROM user_settings
             WHERE "userId" = %s
            """,
            (userId,),
        )
        if not row or row.get("settings") is None:
            return {}
        return row["settings"]

    def upsertUserSettings(self, userId: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        # upsertUserSettings
        cur = self.db.execute(
            """
            INSERT INTO user_settings ("userId", settings, "updatedAt")
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT ("userId")
            DO UPDATE SET
                settings = EXCLUDED.settings,
                "updatedAt" = NOW()
            RETURNING settings
            """,
            (userId, _toJsonParam(settings)),
        )
        row = cur.fetchone()
        return row["settings"] if row and row.get("settings") is not None else {}

    def getInstanceSettings(self) -> Dict[str, Any]:
        # getInstanceSettings
        row = self.db.fetchOne(
            """
            SELECT settings
              FROM instance_settings
             WHERE id = 1
            """
        )
        if not row or row.get("settings") is None:
            return {}
        return row["settings"]

    def upsertInstanceSettings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        # upsertInstanceSettings
        cur = self.db.execute(
            """
            INSERT INTO instance_settings (id, settings, "updatedAt")
            VALUES (1, %s::jsonb, NOW())
            ON CONFLICT (id)
            DO UPDATE SET
                settings = EXCLUDED.settings,
                "updatedAt" = NOW()
            RETURNING settings
            """,
            (_toJsonParam(settings),),
        )
        row = cur.fetchone()
        return row["settings"] if row and row.get("settings") is not None else {}
