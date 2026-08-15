# alembic/env.py

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# loadEnvFile
load_dotenv()

config = context.config

# setSqlAlchemyUrlFromEnv
databaseUrl = os.getenv("DATABASE_URL")
if databaseUrl:
    config.set_main_option("sqlalchemy.url", databaseUrl)

# configureLoggingIfAvailable
if config.config_file_name is not None and os.path.exists(config.config_file_name):
    fileConfig(config.config_file_name)

# ensureRepoRootInSysPath
repoRoot = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repoRoot))

# importModelsForMetadata
from app.backend.database import Base  # noqa: E402
from app.backend.models import (  # noqa: F401,E402
    user_model,
    project_model,
    protocol_model,
    tag_model,
    protocol_tag_assignment_model,
    protocol_step_model,
    scipion_object_model,
    system_task_model,
)

target_metadata = Base.metadata


def run_migrations_offline():
    # runMigrationsOffline
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Cannot run Alembic migrations.")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema="public",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # runMigrationsOnline
    section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
