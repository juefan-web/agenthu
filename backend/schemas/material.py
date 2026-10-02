"""Schemas and consent text for the materials-ingestion API surface (D-033).

The consent text is versioned backend-side: the client renders exactly what
GET returns, and an opt-in must echo the *current* ``consent_text_version``.
When the text changes, bump ``CONSENT_TEXT_VERSION`` — stale-version opt-ins
are rejected so every "开启" was given on the wording the user actually read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from backend.schemas.common import ORMModel

CONSENT_TEXT_VERSION = "v1"

CONSENT_TEXT = (
    "开启后，当你在此课程中提问，系统会把与问题最相关的课程资料片段"
    "（仅命中片段的文本，不发送整份文件）发送给模型供应商以生成回答，"
    "并仅限当前课程范围。供应商（OpenAI）默认不使用 API 输入输出训练模型；"
    "但送出的文本在供应商侧存在至多 30 天的滥用监控日志保留（其政策承诺"
    "默认不用于训练）。文件内容不会分发给其他用户。你可以随时关闭本开关"
    "（关闭后不再发送新请求），也可以随时删除已上传的文件及其全部派生"
    "数据（删除不可恢复，需要确认）。"
)


class MaterialChunkRead(ORMModel):
    id: uuid.UUID
    file_id: uuid.UUID
    page: int | None
    chunk_index: int
    content: str
    char_count: int
    scan_status: str
    scanner_version: str
    scan_flags: list[str]
    # Populated from the ORM column during validation but excluded from the
    # response — shipping 1536 floats per row would dwarf the payload.
    embedding: list[float] | None = Field(default=None, exclude=True)
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def embedding_present(self) -> bool:
        return self.embedding is not None


class GroundingConsentRead(BaseModel):
    course_name: str
    enabled: bool
    consent_text: str
    consent_text_version: str
    consented_at: datetime | None


class GroundingConsentUpdate(BaseModel):
    course_name: str = Field(min_length=1, max_length=300)
    enabled: bool
    # Version of the text the user read and agreed to; must match the current
    # CONSENT_TEXT_VERSION or the opt-in is rejected (422).
    consent_text_version: str = Field(min_length=1, max_length=32)
