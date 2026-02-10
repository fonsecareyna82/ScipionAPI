# postgresql.py

import json
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Iterator
from pyworkflow.mapper.mapper import Mapper  # Base class from Scipion


def _toJsonParam(value: Any) -> Any:
    # toJsonParam
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value, dumps=json.dumps)
    return value


class PostgresqlDb:
    """Class to handle PostgreSQL connection and basic operations."""

    def __init__(self, dbName: str, user: str, password: str, host: str = "localhost", port: int = 5432):
        self.conn = psycopg2.connect(dbname=dbName, user=user, password=password, host=host, port=port)
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, query: str, params: Optional[tuple] = None, commit: bool = True) -> Any:
        """Execute a SQL command."""
        self.cursor.execute(query, params)
        if commit:
            self.conn.commit()
        return self.cursor

    @contextmanager
    def transaction(self) -> Iterator["PostgresqlDb"]:
        # transaction
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def fetchOne(self, query: str, params: Optional[tuple] = None) -> Optional[Dict]:
        """Fetch a single row."""
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

    def fetchAll(self, query: str, params: Optional[tuple] = None) -> List[Dict]:
        """Fetch all rows."""
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()
        self.conn.close()


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

        # CreateProtocolsTableLegacy (kept as-is for now)
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS protocols (
                id SERIAL PRIMARY KEY,
               CREATE TABLE IF NOT EXISTS protocols (
               id SERIAL PRIMARY KEY,
               "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
               "protocolId" TEXT NOT NULL,
               "protocolClassName" TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'pending',
               params JSONB,
               "parentIds" JSONB NOT NULL DEFAULT '[]'::jsonb,
               "childIds" JSONB NOT NULL DEFAULT '[]'::jsonb,
               "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
               "updatedAt" TIMESTAMPTZ
            );
            
            CREATE UNIQUE INDEX IF NOT EXISTS protocols_project_protocol_ux
              ON protocols("projectId", "protocolId");
            """
        )

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

        # -----------------------------
        # Tag Assignments Methods
        # -----------------------------

    def getProtocolTagIds(self, projectId: int, protocolDbId: int) -> List[str]:
        # getProtocolTagIds
        rows = self.db.fetchAll(
            """
            SELECT "tagId"
              FROM protocol_tag_assignments
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "tagId" ASC
            """,
            (projectId, protocolDbId),
        )
        return [r["tagId"] for r in rows if r.get("tagId")]

    def setProtocolTagIds(self, projectId: int, protocolDbId: int, tagIds: List[str]) -> Dict[str, Any]:
        # setProtocolTagIds
        cleanedTagIds: List[str] = []
        for rawId in tagIds or []:
            if rawId is None:
                continue
            tid = str(rawId).strip()
            if tid and tid not in cleanedTagIds:
                cleanedTagIds.append(tid)

        if not cleanedTagIds:
            with self.db.transaction() as tx:
                tx.execute(
                    """
                    DELETE FROM protocol_tag_assignments
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                    """,
                    (projectId, protocolDbId),
                    commit=False,
                )
            return {"tagIds": [], "missingTagIds": []}

        existing = self.db.fetchAll(
            """
            SELECT id
              FROM protocol_tags
             WHERE "projectId" = %s
               AND id = ANY(%s)
            """,
            (projectId, cleanedTagIds),
        )
        existingSet = {r["id"] for r in existing if r.get("id")}
        missingTagIds = [tid for tid in cleanedTagIds if tid not in existingSet]
        finalTagIds = [tid for tid in cleanedTagIds if tid in existingSet]

        with self.db.transaction() as tx:
            tx.execute(
                """
                DELETE FROM protocol_tag_assignments
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (projectId, protocolDbId),
                commit=False,
            )

            if finalTagIds:
                valuesSql = ",".join(["(%s, %s, %s)"] * len(finalTagIds))
                params: List[Any] = []
                for tid in finalTagIds:
                    params.extend([projectId, protocolDbId, tid])

                tx.execute(
                    f"""
                       INSERT INTO protocol_tag_assignments ("projectId", "protocolDbId", "tagId")
                       VALUES {valuesSql}
                       ON CONFLICT DO NOTHING
                       """,
                    tuple(params),
                    commit=False,
                )

        return {"tagIds": finalTagIds, "missingTagIds": missingTagIds}

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
            ORDER BY "createdAt" DESC
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

    def deleteProject(self, projectId: int, ownerId: int) -> bool:
        """Delete the project for a given owner."""
        cursor = self.db.execute(
            'DELETE FROM "projects" WHERE "id" = %s AND "ownerId" = %s',
            (projectId, ownerId),
        )
        return cursor.rowcount > 0

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

    # -----------------------------
    # Protocol Methods
    # -----------------------------
    def saveProtocol(self, protocol: Dict[str, Any]) -> int:
        """Insert a new protocol row and return its database id."""
        protocolId = protocol.get("protocolId")
        projectId = protocol.get("projectId")
        protocolClassName = protocol.get("protocolClassName")

        if not protocolId:
            raise ValueError("Missing required field: protocolId")
        if not projectId:
            raise ValueError("Missing required field: projectId")
        if not protocolClassName:
            raise ValueError("Missing required field: protocolClassName")

        status = protocol.get("status", "pending")
        params = protocol.get("params")
        parentIds = protocol.get("parentIds", [])
        childIds = protocol.get("childIds", [])

        cur = self.db.execute(
            """
            INSERT INTO protocols (
                "projectId",
                "protocolId",
                "protocolClassName",
                status,
                params,
                "parentIds",
                "childIds"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                projectId,
                str(protocolId),
                protocolClassName,
                status,
                params,
                parentIds,
                childIds,
            ),
        )
        return cur.fetchone()["id"]

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

    def deleteProtocol(self, protocolId: int) -> bool:
        """Delete a protocol by id."""
        cursor = self.db.execute(
            'DELETE FROM protocols WHERE "id"=%s',
            (protocolId,),
        )
        return cursor.rowcount > 0

    def updateProtocolDependencies(self, protocolId: str, parentIds: list, childIds: list):
        query = 'UPDATE protocols SET "parentIds" = %s, "childIds" = %s, "updatedAt" = NOW() WHERE "protocolId" = %s'
        self.db.execute(query, (parentIds, childIds, protocolId))

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
