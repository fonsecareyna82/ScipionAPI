==========================================================
Scipion API (Backend)
==========================================================

A FastAPI-based backend that exposes a REST API around Scipion project
management, protocol interaction, output browsing/previews, plugin inspection,
and user authentication. The backend uses PostgreSQL for persistence, Redis for
task brokering, and requires a working Scipion Python environment.

This repository is backend-only.

----------------------------------------------------------
1. Highlights
----------------------------------------------------------

* FastAPI application with modular routers:
  - Projects + protocol operations + filesystem browsing + output previews
  - Authentication (JWT access/refresh) + email verification flow
  - Users listing (for project sharing)
  - Plugins inspection and install/uninstall endpoints

* PostgreSQL persistence:
  - SQLAlchemy ORM models (users/projects/protocols)
  - Additional relational features via a flat Postgres mapper (e.g., project_shares)

* Scipion integration:
  - Initializes Scipion variables and sets Pyworkflow domain ("pwem")
  - Runs in the same Python environment where Scipion is installed

* Output preview pipeline:
  - Volume slices and downsampled 3D data
  - Text/CSV/STAR/PDF/archive/SQLite previews (where applicable)
  - Preview metadata returned via response headers (see section 8)

* Celery + Redis:
  - Task queue available (plugin install task is implemented)
  - Redis is used both as broker and result backend (default configuration)

----------------------------------------------------------
2. Repository Layout (as implemented)
----------------------------------------------------------

::

    alembic/
      env.py
      script.py.mako
      versions/
        3f055107e978_create_protocols_table.py

    app/
      backend/
        main.py                          # FastAPI app + CORS + router include
        database.py                      # env loading + mapper factory
        worker.py                        # sample Celery app (utility)
        api/
          dependencies.py                # JWT auth dependency (getCurrentUser)
          routers/
            auth_router.py
            user_router.py
            project_router.py
            protocol_router.py
            plugin_router.py
          schemas/
            project_schema.py
            protocols_schema.py
            user_schema.py
          services/
            environment.py               # prepareEnvironment() (Scipion init)
            project_service.py
            protocol_service.py
            plugin_service.py
        mapper/
          postgresql.py                  # PostgresqlFlatMapper + project_shares
        models/
          user_model.py                  # SQLAlchemy User
          project_model.py               # SQLAlchemy Project
          protocol_model.py              # SQLAlchemy Protocol + Pydantic payloads
          data_model.py                  # Pydantic response model(s)
          plugin_model.py                # Pydantic request model(s)
        utils/
          jwt.py
          security.py
          email.py
          error_handlers.py              # custom FastAPI error handlers
          file_handlers.py
          outputs_preview.py             # previews (tables/pdf/archives/sqlite/etc.)
          volume_utils.py                # volume parsing + slice helpers
          constants.py

      celeryconfig.py                    # Redis broker/backend defaults
      celery_worker.py                   # starts Celery worker main()
      workers/
        task_queue.py                    # Celery app + installPluginTask
      services/
        scipion_runner.py
      utils/
        scipion_helper.py
      run_all.py                         # optional runner (API + UI hook)

    projects/                            # runtime workspace (if used)
    logs/                                # app.log, celery.log, celery.pid
    requirements.txt
    setup_api.sh                         # bootstrap script (may be outdated)
    README.rst


----------------------------------------------------------
3. Runtime Architecture
----------------------------------------------------------

::

    +----------------------------+
    |          Clients           |
    |  (Frontend / REST callers) |
    +-------------+--------------+
                  |
                  v
    +----------------------------+
    |          FastAPI           |
    | app/backend/main.py        |
    | Routers + schemas + DI     |
    +-------------+--------------+
                  |
                  v
    +----------------------------+
    |  Services + Mapper/ORM     |
    | project_service.py         |
    | protocol_service.py        |
    | plugin_service.py          |
    | PostgresqlFlatMapper       |
    +-------------+--------------+
                  |
                  +--------------------+
                  |                    |
                  v                    v
    +--------------------+    +---------------------------+
    |   PostgreSQL DB     |    |  Scipion / Pyworkflow     |
    | users/projects/...  |    | prepareEnvironment()      |
    +--------------------+    +---------------------------+
                  |
                  v
    +----------------------------+
    |  Filesystem (project tree) |
    | previews, outputs, logs    |
    +----------------------------+

Celery/Redis is used for async tasks (plugin install task is implemented).
Other long-running operations may run synchronously depending on service logic.

----------------------------------------------------------
4. Requirements
----------------------------------------------------------

* Python 3.8+ (your repo includes compiled artifacts for 3.8/3.12, but runtime is Python)
* A Scipion-capable environment (Scipion import must work in Python)
* PostgreSQL (required)
* Redis (required for Celery broker/backend in default config)
* Linux recommended for Scipion runtime

----------------------------------------------------------
5. Installation (Local)
----------------------------------------------------------

1) Create and activate an environment (Conda example):

::

    conda create -n scipionapi python=3.8
    conda activate scipionapi

2) Install dependencies:

::

    pip install -r requirements.txt

3) Ensure Scipion is installed and importable in this environment.
   The backend calls ``from scipion.__main__ import Vars`` during startup.

----------------------------------------------------------
6. Configuration (.env)
----------------------------------------------------------

Your repository contains a .env, but do NOT commit real credentials to public repos.
Use placeholders in documentation.

Required variables used by the backend:

* ``DATABASE_URL`` (SQLAlchemy engine URL)
* ``DATABASE_NAME`` (used by PostgresqlDb)
* ``DATABASE_USER`` (used by PostgresqlDb)
* ``DATABASE_PASS`` (used by PostgresqlDb)
* ``SECRET_KEY`` (JWT signing secret for auth)

Example:

::

    DATABASE_URL=postgresql://scipion_user:yourPassword@localhost:5432/scipion_db
    DATABASE_NAME=scipion_db
    DATABASE_USER=scipion_user
    DATABASE_PASS=yourPassword
    SECRET_KEY=changeMeInProduction

Notes:

* ``DATABASE_URL`` is used by SQLAlchemy engine in ``app/backend/database.py``.
* ``DATABASE_NAME/USER/PASS`` are used by the flat mapper (psycopg2 connection).
* JWT decoding in ``api/dependencies.py`` uses ``HS256`` with ``SECRET_KEY``.

----------------------------------------------------------
7. Database Setup and Migrations
----------------------------------------------------------

Create database/user (example):

::

    sudo -u postgres psql
    CREATE USER scipion_user WITH PASSWORD 'yourPassword';
    CREATE DATABASE scipion_db OWNER scipion_user;
    GRANT ALL PRIVILEGES ON DATABASE scipion_db TO scipion_user;
    \q

Run Alembic migrations:

::

    alembic upgrade head

Current migration present in this repo:

* ``3f055107e978_create_protocols_table.py`` (creates the ``protocols`` table)

Important:
Other tables (e.g., ``users``, ``projects``, ``project_shares``) may exist from
prior migrations or manual provisioning. The mapper contains SQL for creating
``project_shares`` (see ``app/backend/mapper/postgresql.py``).

----------------------------------------------------------
8. Running the API
----------------------------------------------------------

Start the backend:

::

    uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload

Health endpoint:

::

    GET /health  ->  {"status": "ok"}

Interactive docs:

::

    http://localhost:8000/docs

----------------------------------------------------------
8.1 CORS / Preview Headers
----------------------------------------------------------

CORS origins configured in ``app/backend/main.py`` include:

* ``http://localhost:5173``
* ``http://localhost:5174``

The API also exposes preview-related headers (examples):

* ``X-Preview-Mime``
* ``X-Preview-Width``, ``X-Preview-Height``, ``X-Preview-Depth``
* ``X-Preview-Colormap``, ``X-Preview-Colormap-Note``
* ``X-Preview-Tiles``, ``X-Preview-SizeBytes``
* ``X-Preview-Columns``, ``X-Preview-RowCount``
* ``X-Archive-Kind``
* ``X-Preview-VoxelSize``

Colormap can be passed via request headers such as:

* ``X-Scipion-Colormap``
* ``X-Preview-Colormap``
* ``X-Colormap``
* ``Colormap``

See ``project_router.py`` (output preview endpoint) and
``utils/outputs_preview.py``.

----------------------------------------------------------
9. Running Celery (Redis Broker)
----------------------------------------------------------

Redis (local):

::

    redis-server

Celery worker (project task queue app):

::

    PYTHONPATH=. celery -A app.workers.task_queue worker --loglevel=info

Celery configuration is loaded from:

* ``app/celeryconfig.py`` (broker_url/result_backend default to Redis db 0)

Implemented async task(s):

* ``installPluginTask`` (see ``app/workers/task_queue.py``)

----------------------------------------------------------
10. Docker Compose (API + Postgres + Redis)
----------------------------------------------------------

A reference docker-compose (no Dockerfile included here; you can adapt to your setup):

::

    version: "3.8"

    services:
      postgres:
        image: postgres:15
        environment:
          POSTGRES_DB: scipion_db
          POSTGRES_USER: scipion_user
          POSTGRES_PASSWORD: yourPassword
        ports:
          - "5432:5432"
        volumes:
          - pgdata:/var/lib/postgresql/data

      redis:
        image: redis:7
        ports:
          - "6379:6379"

      api:
        image: python:3.8-slim
        working_dir: /app
        volumes:
          - ./:/app
        environment:
          DATABASE_URL: postgresql://scipion_user:yourPassword@postgres:5432/scipion_db
          DATABASE_NAME: scipion_db
          DATABASE_USER: scipion_user
          DATABASE_PASS: yourPassword
          SECRET_KEY: changeMeInProduction
        depends_on:
          - postgres
          - redis
        command: >
          bash -lc "pip install -r requirements.txt &&
                   uvicorn app.backend.main:app --host 0.0.0.0 --port 8000"
        ports:
          - "8000:8000"

    volumes:
      pgdata:

Important:
Scipion execution typically requires a specialized environment and system-level
dependencies. For real Scipion execution inside Docker, you will likely need a
custom image that includes Scipion and its runtime stack.

----------------------------------------------------------
11. API Endpoints Summary
----------------------------------------------------------

Below is a summary derived from the actual router decorators in this repo.
Paths include router prefixes.

----------------------------------------------------------
11.1 Authentication Router (prefix: /auth)
----------------------------------------------------------

+--------+-------------------+--------------------------------------------+
| Method | Path              | Notes                                      |
+========+===================+============================================+
| POST   | /auth/signup      | Create user + send verification email      |
+--------+-------------------+--------------------------------------------+
| POST   | /auth/verify      | Verify email with verificationCode         |
+--------+-------------------+--------------------------------------------+
| POST   | /auth/resend-code | Resend email verification code             |
+--------+-------------------+--------------------------------------------+
| POST   | /auth/login       | Login (requires verified email)            |
+--------+-------------------+--------------------------------------------+
| GET    | /auth/me          | Current user profile (JWT required)        |
+--------+-------------------+--------------------------------------------+
| PUT    | /auth/me          | Update current user profile fields         |
+--------+-------------------+--------------------------------------------+
| POST   | /auth/refresh     | Exchange refresh token for access token    |
+--------+-------------------+--------------------------------------------+

----------------------------------------------------------
11.2 Users Router (prefix: /users)
----------------------------------------------------------

+--------+----------+--------------------------------------------+
| Method | Path     | Notes                                      |
+========+==========+============================================+
| GET    | /users/  | List users (excludes current user)         |
+--------+----------+--------------------------------------------+

----------------------------------------------------------
11.3 Plugins Router (prefix: /plugins)
----------------------------------------------------------

+--------+----------------------------+----------------------------------------+
| Method | Path                       | Notes                                  |
+========+============================+========================================+
| GET    | /plugins/                  | List plugins                            |
+--------+----------------------------+----------------------------------------+
| GET    | /plugins/{pluginName}      | Plugin details                          |
+--------+----------------------------+----------------------------------------+
| POST   | /plugins/install/{pluginName}   | Triggers install in executor thread |
+--------+----------------------------+----------------------------------------+
| POST   | /plugins/uninstall/{pluginName} | Triggers uninstall in executor thread|
+--------+----------------------------+----------------------------------------+
| GET    | /plugins/tasks/{task_id}   | Celery status (installPluginTask)       |
+--------+----------------------------+----------------------------------------+

----------------------------------------------------------
11.4 Protocols Router (prefix: /protocols)
----------------------------------------------------------

Note:
This router overlaps conceptually with endpoints under ``/projects/{projectId}/...``.
In many deployments, the project-scoped endpoints are preferred.

+--------+--------------------------------------------------------------+---------------------------+
| Method | Path                                                         | Notes                     |
+========+==============================================================+===========================+
| GET    | /protocols/{projectId}/{protocolId}                           | Protocol parameters       |
+--------+--------------------------------------------------------------+---------------------------+
| GET    | /protocols/{projectId}/protclass/{protClassName}              | New protocol params       |
+--------+--------------------------------------------------------------+---------------------------+
| POST   | /protocols/launch                                             | Launch protocol           |
+--------+--------------------------------------------------------------+---------------------------+
| POST   | /protocols/save                                               | Save protocol parameters  |
+--------+--------------------------------------------------------------+---------------------------+
| GET    | /protocols/logs/{projectId}/{protocolId}/{offset}/{errOffset}/{scheduleOffset} | Logs |
+--------+--------------------------------------------------------------+---------------------------+

----------------------------------------------------------
11.5 Projects Router (prefix: /projects)
----------------------------------------------------------

This is the main router and includes:
* project CRUD
* project sharing
* workflow templates
* protocol lifecycle operations
* protocol filesystem browsing + preview + download
* output previews + volume/tilt-series analysis endpoints

A non-exhaustive grouping (all paths are real and present in this repo):

Project workflows:
* GET    /projects/workflows
* POST   /projects/{projectId}/workflows/apply

Projects CRUD:
* GET    /projects/
* POST   /projects/
* GET    /projects/{projectId}
* PUT    /projects/{projectId}
* DELETE /projects/{projectId}

Project sharing:
* POST   /projects/{projectId}/share
* DELETE /projects/{projectId}/share/{targetUserId}
* GET    /projects/{projectId}/shares

Protocol list/params:
* GET    /projects/{projectId}/protocols
* GET    /projects/{projectId}/protocols/{protocolId}
* GET    /projects/{projectId}/protclass/{protClassName}

Protocol save/launch:
* POST   /projects/{projectId}/save
* POST   /projects/{projectId}/launch

Protocol operations:
* PUT    /projects/{projectId}/protocols/{protocolId}/rename
* POST   /projects/{projectId}/protocols/duplicate
* POST   /projects/{projectId}/protocols/delete
* POST   /projects/{projectId}/protocols/{protocolId}/restart-all
* POST   /projects/{projectId}/protocols/{protocolId}/continue-all
* POST   /projects/{projectId}/protocols/{protocolId}/reset-from
* POST   /projects/{projectId}/protocols/stop

Protocol filesystem browsing:
* GET    /projects/{projectId}/protocols/{protocolId}/fs/start-path
* GET    /projects/{projectId}/protocols/{protocolId}/fs/list
* GET    /projects/{projectId}/protocols/{protocolId}/fs/preview
* GET    /projects/{projectId}/protocols/{protocolId}/fs/download

Output preview:
* GET    /projects/{projectId}/protocols/{protocolId}/outputpreview/{outputName}

Volume analysis endpoints:
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/info
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/histogram
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/slice
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/data3d

Tilt-series analysis endpoints (SetOfTiltSeries):
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries
* GET    /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries/{tiltSeriesId}/frames
* (additional endpoints exist in project_router.py)

For the complete set, refer to:
``app/backend/api/routers/project_router.py``


----------------------------------------------------------
12. Entity Diagram (ORM + Mapper Tables)
----------------------------------------------------------

SQLAlchemy ORM tables (as defined in app/backend/models):

* users
* projects
* protocols

Additional relational table created/used by the flat mapper:

* project_shares (projectId, userId, permission, timestamps)

Diagram:

::

    +------------------+        +-------------------+
    |      users       |        |     projects       |
    |------------------|        |-------------------|
    | id (PK)          | 1   N  | id (PK)           |
    | email (unique)   |------->| ownerId (FK users)|
    | hashedPassword   |        | name, status,...  |
    | isVerified,...   |        +---------+---------+
    +--------+---------+                  |
             |                            | 1
             |                            | N
             |                    +-------v--------+
             |                    |    protocols    |
             |                    |----------------|
             |                    | id (PK)        |
             |                    | projectId (FK) |
             |                    | protocolId     |
             |                    | params (JSON)  |
             |                    | parentIds[]    |
             |                    | childIds[]     |
             |                    +----------------+
             |
             |      +------------------------------------------+
             +----->|              project_shares               |
                    |------------------------------------------|
                    | projectId (FK projects)                  |
                    | userId (FK users)                        |
                    | permission (default 'full')              |
                    | UNIQUE(projectId, userId)                |
                    +------------------------------------------+

----------------------------------------------------------
13. Security Notes
----------------------------------------------------------

* JWT is decoded in ``api/dependencies.py`` using HS256 and SECRET_KEY.
* Access tokens rely on the ``sub`` claim (email) and fetch user from DB.
* Keep SECRET_KEY private and rotate in production.
* Use HTTPS behind a reverse proxy for real deployments.

----------------------------------------------------------
14. Troubleshooting
----------------------------------------------------------

* ImportError: scipion / pyworkflow not found
  - Ensure you run the API inside the Scipion-capable environment.
  - Startup calls ``prepareEnvironment()`` from ``environment.py``.

* 401 / "Invalid authentication credentials"
  - Ensure Authorization header includes a Bearer token.
  - Verify SECRET_KEY matches the one used to sign tokens.

* Email verification issues
  - Check ``utils/email.py`` configuration and SMTP credentials (if used).

* Postgres connection errors
  - Validate DATABASE_URL, DATABASE_NAME, DATABASE_USER, DATABASE_PASS.

* Celery task not executing
  - Ensure Redis is running and broker_url/result_backend are reachable.
  - Start worker with PYTHONPATH=. so it can import app.* modules.

----------------------------------------------------------
15. License
----------------------------------------------------------

See LICENSE in the repository root.
