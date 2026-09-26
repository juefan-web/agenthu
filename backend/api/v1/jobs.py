from __future__ import annotations

import uuid
from typing import Any

from arq.jobs import Job, JobStatus
from fastapi import APIRouter, status
from pydantic import BaseModel

from backend.api.deps import CurrentUser
from backend.core.errors import ServiceUnavailableError
from backend.worker.queue import get_arq_pool

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobAccepted(BaseModel):
    job_id: str


class JobStatusRead(BaseModel):
    job_id: str
    status: JobStatus
    result: Any | None = None


@router.post("/ping", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_ping(user: CurrentUser) -> JobAccepted:
    """Enqueue the liveness task to prove the Redis/Arq pipeline works."""

    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job("ping", "pong", _job_id=f"ping:{uuid.uuid4().hex}")
    except Exception as exc:  # pragma: no cover - depends on Redis availability
        raise ServiceUnavailableError("Job queue is unavailable") from exc
    return JobAccepted(job_id=job.job_id if job else "")


@router.get("/{job_id}", response_model=JobStatusRead)
async def job_status(job_id: str, user: CurrentUser) -> JobStatusRead:
    try:
        pool = await get_arq_pool()
    except Exception as exc:  # pragma: no cover
        raise ServiceUnavailableError("Job queue is unavailable") from exc
    job = Job(job_id, pool)
    status = await job.status()
    result = await job.result(timeout=0) if status == JobStatus.complete else None
    return JobStatusRead(job_id=job_id, status=status, result=result)
