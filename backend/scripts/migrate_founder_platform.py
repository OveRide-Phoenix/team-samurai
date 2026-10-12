"""Apply the founder-platform migration to a disposable PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

if not __package__:
    sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from samurai.schema import FounderPlatformMigrator
from samurai.schema_contracts import LegacyMigrationError


class _Arguments(argparse.Namespace):
    database_url_env: str = ""
    schema: str = "ai"
    receipt: Path = Path()
    dry_run: bool = False


def _arguments() -> _Arguments:
    parser = argparse.ArgumentParser(
        description="Backfill the additive founder-platform schema from legacy Agno sessions."
    )
    _ = parser.add_argument(
        "--database-url-env",
        required=True,
        help="Environment variable containing the disposable PostgreSQL URL",
    )
    _ = parser.add_argument("--schema", default="ai", help="Existing Agno database schema")
    _ = parser.add_argument("--receipt", required=True, type=Path)
    _ = parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory only in a read-only transaction",
    )
    return parser.parse_args(namespace=_Arguments())


def main() -> int:
    """Run the guarded migration and write a sanitized reconciliation receipt."""
    arguments = _arguments()
    database_url = os.environ.get(arguments.database_url_env)
    if not database_url:
        _ = sys.stderr.write("migration refused: database URL environment variable is unset\n")
        return 2
    engine: Engine | None = None
    try:
        engine = create_engine(database_url)
        migrator = FounderPlatformMigrator(engine, schema=arguments.schema)
        receipt = migrator.inventory() if arguments.dry_run else migrator.apply()
        arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
        _ = arguments.receipt.write_text(
            json.dumps(receipt.as_json(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except LegacyMigrationError as error:
        _ = sys.stderr.write(f"migration refused: {error}\n")
        return 2
    except SQLAlchemyError:
        _ = sys.stderr.write("migration refused: database operation failed\n")
        return 2
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
