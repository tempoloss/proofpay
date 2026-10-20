"""Alembic env.py - a single MetaData, models of all modules imported."""

from collections.abc import MutableMapping
from importlib import import_module
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import create_engine, pool

from proofpay.modules.registry import MODULES, all_model_modules
from proofpay.settings import Settings
from proofpay.shared.db.base import metadata

# Import the models of all modules - without it autogenerate cannot see them.
# There is one list of modules, in proofpay/modules/registry.py.
for _model_module in all_model_modules():
    import_module(_model_module)

target_metadata = metadata

# Schemas owned by the application. Everything else (public, pg_catalog,
# information_schema, procrastinate) is foreign: autogenerate leaves it alone.
MANAGED_SCHEMAS: set[str] = set(MODULES.values())

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL from Settings (env PROOFPAY_DATABASE_URL) overrides alembic.ini.
# In CI the database is reached by a service alias, not localhost.
config.set_main_option("sqlalchemy.url", Settings().database_url)


def include_name(
    name: str | None,
    type_: Literal[
        "schema",
        "table",
        "column",
        "index",
        "unique_constraint",
        "foreign_key_constraint",
        "check_constraint",
    ],
    parent_names: MutableMapping[
        Literal["schema_name", "table_name", "schema_qualified_table_name"], str | None
    ],
) -> bool:
    """Autogenerate filter: only manage our own schemas."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    # Tables, indexes and so on inside managed schemas are accepted.
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url", ""),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
