"""Administrative commands.

    uv run proofpay-cli openapi ../frontend/schema/openapi.json

Writes the OpenAPI description to a file. It is the only link to the
frontend: the API client is generated from it, not written by hand. Neither
a database nor a running server is needed - the description is built from
``create_app()``.

    uv run proofpay-cli bootstrap-db

Prepares an empty database: first ``alembic upgrade head`` (application
schemas), then ``procrastinate schema --apply`` (job queue tables; skipped
when they already exist, so the command can be re-run). The order is fixed:
procrastinate creates its own objects in the ``public`` schema, which Alembic
does not manage.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

import psycopg
from alembic import command
from alembic.config import Config

from proofpay.settings import Settings

BACKEND_ROOT: Final = Path(__file__).resolve().parents[1]

COMMAND_OPENAPI: Final = "openapi"
COMMAND_BOOTSTRAP_DB: Final = "bootstrap-db"

_USAGE: Final = (
    "Usage:\n"
    f"  proofpay-cli {COMMAND_OPENAPI} path/to/openapi.json\n"
    f"  proofpay-cli {COMMAND_BOOTSTRAP_DB}"
)


def openapi_document() -> str:
    """OpenAPI description as JSON text.

    Built from the same ``create_app()`` as the real application, without
    touching external services: the description is a property of the code,
    not of the database state. Keys are sorted and the indent is constant -
    the file lives in the frontend repository, and the diff between versions
    must stay readable.
    """
    from proofpay.app import create_app  # noqa: PLC0415 - only needed here

    schema = create_app().openapi_schema.to_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _run_openapi(args: list[str]) -> None:
    """Writes the interface description to a file."""
    if len(args) != 1:
        raise SystemExit(_USAGE)
    target = Path(args[0])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(openapi_document(), encoding="utf-8")
    print(f"OpenAPI description written: {target}")  # noqa: T201 - command output


def _procrastinate_schema_applied() -> bool:
    """Whether the procrastinate tables already exist.

    ``procrastinate schema --apply`` is not idempotent: on a database that
    already has the schema it fails on the first ``CREATE TYPE``.
    """
    dsn = Settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT to_regclass('public.procrastinate_jobs')"
        ).fetchone()
    return row is not None and row[0] is not None


def _run_bootstrap_db(args: list[str]) -> None:
    """Applies Alembic migrations, then the procrastinate schema if missing."""
    if args:
        raise SystemExit(_USAGE)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    if _procrastinate_schema_applied():
        print("procrastinate schema already applied")  # noqa: T201 - command output
        return
    subprocess.run(
        [
            sys.executable,
            "-m",
            "procrastinate",
            "--app=proofpay.worker.app",
            "schema",
            "--apply",
        ],
        check=True,
        cwd=BACKEND_ROOT,
    )


def main() -> None:
    """Parses command-line arguments."""
    args = sys.argv[1:]
    if not args:
        raise SystemExit(_USAGE)
    if args[0] == COMMAND_OPENAPI:
        _run_openapi(args[1:])
        return
    if args[0] == COMMAND_BOOTSTRAP_DB:
        _run_bootstrap_db(args[1:])
        return
    raise SystemExit(_USAGE)
