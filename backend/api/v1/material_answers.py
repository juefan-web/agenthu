"""Grounded course-material Q&A endpoints (TASKS/m3-grounded-answers.md §6).

The POST path is synchronous by design: the user is waiting for the answer,
so generation happens in-request. Failure semantics are frozen: no consent
→ 403 with zero provider calls; provider failure → 503 (never a smooth
ungrounded answer). Citations in the response already passed mechanical
verification; ``grounded=false`` means none survived.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from backend.adapters.model_provider import get_model_provider
from backend.adapters.model_provider.base import (
    ModelProviderError,
    ModelProviderUnavailable,
)
from backend.api.deps import CurrentUser, DBSession, PaginationDep
from backend.core.errors import NotFoundError, PermissionDeniedError, ServiceUnavailableError
from backend.models.material import MaterialAnswer
from backend.schemas.common import Page
from backend.schemas.material import (
    MaterialAnswerCreate,
    MaterialAnswerRead,
)
from backend.services.grounded_answers import (
    GroundingPermissionDenied,
    answer_question,
    list_answers,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/material/answers", tags=["material-answers"])


def _get_answer(db: DBSession, user_id: uuid.UUID, answer_id: uuid.UUID) -> MaterialAnswer:
    row = db.scalar(
        select(MaterialAnswer).where(
            MaterialAnswer.id == answer_id, MaterialAnswer.user_id == user_id
        )
    )
    if row is None:
        raise NotFoundError("Answer not found")
    return row


CourseNameQuery = Annotated[str, Query(min_length=1, max_length=300)]


@router.post("", response_model=MaterialAnswerRead, status_code=status.HTTP_201_CREATED)
async def create_answer(
    payload: MaterialAnswerCreate,
    user: CurrentUser,
    db: DBSession,
) -> MaterialAnswer:
    try:
        provider = get_model_provider()
        record = await answer_question(
            db,
            provider,
            user_id=user.id,
            course_name=payload.course_name,
            question=payload.question,
            model_version=provider.model_name,
        )
    except GroundingPermissionDenied:
        # Fail-closed before any provider call (§3.2 — the gate is checked
        # inside the service, next to the calls it guards).
        raise PermissionDeniedError(
            "Grounding is not enabled for this course; opt in via PUT /v1/grounding-consent first"
        ) from None
    except ModelProviderUnavailable as exc:
        logger.warning("Grounding generation unavailable", exc_info=True)
        raise ServiceUnavailableError(str(exc)) from exc
    except ModelProviderError as exc:
        logger.warning("Grounding generation failed", exc_info=True)
        raise ServiceUnavailableError(str(exc)) from exc
    return record


@router.get("", response_model=Page[MaterialAnswerRead])
def list_course_answers(
    course_name: CourseNameQuery,
    user: CurrentUser,
    db: DBSession,
    pagination: PaginationDep,
) -> Page[MaterialAnswerRead]:
    rows, total = list_answers(
        db,
        user_id=user.id,
        course_name=course_name,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page(
        items=[MaterialAnswerRead.model_validate(row) for row in rows],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.delete("/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer(
    answer_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> Response:
    """§3.5 deletion entry: citations are snapshot tuples on the row, so
    deleting an answer never resurrections a deleted file's content."""

    row = _get_answer(db, user.id, answer_id)
    db.delete(row)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
