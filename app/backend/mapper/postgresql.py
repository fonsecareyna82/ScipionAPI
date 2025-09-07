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

    def getProject(self, projectId: int, ownerId: int) -> Optional[Dict]:
        """Retrieve a project by id and ownerId."""
        return self.db.fetchOne(
            'SELECT * FROM projects WHERE id=%s AND "ownerId"=%s',
            (projectId, ownerId)
        )

    def listProjects(self, ownerId: int) -> List[Dict]:
        """List all projects for a given owner, ordered by createdAt."""
        return self.db.fetchAll(
            'SELECT * FROM projects WHERE "ownerId" = %s ORDER BY "createdAt" DESC',
            (ownerId,)
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

    # -----------------------------
    # Protocol Methods
    # -----------------------------
    def insertProtocol(self, projectId: int, protocolType: str,
                       parameters: Optional[OrderedDict] = None, status: str = 'pending') -> int:
        """Insert a new protocol and return its id."""
        cur = self.db.execute(
            "INSERT INTO protocols (project_id, type, status, parameters) VALUES (%s, %s, %s, %s) RETURNING id",
            (projectId, protocolType, status, parameters)
        )
        return cur.fetchone()['id']

    def getProtocol(self, protocolId: int) -> Optional[Dict]:
        """Retrieve a protocol by id."""
        return self.db.fetchOne("SELECT * FROM protocols WHERE id=%s", (protocolId,))

    def listProtocols(self, projectId: Optional[int] = None) -> List[Dict]:
        """List all protocols, optionally filtered by projectId."""
        if projectId is None:
            return self.db.fetchAll("SELECT * FROM protocols ORDER BY createdAt DESC")
        else:
            return self.db.fetchAll(
                "SELECT * FROM protocols WHERE project_id=%s ORDER BY createdAt DESC",
                (projectId,)
            )

    def updateProtocol(self, protocolId: int, status: Optional[str] = None,
                       parameters: Optional[OrderedDict] = None):
        """Update protocol fields."""
        updates = []
        params = []
        if status is not None:
            updates.append("status=%s")
            params.append(status)
        if parameters is not None:
            updates.append("parameters=%s")
            params.append(parameters)
        if not updates:
            return
        params.append(protocolId)
        self.db.execute(f"UPDATE protocols SET {', '.join(updates)} WHERE id=%s", tuple(params))

    def deleteProtocol(self, protocolId: int):
        """Delete a protocol."""
        self.db.execute("DELETE FROM protocols WHERE id=%s", (protocolId,))
