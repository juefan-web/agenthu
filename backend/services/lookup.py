"""Ownership-scoped lookups.

Every query in the API is scoped by ``user_id``. These helpers centralize that
rule so no endpoint can accidentally read another user's row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import NotFoundError
from backend.models.event import Event
from backend.models.goal import Goal
from backend.models.memory import Memory
from backend.models.plan import Plan
from backend.models.task import Task


def get_goal(session: Session, *, user_id: uuid.UUID, goal_id: uuid.UUID) -> Goal:
    goal = session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
    if goal is None:
        raise NotFoundError("Goal not found")
    return goal


def get_task(session: Session, *, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if task is None:
        raise NotFoundError("Task not found")
    return task


def get_plan(session: Session, *, user_id: uuid.UUID, plan_id: uuid.UUID) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id))
    if plan is None:
        raise NotFoundError("Plan not found")
    return plan


def get_memory(session: Session, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
    memory = session.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    if memory is None:
        raise NotFoundError("Memory not found")
    return memory


def get_event(session: Session, *, user_id: uuid.UUID, event_id: uuid.UUID) -> Event:
    event = session.scalar(select(Event).where(Event.id == event_id, Event.user_id == user_id))
    if event is None:
        raise NotFoundError("Event not found")
    return event
