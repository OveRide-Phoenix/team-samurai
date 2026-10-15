"""Execute one bounded pass over due local schedules."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import TypeAdapter
from sqlalchemy import create_engine

from samurai.schedules import ScheduleStore


class _Arguments(argparse.Namespace):
    once: bool = False
    now: str = ""
    database_url_env: str = ""
    schema_env: str = "SAMURAI_DB_SCHEMA"


def _arguments() -> _Arguments:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--once", action="store_true", required=True)
    _ = parser.add_argument("--now", required=True)
    _ = parser.add_argument("--database-url-env", required=True)
    _ = parser.add_argument("--schema-env", default="SAMURAI_DB_SCHEMA")
    return parser.parse_args(namespace=_Arguments())


def main() -> int:
    """Run one provider-free dispatch pass and print terminal JSON receipts."""
    arguments = _arguments()
    database_url = os.environ.get(arguments.database_url_env)
    if database_url is None:
        message = f"missing database URL environment variable: {arguments.database_url_env}"
        raise SystemExit(message)
    now = TypeAdapter(datetime).validate_python(arguments.now)
    if now.utcoffset() is None:
        message = "--now must include a UTC offset"
        raise SystemExit(message)
    schema = os.environ.get(arguments.schema_env, "samurai")
    engine = create_engine(database_url)
    try:
        receipts = ScheduleStore(engine, schema).run_due(now, f"once-{uuid4()}")
        output = json.dumps([item.model_dump(mode="json") for item in receipts], sort_keys=True)
        _ = sys.stdout.write(f"{output}\n")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
