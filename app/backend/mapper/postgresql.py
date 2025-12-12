# postgresql.py

import psycopg2
import psycopg2.extras
from collections import OrderedDict
from typing import Optional, List, Dict, Any
from pyworkflow.mapper.mapper import Mapper  # Base class from Scipion


class PostgresqlDb:
    """Class to handle PostgreSQL connection and basic operations."""

    def __init__(self, dbName: str, user: str, password: str, host: str = 'localhost', port: int = 5432):
        self.conn = psycopg2.connect(
            dbname=dbName, user=user, password=password, host=host, port=port
        )
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, query: str, params: Optional[tuple] = None) -> Any:
        """Execute a SQL command."""
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor

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
        """Create projects and protocols tables if they do not exist."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                ownerId INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                createdAt TIMESTAMP DEFAULT NOW(),
                updatedAt TIMESTAMP
            );
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS protocols (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                createdAt TIMESTAMP DEFAULT NOW(),
                parameters JSONB
            );
        """)
        # Table for shared projects with future-proof permission field
        self.db.execute("""
                   CREATE TABLE IF NOT EXISTS project_shares (
                       id SERIAL PRIMARY KEY,
                       "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                       "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                       "permission" TEXT NOT NULL DEFAULT 'full',
                       "createdAt" TIMESTAMP DEFAULT NOW(),
                       "updatedAt" TIMESTAMP,
                       UNIQUE ("projectId", "userId")
                   );
               """)

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
            '''
            SELECT *
              FROM users
             WHERE email = %s
            ''',
            (email,)
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

        # Build SET clause dynamically
        setClauses = []
        params = []
        for idx, (col, val) in enumerate(fields.items(), start=1):
            setClauses.append(f'"{col}" = %s')
            params.append(val)

        sql = f'''
            UPDATE users
               SET {', '.join(setClauses)}
             WHERE id = %s
        '''
        params.append(userId)
        self.db.execute(sql, tuple(params))

    def listUsers(self, excludeUserId: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return a list of users for selection in the UI.
        If excludeUserId is provided, that user will be filtered out.
        """
        if excludeUserId is None:
            return self.db.fetchAll(
                '''
                SELECT
                  id,
                  email,
                  "firstName",
                  "lastName",
                  institution,
                  role
                FROM users
                ORDER BY "firstName", "lastName", email
                '''
            )
        else:
            return self.db.fetchAll(
                '''
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
                ''',
                (excludeUserId,),
            )

    # -----------------------------
    # Project Methods
    # -----------------------------
    def insertProject(self, ownerId: int, name: str, description: Optional[str] = None,
                      status: str = "active") -> int:
        """Insert a new project and return its id."""
        cur = self.db.execute(
            'INSERT INTO projects ("ownerId", name, description, status) VALUES (%s, %s, %s, %s) RETURNING id',
            (ownerId, name, description, status)
        )
        return cur.fetchone()['id']

    def getProject(self, projectId: int, userId: int) -> Optional[Dict]:
        """
        Retrieve a project by id that is accessible to the given user.
        A project is accessible if:
          - The user is the owner, or
          - There is an entry in project_shares for (projectId, userId).

        It also annotates the row with:
          - isOwner: bool
          - isShared: bool (true if there is a share row for this user)
          - permission: text (permission for this user, default 'full')
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
            userId,  # isOwner check
            userId,  # isShared EXISTS
            userId,  # permission subquery
            projectId,
            userId,  # owner condition in WHERE
            userId,  # shared condition in WHERE
        )
        return self.db.fetchOne(query, params)

    # -----------------------------
    # Project share methods
    # -----------------------------
    def shareProjectWithUser(self, projectId: int, targetUserId: int, permission: str = "full") -> Dict[str, Any]:
        """
        Create or update a project share entry between projectId and targetUserId.

        Requires a unique constraint on (projectId, userId) in project_shares.
        If the row already exists, only the permission and updatedAt are changed.
        """
        cur = self.db.execute(
            '''
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
            ''',
            (projectId, targetUserId, permission),
        )
        return cur.fetchone()

    def revokeProjectShare(self, projectId: int, userId: int) -> bool:
        """
        Remove a share from project_shares.
        """
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
        """
        List all shares for a given project.
        """
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
        List all projects the user can see:
        - owned projects (isOwner=True, isShared=False, permission='owner')
        - shared projects (isOwner=False, isShared=True, permission from project_shares)
        Results are ordered by createdAt (from projects table) descending.
        """
        return self.db.fetchAll(
            '''
            SELECT *
            FROM (
                -- Owned projects
                SELECT
                    p.*,
                    TRUE  AS "isOwner",
                    FALSE AS "isShared",
                    'owner'::text AS "permission"
                FROM projects p
                WHERE p."ownerId" = %s

                UNION ALL

                -- Projects shared with this user
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
            ''',
            (ownerId, ownerId, ownerId)
        )

    def updateProject(
        self,
        projectId: int,
        ownerId: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update the given fields on a project owned by ownerId.
        Returns the updated project dict or None if not found.
        """
        # Gather SET clauses dynamically
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

        # If nothing to update, just return the existing project
        if not setClauses:
            return self.getProject(projectId, ownerId)

        # Always update the timestamp
        setClauses.append('"updatedAt" = NOW()')

        # Build and execute the UPDATE statement
        sql = f'''
            UPDATE "projects"
               SET {', '.join(setClauses)}
             WHERE "id" = %s
               AND "ownerId" = %s
        '''
        params.extend([projectId, ownerId])
        self.db.execute(sql, tuple(params))

        # Return the newly updated project
        return self.getProject(projectId, ownerId)

    def deleteProject(self, projectId: int, ownerId: int) -> bool:
        """
        Delete the project (and its protocols) for a given owner.
        Returns True if a row was deleted, False otherwise.
        """
        # Execute the DELETE and grab the cursor to inspect rowcount
        cursor = self.db.execute(
            'DELETE FROM "projects" WHERE "id" = %s AND "ownerId" = %s',
            (projectId, ownerId),
        )

        # psycopg2 cursor.rowcount holds number of rows affected
        return cursor.rowcount > 0

    def getProjectSharedUsers(self, projectId: int) -> List[int]:
        """
        Return the list of userIds with whom the given project is shared.
        """
        rows = self.db.fetchAll(
            '''
            SELECT "userId"
              FROM project_shares
             WHERE "projectId" = %s
             ORDER BY "userId"
            ''',
            (projectId,),
        )
        return [row["userId"] for row in rows]

    def setProjectSharedUsers(self, projectId: int, ownerId: int, userIds: List[int]) -> None:
        """
        Replace the share list of a project with the given userIds.

        Semantics:
        - The project must exist and belong to ownerId.
        - Existing entries in project_shares for this project are removed.
        - New rows (projectId, userId) are inserted for each userId.
        - Owner is not stored in project_shares (he already owns the project).
        """
        # Ensure project exists and belongs to ownerId
        project = self.getProject(projectId, ownerId)
        if not project:
            raise ValueError("Project does not exist or is not owned by this user")

        # NormalizeAndDeduplicateUserIds
        cleanedUserIds: List[int] = []
        for rawId in userIds or []:
            try:
                uid = int(rawId)
            except (TypeError, ValueError):
                continue
            if uid not in cleanedUserIds:
                cleanedUserIds.append(uid)

        # RemoveExistingSharesForThisProject
        self.db.execute(
            '''
            DELETE FROM project_shares
             WHERE "projectId" = %s
            ''',
            (projectId,),
        )

        # If no users to share with, we are done
        if not cleanedUserIds:
            return

        # BulkInsertNewShareRows
        valuesSql = ",".join(["(%s, %s)"] * len(cleanedUserIds))
        params: List[Any] = []
        for uid in cleanedUserIds:
            params.extend([projectId, uid])

        self.db.execute(
            f'''
            INSERT INTO project_shares ("projectId", "userId")
            VALUES {valuesSql}
            ''',
            tuple(params),
        )

    # -----------------------------
    # Protocol Methods
    # -----------------------------
    def saveProtocol(self, protocol: Dict[str, Any]) -> int:
        """Insert a new protocol and return its id."""
        cur = self.db.execute(
            """
            INSERT INTO protocols ("projectId", "protocolClassName", status, params)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                protocol["projectId"],
                protocol["protocolClassName"],
                protocol.get("status", "pending"),
                protocol.get("params"),
            ),
        )
        return cur.fetchone()["id"]

    def getProtocolByProtocolId(self, protocolId: int, projectId: int) -> Optional[Dict]:
        """Retrieve a protocol by id."""
        return self.db.fetchOne(
            'SELECT * FROM protocols WHERE "protocolId" = %s AND "projectId" = %s',
            (str(protocolId), projectId)
        )

    def getProtocols(self, projectId: Optional[int] = None) -> List[Dict]:
        """List all protocols, optionally filtered by projectId."""
        if projectId is None:
            return self.db.fetchAll(
                'SELECT * FROM protocols ORDER BY "createdAt" DESC'
            )
        else:
            return self.db.fetchAll(
                'SELECT * FROM protocols WHERE "projectId"=%s ORDER BY "createdAt" DESC',
                (projectId,)
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
               SET {', '.join(updates)},
                   "updatedAt" = NOW()
             WHERE "id"=%s
        """
        self.db.execute(sql, tuple(params))

    def deleteProtocol(self, protocolId: int) -> bool:
        """Delete a protocol by id."""
        cursor = self.db.execute(
            'DELETE FROM protocols WHERE "id"=%s',
            (protocolId,)
        )
        return cursor.rowcount > 0

    def updateProtocolDependencies(self, protocolId: str, parentIds: list, childIds: list):
        query ='UPDATE protocols SET "parentIds" = %s, "childIds" = %s, "updatedAt" = NOW() WHERE "protocolId" = %s'
        self.db.execute(query, (parentIds, childIds, protocolId))
