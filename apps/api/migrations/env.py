import os
from logging.config import fileConfig
from urllib.parse import unquote
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

# Decode %40 -> @ and replace asyncpg driver, then escape % for configparser
db_url = os.environ.get("DATABASE_URL", "")
db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
db_url = unquote(db_url)          # Sentinel%402024 -> Sentinel@2024
db_url = db_url.replace("%", "%%")  # escape remaining % for configparser

config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.db.base import Base
import app.db.models.document
import app.db.models.permission
import app.db.models.budget
import app.db.models.ingestion_job
import app.db.models.role
import app.db.models.collection
import app.db.models.tenant
import app.db.models.prompt
import app.db.models.evaluation
import app.db.models.user

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
