==========================================================
Scipion Web Backend API
==========================================================

A modular, service-oriented backend exposing a modern REST API around
Scipion. This application provides project management, protocol
execution, plugin inspection, output preview functionalities, user
management, and asynchronous workflow orchestration. It combines 
FastAPI, SQLAlchemy, Alembic, Celery, Redis, and an installed Scipion 
environment to deliver a robust and extensible computation backend.

This repository contains only the backend. It can be used independently
or as part of a larger web-based Scipion interface.

----------------------------------------------------------
1. Key Features
----------------------------------------------------------

* Project creation, renaming, deletion, and metadata access  
* Scipion plugin discovery via plugin_router and plugin_service  
* Protocol execution via Celery workers  
* Structured access to protocol output artifacts  
* Previews for volumes, metadata tables, micrographs, etc.  
* User CRUD + optional authentication layer  
* Fully asynchronous Scipion workflow execution  
* Automated database migrations using Alembic  
* Modular services architecture for future extension  
* Production-friendly logs and worker orchestration  

----------------------------------------------------------
2. Repository Structure (Detailed)
----------------------------------------------------------

The following reflects the actual project layout:

::

    alembic/
        env.py                  # Alembic environment setup
        script.py.mako          # Migration template
        versions/               # Versioned migration scripts

    app/
      backend/
        api/
          dependencies.py       # Shared API dependencies (DB, auth, etc.)
          routers/
            auth_router.py
            plugin_router.py
            project_router.py
            protocol_router.py
            user_router.py
          schemas/
            project_schema.py
            protocols_schema.py
            user_schema.py
          routes.py             # Router registration
          services/
            environment.py
            plugin_service.py
            project_service.py
            protocol_service.py

        database.py             # SQLAlchemy engine/session lifecycle
        main.py                 # FastAPI application entrypoint
        mapper/
          postgresql.py         # Low-level PostgreSQL mapper helpers
        models/
          data_model.py
          plugin_model.py
          project_model.py
          protocol_model.py
          user_model.py
        scripts/
          update_user_email.py  # Example maintenance script
        utils/
          constants.py
          email.py
          error_handlers.py
          file_handlers.py
          jwt.py
          outputs_preview.py
          security.py
          volume_utils.py
        worker.py               # Celery integration (worker entrypoint)

      celeryconfig.py           # Celery configuration (broker, backend)
      celery_worker.py          # Alternative Celery launcher
      services/
        scipion_runner.py       # High-level wrapper for Scipion execution
      utils/
        scipion_helper.py       # Low-level Scipion utility helpers
      workers/
        task_queue.py           # Celery tasks and queue helpers

    projects/                   # Scipion project workspace (runtime)
    logs/                       # app.log, celery.log, celery.pid

    requirements.txt
    setup_api.sh                # Helper script for launching API

This structure formalizes a multi-layered backend divided into:
API → Services → Workers → Scipion Integration → DB + Filesystem.

----------------------------------------------------------
3. Architecture
----------------------------------------------------------

The backend is organized into well-defined layers that separate 
concerns cleanly.

----------------------------------------------------------
3.1 Architecture Diagram
----------------------------------------------------------

::

    +--------------------------------------------------------------+
    |                       Client Applications                    |
    |    Frontend • CLI • Automated Pipelines • Integrators        |
    +-----------------------------+--------------------------------+
                                  |
                                  v
    +--------------------------------------------------------------+
    |                           FastAPI                            |
    |  Routers: auth, user, project, protocol, plugin              |
    |  Pydantic schemas for validation                             |
    |  Dependency injection: DB session, security, environment     |
    +-----------------------------+--------------------------------+
                                  |
                                  v
    +--------------------------------------------------------------+
    |                           Services                           |
    |  project_service.py                                          |
    |  protocol_service.py                                         |
    |  plugin_service.py                                           |
    |  environment.py                                              |
    |  user services (auth_router + user_router)                   |
    +-----------------------------+--------------------------------+
                                  |
                                  v
    +--------------------------------------------------------------+
    |                       Celery Task System                     |
    |       worker.py • celeryconfig.py • workers/task_queue.py    |
    |  Handles long-running jobs (Scipion workflows, previews)     |
    +-----------------------------+--------------------------------+
                                  |
                                  v
    +--------------------------------------------------------------+
    |                      Scipion Integration                     |
    |     scipion_runner.py → orchestrates execution               |
    |     scipion_helper.py → low-level CLI interaction            |
    |     volume_utils.py & outputs_preview.py → visualization     |
    +-----------------------------+--------------------------------+
                                  |
                                  v
    +--------------------------------------------------------------+
    |       PostgreSQL (SQLAlchemy) + Project Filesystem           |
    |   models/*.py • alembic/ • projects/<project_name>/          |
    +--------------------------------------------------------------+

----------------------------------------------------------
4. Installation
----------------------------------------------------------

----------------------------------------------------------
4.1 Requirements
----------------------------------------------------------

* Python 3.8+
* PostgreSQL
* Redis (or RabbitMQ) for Celery broker
* Scipion installed locally
* Linux recommended (due to Scipion runtime)

----------------------------------------------------------
4.2 Environment Setup (Conda)
----------------------------------------------------------

::

    conda create -n scipionapi python=3.8
    conda activate scipionapi
    pip install -r requirements.txt

----------------------------------------------------------
4.3 Configuration (.env)
----------------------------------------------------------

Typical environment configuration:

::

    DATABASE_URL=postgresql://user:pass@localhost:5432/scipion_db
    BROKER_URL=redis://localhost:6379/0
    SECRET_KEY=yourSecretKey
    SCIPION_HOME=/home/user/scipion3
    PROJECTS_PATH=/home/user/scipion_projects
    LOGS_PATH=./logs

----------------------------------------------------------
4.4 Database Initialization
----------------------------------------------------------

::

    alembic upgrade head

This applies migrations found under ``alembic/versions``.

----------------------------------------------------------
4.5 Start API Server
----------------------------------------------------------

::

    uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload

Docs available at:

::

    http://localhost:8000/docs

----------------------------------------------------------
4.6 Start Celery Worker
----------------------------------------------------------

::

    celery -A app.celery_worker.celery worker -l info

Or using ``task_queue.py`` depending on your Celery app configuration:

::

    PYTHONPATH=. celery -A app.workers.task_queue worker --loglevel=info

----------------------------------------------------------
5. Workflow Execution Model
----------------------------------------------------------

The protocol execution process is fully asynchronous:

1. A request is submitted to ``protocol_router.py``.
2. Input is validated using ``protocols_schema.py``.
3. ``protocol_service.py`` constructs execution context.
4. A Celery task is submitted to ``task_queue.py``.
5. ``scipion_runner.py`` invokes Scipion inside the appropriate project.
6. Outputs are stored under ``projects/<project>/``.
7. ``outputs_preview.py`` and ``volume_utils.py`` provide lightweight previews.
8. Status is checked through corresponding protocol endpoints.

This isolates the web server from heavy Scipion workloads.

----------------------------------------------------------
6. Detailed Folder Responsibilities
----------------------------------------------------------

----------------------------------------------------------
6.1 app/backend/api
----------------------------------------------------------

* routers/  
  Contains route definitions, grouped by domain:
  - ``project_router.py``  
  - ``protocol_router.py``  
  - ``plugin_router.py``  
  - ``user_router.py``  
  - ``auth_router.py``  

* schemas/  
  Pydantic models describing request and response formats.

* dependencies.py  
  Provides shared DI objects (e.g., DB session generator).

* routes.py  
  Globally registers all routers into the FastAPI application.

----------------------------------------------------------
6.2 app/backend/services
----------------------------------------------------------

High-level business logic:

* ``project_service.py``:
  project creation, deletion, renaming, metadata retrieval.

* ``protocol_service.py``:
  validates parameters, schedules protocol execution tasks.

* ``plugin_service.py``:
  discovers Scipion plugins, extracts metadata.

* ``environment.py``:
  Scipion/home path checks, environment validation.

----------------------------------------------------------
6.3 app/backend/models
----------------------------------------------------------

Defines SQLAlchemy ORM entities:

* ``project_model.py``
* ``protocol_model.py``
* ``plugin_model.py``
* ``user_model.py``
* ``data_model.py``

----------------------------------------------------------
6.4 Scipion Integration (app/services + app/utils)
----------------------------------------------------------

* ``scipion_runner.py`` — orchestrates Scipion CLI executions.  
* ``scipion_helper.py`` — command-building, path resolution.  
* ``outputs_preview.py`` — previews for STAR, volumes, micrographs.  
* ``volume_utils.py`` — scientific parsing of EM/MRC files.  

----------------------------------------------------------
6.5 Workers (Celery)
----------------------------------------------------------

* ``worker.py`` — defines Celery app and worker entrypoint.  
* ``task_queue.py`` — defines queue tasks (protocol execution, previews).  
* ``celery_worker.py`` — alternative launcher.  
* ``celeryconfig.py`` — broker, backend, concurrency settings.

----------------------------------------------------------
7. Project Filesystem Layout
----------------------------------------------------------

::

    projects/
      MyProject/
        Runs/
        ProtocolOutputs/
        Extra/
        metadata.json

``PROJECTS_PATH`` defines this root directory.  
Each Scipion project is isolated here.

----------------------------------------------------------
8. Logging
----------------------------------------------------------

::

    logs/app.log
    logs/celery.log
    logs/celery.pid

Written using Python’s logging infrastructure.  
Workers log deeply, including protocol execution output.

----------------------------------------------------------
9. Troubleshooting
----------------------------------------------------------

* **Worker not receiving tasks** → Check Redis connection.  
* **Scipion errors** → Verify ``SCIPION_HOME`` and execution permissions.  
* **Preview failures** → Validate MRC/STAR file structure.  
* **Database errors** → Ensure Alembic migrations are up-to-date.

----------------------------------------------------------
10. Extending the Backend
----------------------------------------------------------

To add new functionality:

1. Create new router under ``api/routers``  
2. Create schemas under ``api/schemas``  
3. Implement logic in ``api/services``  
4. Add ORM models under ``models`` if needed  
5. Generate Alembic revisions  
6. Optionally define new Celery tasks  

----------------------------------------------------------
11. License
----------------------------------------------------------

See LICENSE for details.