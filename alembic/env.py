# alembic/env.py

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Load environment variables from .env file
import os
from dotenv import load_dotenv
load_dotenv()

# Alembic Config object
config = context.config

# Override the database URL from .env
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))

# Setup logging
fileConfig(config.config_file_name)

# Import Base and models from app.backend
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))  # Add project root to path

from app.backend.database import Base
from app.backend.models.user import User  # Import at least one model

# Provide metadata for Alembic's autogenerate
target_metadata = Base.metadata

# Offline migration
def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

# Online migration
def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
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

# Entry point
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
