"""Apply the E7 seed world to the isolated acceptance stack.

Direct insertion (task doc ruling ⑨): deterministic and free of derivation
side effects, with rows matching the production schema and constraints.
Users are inserted with the production ``hash_password`` so case drivers
can log in over HTTP. Object blobs go straight to the E7 bucket; the Redis
dirty-set membership is seeded for the wake-up path.

Usage (envs documented in tests/e7/README.md)::

    python -m tests.e7.seed            # truncate + reseed (per-case rebuild)
    python -m tests.e7.seed --no-truncate
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import Table, create_engine, text
from sqlalchemy.orm import Session

import backend.models  # noqa: F401  (register every table)
from backend.core.security import hash_password
from backend.db.base import Base
from backend.models.agent import AgentRun, PendingAction, PendingActionMutation
from backend.models.audit import AuditLog
from backend.models.chat import ChatMessage, ChatSession
from backend.models.consent import ModelContextConsent
from backend.models.current_state import CurrentState
from backend.models.event import Event
from backend.models.file import FileObject
from backend.models.focus_session import FocusSession
from backend.models.goal import Goal
from backend.models.material import GroundingConsent, MaterialAnswer, MaterialChunk
from backend.models.memory import Memory
from backend.models.notification import NotificationPreference
from backend.models.permission import PermissionGrant
from backend.models.plan import Plan, PlanItem
from backend.models.task import Task, task_events
from backend.models.user import User
from tests.e7.seed_spec import World, build_world

# Seed-table name -> model class or association Table. Kept explicit: a new
# seeded family must be added here *and* to seed_spec together.
_MODEL_BY_TABLE: dict[str, object] = {
    "users": User,
    "events": Event,
    "tasks": Task,
    "task_events": task_events,
    "focus_sessions": FocusSession,
    "goals": Goal,
    "memories": Memory,
    "plans": Plan,
    "plan_items": PlanItem,
    "current_states": CurrentState,
    "file_objects": FileObject,
    "material_chunks": MaterialChunk,
    "material_answers": MaterialAnswer,
    "chat_sessions": ChatSession,
    "chat_messages": ChatMessage,
    "agent_runs": AgentRun,
    "pending_actions": PendingAction,
    "pending_action_mutations": PendingActionMutation,
    "permission_grants": PermissionGrant,
    "grounding_consents": GroundingConsent,
    "model_context_consents": ModelContextConsent,
    "notification_preferences": NotificationPreference,
    "audit_logs": AuditLog,
}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"missing required env {name} (see tests/e7/README.md)", file=sys.stderr)
        raise SystemExit(2)
    return value


def truncate_all(engine) -> None:  # type: ignore[no-untyped-def]
    """Truncate every application table (never alembic_version)."""

    tables = sorted(name for name in Base.metadata.tables if name != "alembic_version")
    quoted = ", ".join(f'"{name}"' for name in tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))


def _put_blobs(world: World) -> None:
    """Purge the whole E7 bucket, then upload seeded blobs with a plain
    boto3 client (independent of the product storage adapter — evidence
    tooling must not share the code path it is auditing). The purge is part
    of per-case world rebuild: staged export packages from earlier cases
    would otherwise accumulate under exports/<handle>/ and break exact
    object expectations (first smoke lesson)."""

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=_require_env("S3_ENDPOINT_URL"),
        aws_access_key_id=_require_env("S3_ACCESS_KEY"),
        aws_secret_access_key=_require_env("S3_SECRET_KEY"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )
    bucket = _require_env("S3_BUCKET")
    paginator = client.get_paginator("list_objects_v2")
    keys: list[dict[str, str]] = []
    for page in paginator.paginate(Bucket=bucket):
        keys.extend({"Key": item["Key"]} for item in page.get("Contents", []))
    for start in range(0, len(keys), 1000):
        client.delete_objects(
            Bucket=bucket, Delete={"Objects": keys[start : start + 1000], "Quiet": True}
        )
    for key, content in world.blobs.items():
        client.put_object(Bucket=bucket, Key=key, Body=content)


def apply_world(engine, world: World) -> None:  # type: ignore[no-untyped-def]
    """Rows + blobs only. Redis is deliberately left alone: seeding the
    dirty set would wake the worker's trigger-evaluation cron and let the
    planner create rows non-deterministically (seeded deadlines sit in the
    past relative to the wall clock). verify asserts the dirty set is EMPTY
    for both users instead of asserting a seeded membership."""

    now = datetime.now(UTC)
    with Session(engine) as session:
        for spec in world.users.values():
            session.add(
                User(
                    id=spec.user_id,
                    email=spec.email,
                    display_name=spec.display_name,
                    hashed_password=hash_password(spec.password),
                    is_active=True,
                    owner_handle=spec.owner_handle,
                    data_generation=1,
                )
            )
        session.flush()
        # Flush whenever the table changes: world.rows is already in FK-safe
        # application order, but the unit of work only orders by ORM
        # relationships — pairs with a bare FK column and no relationship
        # (e.g. chat_sessions -> chat_messages) would otherwise insert in
        # mapper-sort order and violate the FK on fresh tables.
        current_table: str | None = None
        for row in world.rows:
            target = _MODEL_BY_TABLE.get(row.table)
            if target is None:
                print(f"seed spec row has no model mapping: {row.table}", file=sys.stderr)
                raise SystemExit(2)
            if isinstance(target, Table):
                session.execute(target.insert().values(**row.values))
            else:
                session.add(target(**row.values))  # type: ignore[misc]
            if row.table != current_table:
                session.flush()
                current_table = row.table
        session.commit()
        print(f"seed applied: {len(world.rows)} rows, 2 users (spec anchor utc)")
    _put_blobs(world)
    print(f"seed complete at {now.isoformat()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-truncate", action="store_true", help="apply without truncating first")
    args = parser.parse_args(argv)

    engine = create_engine(_require_env("E7_DATABASE_URL"))
    if not args.no_truncate:
        truncate_all(engine)
    apply_world(engine, build_world())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
