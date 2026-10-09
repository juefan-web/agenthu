from __future__ import annotations

import uuid
from typing import Any

from arq.jobs import Job, JobStatus
from fastapi import APIRouter, status
from pydantic import BaseModel

from backend.api.deps import CurrentUser
from backend.core.errors import NotFoundError, ServiceUnavailableError
from backend.worker.queue import enqueue, get_arq_pool

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobAccepted(BaseModel):
    job_id: str


class JobStatusRead(BaseModel):
    job_id: str
    status: JobStatus
    result: Any | None = None


def user_job_id(user_id: uuid.UUID, name: str) -> str:
    """Job id whose first segment binds it to the owning user.

    ``GET /v1/jobs/{id}`` enforces ownership by checking this prefix, so a job
    id (and its result) can never be read by another user. A UUID string is a
    fixed 36 characters followed by ``:``, so one user's prefix cannot appear
    inside another's.
    """

    return f"{user_id}:{name}:{uuid.uuid4().hex}"


@router.post("/ping", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_ping(user: CurrentUser) -> JobAccepted:
    """Enqueue the liveness task to prove the Redis/Arq pipeline works."""

    try:
        pool = await get_arq_pool()
        job = await enqueue(pool, "ping", "pong", _job_id=user_job_id(user.id, "ping"))
    except Exception as exc:  # pragma: no cover - depends on Redis availability
        raise ServiceUnavailableError("Job queue is unavailable") from exc
    return JobAccepted(job_id=job.job_id if job else "")


@router.get("/{job_id}", response_model=JobStatusRead)
async def job_status(job_id: str, user: CurrentUser) -> JobStatusRead:
    if not job_id.startswith(f"{user.id}:"):
        # 404 rather than 403: do not confirm whether someone else's job exists.
        raise NotFoundError("Job not found")
    try:
        pool = await get_arq_pool()
    except Exception as exc:  # pragma: no cover
        raise ServiceUnavailableError("Job queue is unavailable") from exc
    job = Job(job_id, pool)
    status = await job.status()
    result = await job.result(timeout=0) if status == JobStatus.complete else None
    return JobStatusRead(job_id=job_id, status=status, result=result)
