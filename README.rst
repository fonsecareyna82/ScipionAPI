==========================================================
Scipion API (Backend) + Optional Scipion Web Bundle
==========================================================

A FastAPI-based backend that exposes a REST API around Scipion project
management, protocol interaction, output browsing/previews, plugin inspection,
and user authentication.

The backend uses PostgreSQL for persistence, Redis for task brokering, and runs
inside a Scipion-capable Python environment.

This repository is backend-only, but it can optionally serve a precompiled
ScipionWeb (React/Vite) bundle in integrated mode.

----------------------------------------------------------
1. Highlights
----------------------------------------------------------

* FastAPI application with modular routers:
  - Projects + protocol operations + filesystem browsing + output previews
  - Authentication (JWT access/refresh) + email verification flow
  - Users listing (for project sharing)
  - Plugins inspection and install/uninstall endpoints
  - Settings endpoints (if enabled in your current codebase)

* PostgreSQL persistence:
  - SQLAlchemy ORM models (users/projects/protocols)
  - Additional relational features via a flat Postgres mapper (e.g., project_shares)

* Scipion integration:
  - Initializes Scipion variables and sets Pyworkflow domain ("pwem")
  - Runs in the same Python environment where Scipion is importable
  - PostgreSQL is the sole runtime source of truth for protocol Sets/outputs
    (no per-project ``project.sqlite``/``run.db`` for projects created under
    this backend); a temporary SQLite snapshot may appear under ``/tmp`` only
    as a compatibility shim for legacy code paths, never as persistent
    storage. See ``AGENTS.md`` / ``.ai/postgresql-runtime-compatibility.md``
    if you're contributing code that touches runtime Sets.

* Output preview pipeline:
  - Volume slices and downsampled 3D data
  - Text/CSV/STAR/PDF/archive/SQLite previews (where applicable)
  - Preview metadata returned via response headers

* Celery + Redis:
  - Task queue available (plugin install task is implemented)
  - Redis is used as broker and result backend (default configuration)

* Human-friendly provisioning workflow:
  - Conda environment bootstrap
  - Runtime ``SCIPION_HOME/.env`` generation
  - Local PostgreSQL DB/user creation (optional, via sudo)
  - Alembic migrations
  - Admin user bootstrap
  - Detached API + Celery runtime management
  - Optional integrated Web deployment via ``--web-dist``

----------------------------------------------------------
2. Packaging / Distribution Model
----------------------------------------------------------

This project is designed to support a deployment flow similar to tools like
CryoSPARC (download bundles, unpack, run setup/provision commands).

Typical distribution for end users:

* **ScipionAPI bundle (server)**:
  - Contains the backend source, CLI, Alembic migrations, and wrapper scripts.

* **ScipionWeb bundle (compiled UI)**:
  - A prebuilt React/Vite ``dist/`` (or ZIP containing it), downloaded separately.
  - Can be deployed into ``SCIPION_HOME/web/dist`` and served by the API process.

You can install API-only first, and later add the web bundle without reinstalling
everything.

----------------------------------------------------------
3. Download and Unpack (API + Web)
----------------------------------------------------------

Versioned ZIPs are published under:

* ``https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/``

Recommended installation layout (example):

::

    $HOME/scipionweb/
      ScipionAPI-<version>/
      ScipionWeb-<version>-dist.zip   (optional)

Example download + unpack flow (adjust filenames to the published version):

::

    mkdir -p "$HOME/scipionweb"
    cd "$HOME/scipionweb"

    # Download API bundle
    wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/ScipionAPI-<version>.zip

    # Download compiled web bundle (optional but recommended for integrated mode)
    wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/ScipionWeb-<version>-dist.zip

    # Unpack API bundle
    unzip ScipionAPI-<version>.zip
    cd ScipionAPI-<version>

Notes:

* The API bundle is the one that provides ``./scripts/scipionapi``.
* The Web ZIP can remain outside the repo and be passed via ``--web-dist``.
* If your web bundle is already unpacked, you can pass the directory instead of the ZIP.

----------------------------------------------------------
4. Requirements
----------------------------------------------------------

* Linux recommended for Scipion runtime
* Conda (Miniconda/Anaconda) available in PATH (required by the wrapper script)
* Python version managed by conda (default used by wrapper: 3.8)
* PostgreSQL (required)
* Redis (required for Celery broker/backend in default config)
* Sudo privileges for local DB bootstrap (only if using automatic DB/user creation)

----------------------------------------------------------
5. System Prerequisites (Ubuntu example)
----------------------------------------------------------

----------------------------------------------------------
5.1 Base utilities
----------------------------------------------------------

Install common tools (Ubuntu/Debian):

::

    sudo apt update
    sudo apt install -y curl wget unzip bzip2 ca-certificates

----------------------------------------------------------
5.2 Install PostgreSQL (system service)
----------------------------------------------------------

Install PostgreSQL and start the service:

::

    sudo apt update
    sudo apt install -y postgresql postgresql-contrib
    sudo systemctl enable postgresql
    sudo systemctl start postgresql
    sudo systemctl status postgresql

Notes:

* The installer/provisioner can create the database and role automatically
  using local peer auth via:

  ::

      sudo -u postgres psql ...

* This is only supported for local PostgreSQL (``POSTGRES_HOST=localhost``).

----------------------------------------------------------
5.3 Install Redis (system service)
----------------------------------------------------------

Redis is used for Celery broker/result backend (default config):

::

    sudo apt update
    sudo apt install -y redis-server
    sudo systemctl enable redis-server
    sudo systemctl start redis-server
    sudo systemctl status redis-server

Quick check:

::

    redis-cli ping

Expected output:

::

    PONG

----------------------------------------------------------
5.4 Install Conda (Miniconda recommended)
----------------------------------------------------------

Miniconda is recommended (user-local installation, no sudo required).

Example (Linux x86_64):

::

    cd /tmp
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash Miniconda3-latest-Linux-x86_64.sh

After installation, restart your shell (or source your shell rc), then verify:

::

    conda --version

Important:

* ``./scripts/scipionapi`` requires ``conda`` to be available in ``PATH``.
* The installer will auto-detect ``CONDA_EXE`` and persist:
  - ``CONDA_EXE``
  - ``CONDA_ACTIVATION_CMD``
  in ``${SCIPION_HOME}/.env`` when possible.

----------------------------------------------------------
6. Repository Layout
----------------------------------------------------------

::

    alembic/
      env.py
      script.py.mako
      versions/

    app/
      backend/
        main.py
        bootstrap.py                     # loads ${SCIPION_HOME}/.env at runtime
        database.py
        worker.py
        api/
          dependencies.py
          routers/
          schemas/
          services/
        mapper/                          # PostgreSQL runtime mapper, SQLAlchemy models
        models/                          # Pydantic request/response schemas
        project/                         # PostgreSQL-backed Scipion project loading
        runtime/                         # protocol execution engine (PostgreSQL-only)
        viewers/                         # output preview/metadata readers
        utils/
      workers/
        celeryconfig.py
        celery_worker.py
      utils/

    scipionapi_cli/
      cli.py                             # Typer CLI (scipionapi ...)
      bootstrap.py                       # conda env / requirements bootstrap
      install.py                         # creates .env, DB/user, migrations, admin
      provision.py                       # one-shot install + start (optional web deploy)
      update.py                          # update an existing install from release ZIPs
      runtime.py                         # start/stop/status/logs (uvicorn + celery)
      db.py                              # local Postgres bootstrap + alembic upgrade
      doctor.py                          # read-only repo/env/DB/broker diagnostics
      admin.py
      uninstall.py
      version.py
      envfile.py
      shell.py

    scripts/
      scipionapi                         # wrapper: conda bootstrap + runs scipionapi

    .run/                                # runtime PIDs (api.pid, worker.pid) (generated)
    requirements.txt
    pyproject.toml
    alembic.ini
    README.rst

Runtime workspace (generated by install/provision, default):

::

    <repoRoot>/scipion_home/
      .env
      config/
      projects/
      logs/
      web/
        dist/                            # deployed compiled ScipionWeb bundle (optional)

Notes:

* The runtime workspace lives under ``SCIPION_HOME`` (default: ``<repoRoot>/scipion_home``).
* The PID directory ``.run/`` is created under the repo root by the runtime manager.

----------------------------------------------------------
7. Quickstart (Recommended)
----------------------------------------------------------

The wrapper script ``./scripts/scipionapi`` is the main entry point for end users.

It can:

1) Bootstrap a conda env (default name: ``scipion4Web``)
2) Install requirements + editable package
3) Run the CLI commands (install/start/stop/.../provision)

----------------------------------------------------------
7.1 API-only one-shot provisioning
----------------------------------------------------------

From the API repo root:

::

    ./scripts/scipionapi provision --user "admin" --email "admin@local" --pass "changeMe"

What this does (one-shot):

* Bootstraps the conda environment if missing (same effect as ``bootstrap``)
* Creates/updates ``SCIPION_HOME/.env`` and runtime folders
* Creates local PostgreSQL DB/user if missing (via ``sudo -u postgres psql``)
* Runs Alembic migrations
* Ensures an admin user exists (creates or updates)
* Starts FastAPI (uvicorn) and Celery worker (detached), writing logs under ``LOGS_PATH``

----------------------------------------------------------
7.2 Integrated mode (API + compiled Web at /)
----------------------------------------------------------

If you downloaded the compiled ScipionWeb ZIP, pass it to ``--web-dist``:

::

    ./scripts/scipionapi provision \
      --user "admin" \
      --email "admin@local" \
      --pass "changeMe" \
      --web-dist "$HOME/scipionweb/ScipionWeb-<version>-dist.zip"

This enables integrated mode:

* Web served at ``/``
* API mounted under ``/api`` (default)
* API docs available at ``/api/docs``

The provisioning step will:

* Deploy the web build into ``${SCIPION_HOME}/web/dist``
* Write ``config.js`` into the deployed dist with runtime API base URL
* Set integrated-mode env vars (e.g., ``SERVE_WEB=1``)

If the web bundle is already unpacked:

::

    ./scripts/scipionapi provision ... --web-dist /path/to/dist

----------------------------------------------------------
8. CLI Commands
----------------------------------------------------------

The Typer CLI lives in ``scipionapi_cli/cli.py`` and is executed via the wrapper
script (conda-managed).

Bootstrap only (create/update conda env + install requirements + editable install):

::

    ./scripts/scipionapi bootstrap

Install only (create/update .env + folders + DB/user + migrations + admin):

::

    ./scripts/scipionapi install --user "admin" --email "admin@local" --pass "changeMe"

Start/stop/restart/status/logs (detached uvicorn + celery):

::

    ./scripts/scipionapi start
    ./scripts/scipionapi stop
    ./scripts/scipionapi restart
    ./scripts/scipionapi status
    ./scripts/scipionapi logs

Provision (recommended “do everything”):

::

    ./scripts/scipionapi provision --user "admin" --email "admin@local" --pass "changeMe"

Provision with integrated web:

::

    ./scripts/scipionapi provision \
      --user "admin" \
      --email "admin@local" \
      --pass "changeMe" \
      --web-dist /path/to/ScipionWeb-dist.zip \
      --api-mount-path /api

Update an existing installation from published release ZIPs (preserves
``SCIPION_HOME``, ``.env``, projects, logs, and database data):

::

    ./scripts/scipionapi update --version latest

Options include ``--api-only``/``--web-only`` to update a single side,
``--dry-run`` to print the resolved plan without changing files, and
``--no-restart``/``--force`` for finer control. See ``update --help`` for
the full list (including ``--base-url``/``--api-zip-url``/``--web-zip-url``
for custom release sources).

Read-only diagnostics (repository, environment, database, broker, imports,
runtime services):

::

    ./scripts/scipionapi doctor

Use ``--strict`` to exit with code 1 when failures are detected, or
``--quick`` to skip heavier checks (importing the FastAPI app, Alembic).

Show the installed CLI version:

::

    ./scripts/scipionapi version

----------------------------------------------------------
9. Configuration and Runtime Workspace (SCIPION_HOME)
----------------------------------------------------------

Runtime workspace is controlled by ``SCIPION_HOME``.

Default:
* ``SCIPION_HOME=<repoRoot>/scipion_home``

This directory is expected to contain:
* ``config/`` (Scipion-related configuration)
* ``projects/`` (runtime projects workspace)
* ``logs/`` (runtime logs)
* ``web/dist`` (optional compiled web bundle)
* ``.env`` (generated by install/provision; DO NOT commit secrets)

Override the location before running install/provision:

::

    export SCIPION_HOME=/path/to/scipion_home
    ./scripts/scipionapi provision --user ... --email ... --pass ...

To force a specific API/Web port:

::

    ./scripts/scipionapi provision \
      --user "admin" \
      --email "admin@local" \
      --pass "changeMe" \
      --api-port 39080

If ``--api-port`` is omitted, the first installation selects a free port
automatically and persists it in ``${SCIPION_HOME}/.env``.

----------------------------------------------------------
10. .env Variables (generated under SCIPION_HOME)
----------------------------------------------------------

The installer writes/maintains:

* ``${SCIPION_HOME}/.env``

Core variables:

* ``DATABASE_URL`` (SQLAlchemy engine URL)
* ``DATABASE_NAME`` (used by PostgresqlDb)
* ``DATABASE_USER`` (used by PostgresqlDb)
* ``DATABASE_PASS`` (used by PostgresqlDb)
* ``POSTGRES_HOST`` (default: ``localhost``)
* ``POSTGRES_PORT`` (default: ``5432``)
* ``SECRET_KEY`` (JWT signing secret; auto-generated if missing)

Runtime paths:

* ``LOGS_PATH`` (default: ``${SCIPION_HOME}/logs``)
* ``PROJECTS_PATH`` (default: ``${SCIPION_HOME}/projects``)

Services:

* ``BROKER_URL`` (default: ``redis://localhost:6379/0``)
* ``API_HOST`` (default: ``0.0.0.0``)
* ``API_PORT`` (a free port is selected automatically on first install; the persisted value is reused afterwards; override with ``--api-port``)
* ``CELERY_APP`` (default: ``app.workers.task_queue``)
* ``CELERY_LOGLEVEL`` (default: ``info``)

Conda integration (auto-detected when possible):

* ``CONDA_EXE`` (absolute path to ``conda``)
* ``CONDA_ACTIVATION_CMD`` (bash hook command used by some plugins)

Integrated web mode (set by ``provision --web-dist``):

* ``SERVE_WEB`` (``1`` or ``0``)
* ``API_MOUNT_PATH`` (default: ``/api``)
* ``WEB_DIST_PATH`` (default: ``${SCIPION_HOME}/web/dist``)
* ``WEB_API_BASE_URL`` (default: ``/api``)

Admin bootstrap inputs (written by install/provision):

* ``ADMIN_USERNAME``
* ``ADMIN_EMAIL``
* ``ADMIN_PASSWORD``

Security note:
Never commit real credentials. Use placeholders in documentation and examples.

----------------------------------------------------------
11. Database Setup and Migrations
----------------------------------------------------------

Automatic local DB bootstrap (recommended):

* ``install`` / ``provision`` attempts to create the PostgreSQL role and database
  locally using peer auth:

::

    sudo -u postgres psql ...

This requires:

* Local PostgreSQL (``POSTGRES_HOST`` must be ``localhost`` / loopback)
* Sudo permissions to run ``psql`` as ``postgres``

Then the installer runs:

::

    alembic upgrade head

Remote PostgreSQL:

* If PostgreSQL is remote, create the database and user manually first.
* Set ``DATABASE_URL``, ``DATABASE_NAME``, ``DATABASE_USER``, ``DATABASE_PASS``
  accordingly in ``${SCIPION_HOME}/.env``.
* The current installer intentionally refuses automatic DB/user creation for
  non-local hosts.

Migration caveat:

* If your migration history has been heavily edited (deleted/reordered revisions),
  provisioning may fail. In that case, rebuild a clean migration baseline first,
  then retry provisioning on a fresh database.

----------------------------------------------------------
12. Running the API (manual / dev)
----------------------------------------------------------

In normal operation, prefer:

::

    ./scripts/scipionapi start

For local debugging (PyCharm / VSCode / manual uvicorn), ensure the process
receives the same environment variables that ``install`` writes into
``${SCIPION_HOME}/.env`` (at minimum: ``DATABASE_URL`` and ``SECRET_KEY``).

The backend also loads ``${SCIPION_HOME}/.env`` at startup via
``app.backend.bootstrap.bootstrapEnv()`` when ``SCIPION_HOME`` is defined.

Manual uvicorn example:

::

    uvicorn app.backend.main:app --host 0.0.0.0 --port 8080 --reload

Health endpoint:

::

    GET /health  ->  {"status": "ok"}

Docs (API-only mode):
* ``http://localhost:8080/docs``

Docs (integrated mode with API mounted at ``/api``):
* ``http://localhost:8080/api/docs``

----------------------------------------------------------
13. Running Celery (Redis Broker)
----------------------------------------------------------

Redis (local):

::

    redis-server

Celery is started automatically by:

::

    ./scripts/scipionapi start

Manual worker command (if needed):

::

    PYTHONPATH=. celery -A app.workers.task_queue worker --loglevel=info

----------------------------------------------------------
14. Separate Deployment vs Integrated Deployment
----------------------------------------------------------

----------------------------------------------------------
14.1 Integrated deployment (single host/process entrypoint)
----------------------------------------------------------

Use ``provision --web-dist``.

Benefits:
* One URL to open in the browser
* API and web version can be provisioned together
* Simple user experience

Default routing:
* Web: ``/``
* API: ``/api``

----------------------------------------------------------
14.2 Separate deployment (API on one host, Web on another)
----------------------------------------------------------

This remains fully supported.

In that case:

* Run API normally on the server (e.g., ``http://api-host:8080``)
* Build ScipionWeb separately with the appropriate API URL (e.g., ``VITE_API_URL``)
* Serve the compiled Web using nginx / Apache / static hosting / CDN

This is useful for:
* reverse-proxy setups
* isolated frontend hosting
* scaling API and UI independently

----------------------------------------------------------
15. CORS / Preview Headers
----------------------------------------------------------

CORS origins in ``app/backend/main.py`` typically include local dev URLs such as:

* ``http://localhost:5173``
* ``http://localhost:5174``

The API exposes preview-related headers (examples):

* ``X-Preview-Mime``
* ``X-Preview-Width``, ``X-Preview-Height``, ``X-Preview-Depth``
* ``X-Preview-Colormap``, ``X-Preview-Colormap-Note``
* ``X-Preview-Tiles``, ``X-Preview-SizeBytes``
* ``X-Preview-Columns``, ``X-Preview-RowCount``
* ``X-Archive-Kind``
* ``X-Preview-VoxelSize``
* (optionally) ``X-Preview-Schema``, ``X-Preview-Name`` if present in your current code

----------------------------------------------------------
16. Troubleshooting
----------------------------------------------------------

* ``conda: command not found``
  - Install Miniconda/Anaconda and ensure ``conda`` is in PATH.
  - Restart the shell and verify with ``conda --version``.

* ``password authentication failed for user ...`` (PostgreSQL)
  - Verify ``DATABASE_URL`` and ``DATABASE_PASS`` in ``${SCIPION_HOME}/.env``.
  - Confirm the actual DB role password in PostgreSQL (pgAdmin/psql).

* JWT error ``Expecting a string- or bytes-formatted key``
  - ``SECRET_KEY`` is missing/empty in the environment.
  - Ensure ``${SCIPION_HOME}/.env`` exists and is being loaded, and that
    ``SECRET_KEY`` is non-empty.

* Alembic error ``relation "projects" does not exist``
  - Your migration chain likely assumes earlier tables that are missing.
  - Rebuild a clean initial migration baseline or restore the missing revisions.

* Alembic error ``relation "alembic_version" does not exist``
  - Usually caused by a broken initial migration script or a failed migration that
    interfered with Alembic metadata initialization.
  - Recreate a clean initial migration and retry on a fresh empty DB.

* API starts but web is not served
  - Verify ``SERVE_WEB=1`` and ``WEB_DIST_PATH`` points to a valid folder with
    ``index.html``.
  - Re-run ``provision --web-dist ...``.

* Celery task not executing
  - Ensure Redis is running and reachable at ``BROKER_URL``.
  - Check ``${LOGS_PATH}/celery.log`` and run ``./scripts/scipionapi logs``.

----------------------------------------------------------
17. Runtime Artifacts and Git Hygiene
----------------------------------------------------------

Do not commit generated runtime files, for example:

* ``scipion_home/.env``
* ``scipion_home/projects/``
* ``scipion_home/logs/``
* ``scipion_home/web/dist/`` (if deployed locally from a downloaded bundle)
* ``.run/``

Keep these ignored in ``.gitignore`` (repo-level) and/or globally as needed.

----------------------------------------------------------
18. Security Notes
----------------------------------------------------------

* JWT uses ``HS256`` and ``SECRET_KEY``.
* Access tokens rely on the ``sub`` claim (email) and DB lookup.
* Keep ``SECRET_KEY`` private and rotate in production.
* Use HTTPS behind a reverse proxy for real deployments.
* Avoid storing real admin passwords in shell history on shared machines.

----------------------------------------------------------
19. License
----------------------------------------------------------

See LICENSE in the repository root.