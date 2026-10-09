"""Grounded answers integration tests (TASKS/m3-grounded-answers.md §7).

Full pipeline at the API level with a scripted provider: consent gate
(fail-closed, zero calls), hybrid retrieval -> context, mechanical citation
verification (fabricated quotes dropped), memory integration (deleted
memory no longer reflected — the M3 exit sentence's backend half), answer
persistence with model/prompt versions, isolation, and the deletion entry.

Fixtures are synthetic throughout (PPTX carrier for CJK content); the
provider is always fake — nothing here can touch a real vendor.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select

from backend.adapters.model_provider.base import EmbeddingResult, ModelProviderError
from backend.models.enums import MemoryCorrectionStatus, MemoryKind
from backend.models.file import FileObject
from backend.models.material import GroundingConsent
from backend.models.memory import Memory
from backend.schemas.material import CONSENT_TEXT_VERSION
from backend.services.material_ingestion import embed_pending_chunks, run_extraction
from backend.services.model_consent import set_consent
from tests.integration.test_materials import _upload
from tests.unit.test_material_extraction import make_pptx

pytestmark = pytest.mark.integration

COURSE = "信号与系统"
PAGE_1 = "傅里叶变换将时域信号分解为频率分量，频谱展示各频率幅度。"
PAGE_2 = "采样定理要求采样率至少为信号最高频率的两倍，否则发生混叠。"


class FakeGroundingProvider:
    """Scripted provider: records calls, returns content-derived vectors."""

    name = "openai-fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.scripted = ""
        # 顺序无关脚本：以 build_context 的产物为入参构造回答——引用从
        # 上下文原位提取，不锁 RRF 融合后的块次序（验收轮教训：任何把
        # 排序写死的 scripted 都会在检索语义修正时假性翻红）。
        self.scripted_fn: Callable[[str], str] | None = None
        self.generate_error: Exception | None = None

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(("embed", list(texts)))
        vectors = []
        for text in texts:
            digest = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            vectors.append([float((digest >> (k % 32)) & 1) for k in range(1536)])
        return EmbeddingResult(vectors=vectors, model="fake-embed")

    async def generate(self, input_text: str, instructions: str | None = None) -> str:
        self.calls.append(("generate", input_text))
        if self.generate_error is not None:
            raise self.generate_error
        if self.scripted_fn is not None:
            return self.scripted_fn(input_text)
        return self.scripted

    def build_responses_request(
        self, model: str, input_text: str, instructions: str | None = None
    ) -> dict[str, object]:
        return {"model": model, "input": input_text, "store": False}

    @property
    def generate_inputs(self) -> list[str]:
        return [str(payload) for kind, payload in self.calls if kind == "generate"]


@pytest.fixture
def provider(monkeypatch) -> FakeGroundingProvider:
    fake = FakeGroundingProvider()
    monkeypatch.setattr("backend.api.v1.material_answers.get_model_provider", lambda: fake)
    return fake


def _enable_consent(db_session, user_id: uuid.UUID, course: str = COURSE) -> None:
    db_session.add(
        GroundingConsent(
            user_id=user_id,
            course_name=course,
            enabled=True,
            consent_text_version=CONSENT_TEXT_VERSION,
        )
    )
    db_session.flush()


def _enable_model_consent(db_session, user_id: uuid.UUID) -> None:
    set_consent(db_session, user_id, enabled=True, consent_text_version="v1")
    db_session.flush()


def _seed_course_material(db_session, client, headers, storage) -> tuple[uuid.UUID, uuid.UUID]:
    body = _upload(
        client,
        headers,
        make_pptx([PAGE_1, PAGE_2]),
        "signals.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        COURSE,
    )
    file_id = uuid.UUID(body["id"])
    result = run_extraction(db_session, file_id, storage)
    assert result["status"] == "extracted" and result["clean"] == 2
    user_id = db_session.scalar(select(FileObject.user_id).where(FileObject.id == file_id))
    return file_id, user_id


def _add_episode(db_session, user_id: uuid.UUID, content: str) -> Memory:
    memory = Memory(
        user_id=user_id,
        level=1,
        kind=MemoryKind.EPISODE,
        domain="study",
        content=content,
        confidence=1.0,
        correction_status=MemoryCorrectionStatus.CONFIRMED,
    )
    db_session.add(memory)
    db_session.flush()
    return memory


def _user_id_from_headers(headers: dict[str, str]) -> uuid.UUID:
    from backend.core.security import decode_access_token

    return uuid.UUID(decode_access_token(headers["Authorization"].removeprefix("Bearer "))["sub"])


def _context_clause(context: str, ref: int) -> str:
    """上下文里第 ref 个 chunk 的首个句段（句号前）——原位提取，天然逐字，
    与该 chunk 在融合排序中的位置无关。"""
    match = re.search(rf"\[{ref}\] （[^）]*）\n(.+?)。", context)
    assert match is not None, f"context lacks chunk [{ref}]:\n{context}"
    return match.group(1)


def test_full_pipeline_grounded_answer(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    import asyncio

    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)
    _enable_model_consent(db_session, user_id)
    asyncio.run(embed_pending_chunks(db_session, provider, user_id, COURSE))
    memory = _add_episode(db_session, user_id, "该生在滤波器作业平均用时 40 分钟")

    provider.scripted_fn = lambda context: (
        f"定义：「{_context_clause(context, 1)}」[1]。"
        f"采样约束：「{_context_clause(context, 2)}」[2]。"
    )
    response = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "什么是采样定理"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["grounded"] is True
    assert len(body["citations"]) == 2
    assert body["model_version"] == "fake-model"
    assert body["prompt_version"] == "v2"
    assert str(memory.id) in body["memory_ids"]
    assert body["chunk_ids"]
    pages = sorted(c["page"] for c in body["citations"])
    assert pages == [1, 2]

    # Context carried the chunks AND the confirmed memory (§3.6).
    generate_input = provider.generate_inputs[0]
    assert PAGE_1[:8] in generate_input
    assert "该生在滤波器作业平均用时 40 分钟" in generate_input

    # Citations point back into the cited chunk's stored text.
    listing = client.get(
        "/v1/material/answers", params={"course_name": COURSE}, headers=auth_headers
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    row = listing.json()["items"][0]
    assert row["grounded"] is True and len(row["citations"]) == 2


def test_adversarial_fabricated_citations_dropped(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)

    provider.scripted_fn = lambda context: (
        f"真实引用：「{_context_clause(context, 1)}」[1]。"
        "伪造引用：「这段引文完全编造」[2]。"
        "越界引用：「再编一段」[9]。"
    )
    response = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "采样定理"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["grounded"] is True  # one survived
    quotes = [c["quote"] for c in body["citations"]]
    assert quotes == [_context_clause(provider.generate_inputs[0], 1)]
    assert "[9]" not in body["answer"]  # dropped markers stripped
    assert "这段引文完全编造" in body["answer"]  # excerpt stays as prose


def test_all_fabricated_yields_ungrounded(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)

    provider.scripted = "完全是编造的「不存在的引文」[1] 与「另一段编造」[2]。"
    response = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "任意问题"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["grounded"] is False
    assert body["citations"] == []


def test_consent_gate_is_fail_closed_with_zero_provider_calls(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    _seed_course_material(db_session, client, auth_headers, storage)  # no consent
    response = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "anything"},
        headers=auth_headers,
    )
    assert response.status_code == 403, response.text
    assert provider.calls == []  # not even an embed call


def test_memory_content_requires_global_model_consent(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    """钉子（外审 #1 / R1-A）：课程 grounding 同意只授权 chunk 检索；L1/L2
    记忆正文仅在全局模型上下文同意激活时进入 provider 请求体。同意关 ⇒
    请求体不含 memory.content、回执 memory_ids 为空（chunk 路径不受影响）；
    同意开 ⇒ 原语义恢复——门只加不撤。"""
    import asyncio

    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)
    asyncio.run(embed_pending_chunks(db_session, provider, user_id, COURSE))
    memory = _add_episode(db_session, user_id, "该生在滤波器作业平均用时 40 分钟")
    provider.scripted_fn = lambda context: f"定义：「{_context_clause(context, 1)}」[1]。"

    # 全局模型上下文同意缺失（默认）——记忆不得进入请求体与回执。
    off = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "什么是采样定理"},
        headers=auth_headers,
    )
    assert off.status_code == 201, off.text
    assert off.json()["memory_ids"] == []
    assert "该生在滤波器作业平均用时 40 分钟" not in provider.generate_inputs[0]
    assert PAGE_1[:8] in provider.generate_inputs[0]  # chunk 检索不受门影响

    # 开启后同一问恢复原语义（正对照，防门假绿）。
    _enable_model_consent(db_session, user_id)
    provider.calls.clear()
    on = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "什么是采样定理"},
        headers=auth_headers,
    )
    assert on.status_code == 201, on.text
    assert str(memory.id) in on.json()["memory_ids"]
    assert "该生在滤波器作业平均用时 40 分钟" in provider.generate_inputs[0]


def test_provider_failure_is_503_not_smooth_answer(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)
    provider.generate_error = ModelProviderError("boom")
    response = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "anything"},
        headers=auth_headers,
    )
    assert response.status_code == 503, response.text


def test_deleted_memory_no_longer_reflected(
    db_session, client, auth_headers, storage, no_arq, provider
) -> None:
    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)
    _enable_model_consent(db_session, user_id)
    memory = _add_episode(db_session, user_id, "该生偏好晚间复习并做错题本")
    provider.scripted = "依据资料：「采样率至少为信号最高频率的两倍」[1]。结合记忆补充。"

    first = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "采样定理与我的复习"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    assert str(memory.id) in first.json()["memory_ids"]
    assert "该生偏好晚间复习并做错题本" in provider.generate_inputs[0]

    # Delete the memory (hard delete — supersedes_id stays NULL, live row gone)
    # and ask the same question again.
    db_session.delete(memory)
    db_session.flush()
    provider.calls.clear()
    provider.scripted = "再次依据资料：「采样率至少为信号最高频率的两倍」[1]。"

    second = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "采样定理与我的复习"},
        headers=auth_headers,
    )
    assert second.status_code == 201
    assert str(memory.id) not in second.json()["memory_ids"]
    assert "该生偏好晚间复习并做错题本" not in provider.generate_inputs[-1]


def test_isolation_and_delete_entry(
    db_session, client, register_user, storage, no_arq, provider
) -> None:
    from tests.conftest import login_headers

    owner = register_user()
    owner_headers = login_headers(client, owner["email"], owner["password"])
    _file_id, user_id = _seed_course_material(db_session, client, owner_headers, storage)
    _enable_consent(db_session, user_id)
    provider.scripted = "依据：「采样率至少为信号最高频率的两倍」[1]。"

    created = client.post(
        "/v1/material/answers",
        json={"course_name": COURSE, "question": "采样定理"},
        headers=owner_headers,
    )
    assert created.status_code == 201
    answer_id = created.json()["id"]

    stranger = register_user()
    stranger_headers = login_headers(client, stranger["email"], stranger["password"])
    assert (
        client.get(
            "/v1/material/answers", params={"course_name": COURSE}, headers=stranger_headers
        ).json()["total"]
        == 0
    )

    deleted = client.delete(f"/v1/material/answers/{answer_id}", headers=owner_headers)
    assert deleted.status_code == 204
    assert (
        client.get(
            "/v1/material/answers", params={"course_name": COURSE}, headers=owner_headers
        ).json()["total"]
        == 0
    )


def test_keyword_lane_is_any_token_and_recalls_embeddingless_chunks(
    db_session, client, auth_headers, storage, no_arq, provider
):
    """关键词通道 = OR 语义（验收轮发现：交付时误写为 AND，含功能词的问题
    在该通道直接归零）。无 embedding 的 chunk（未同意课程、从未回填）只能
    靠关键词通道召回——问题里混一个原文 token 与一个不在原文的功能词，
    通道仍须命中。"""
    import asyncio

    from backend.services.grounded_answers import retrieve_chunks

    _file_id, user_id = _seed_course_material(db_session, client, auth_headers, storage)
    _enable_consent(db_session, user_id)
    db_session.commit()

    retrieved = asyncio.run(
        retrieve_chunks(
            db_session,
            provider,
            user_id=user_id,
            course_name=COURSE,
            # what/does/require 不在课件原文；采样/定理 双元在 PAGE_2。
            question="What does 采样定理 require?",
        )
    )
    assert retrieved, "关键词通道必须召回无 embedding 的 chunk（OR 语义）"
    assert any("采样定理" in chunk.content for chunk in retrieved)
