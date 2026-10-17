"""Admit verified guests against durable, service-wide daily request limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from samurai.company_store_queries import valid_schema

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from starlette.types import ASGIApp, Receive, Scope, Send


def admit_guest(engine: Engine, schema: str, actor_id: str, *, ai_run: bool) -> bool:
    """Reserve one write and optional AI run atomically across all replicas."""
    if not valid_schema(schema):
        message = "invalid guest quota schema"
        raise ValueError(message)
    table = f'"{schema}".samurai_guest_usage'
    today = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date"
    with engine.begin() as connection:
        _ = connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"samurai-guest-admission:{schema}"},
        )
        _ = connection.execute(text(f"DELETE FROM {table} WHERE day < {today}"))  # noqa: S608 - validated schema.
        # Check both budgets before creating a row for a new guest.
        for actor, writes, runs in (("*", 300, 50), (actor_id, 60, 10)):
            allowed = connection.execute(
                text(
                    f"""SELECT writes < :writes AND ai_runs + :ai <= :runs
                        FROM {table} WHERE day = {today} AND actor_id = :actor"""  # noqa: S608 - validated schema.
                ),
                {"actor": actor, "writes": writes, "ai": int(ai_run), "runs": runs},
            ).scalar_one_or_none()
            if allowed is False:
                return False
        for actor in ("*", actor_id):
            _ = connection.execute(
                text(
                    f"""INSERT INTO {table} AS usage (day, actor_id, writes, ai_runs)
                        VALUES ({today}, :actor, 1, :ai)
                        ON CONFLICT (day, actor_id) DO UPDATE
                        SET writes = usage.writes + 1, ai_runs = usage.ai_runs + :ai"""  # noqa: S608 - validated schema.
                ),
                {"actor": actor, "ai": int(ai_run)},
            )
    return True


@dataclass(slots=True)
class GuestAccessBoundary:
    """Apply limits only to identities established by AgentOS JWT authorization."""

    app: ASGIApp
    enabled: bool
    engine: Engine | None
    schema: str

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject disabled guests, membership changes, or exhausted durable budgets."""
        state = cast("dict[str, object]", scope.get("state", {}))
        actor = state.get("user_id")
        if scope["type"] != "http" or not isinstance(actor, str) or not actor.startswith("guest:"):
            await self.app(scope, receive, send)
            return
        status, detail = 0, ""
        path = cast("str", scope["path"])
        if not self.enabled or self.engine is None:
            status, detail = 503, "Guest access is not enabled."
        elif "/members/" in path:
            status, detail = 403, "Guest workspaces cannot be shared."
        elif scope["method"] in {"POST", "PUT", "PATCH", "DELETE"} and not path.endswith(
            ("/cancel", "/resume")
        ):
            try:
                admitted = await run_in_threadpool(
                    admit_guest,
                    self.engine,
                    self.schema,
                    actor,
                    ai_run=path.endswith(("/runs", "/agui", "/continue")),
                )
                if not admitted:
                    status, detail = (
                        429,
                        "Guest daily usage limit reached. Try again tomorrow (UTC).",
                    )
            except SQLAlchemyError:
                status, detail = 503, "Guest usage checks are unavailable."
        if status:
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
            return
        await self.app(scope, receive, send)
