"""Grounded course-material Q&A (TASKS/m3-grounded-answers.md §3).

Orchestrates one answer end to end, all inside the caller's session so the
chunks, their file checksums, and the memories used for verification are one
consistent snapshot (§5: citation anchors cannot drift mid-check):

consent re-check (same ``consent_enabled`` as the embedding path — one gate,
never a second copy) -> hybrid retrieval (pgvector cosine + keyword, RRF
fusion; clean chunks only) -> confirmed-memory context via the shared
``retrieve_memories`` floor -> provider generate (``store=False`` pinned in
the adapter) -> MECHANICAL citation verification (each quote must be found
in the cited chunk's normalized text — the very ``normalize_text`` the
scanner applied, so "scanned" and "verified" are one text universe) ->
persist with model/prompt versions.

Retrieval-eligibility note required by §3.1: hard-blocked chunks were never
stored (#41), and ``flagged`` chunks — stored but never embedded — are
excluded from BOTH retrieval lanes here, honouring the frozen "flagged
never travels to the provider" semantics.

No vector index yet: exact scan, with per-query latency and candidate counts
logged for the HNSW decision (§3.7 — measure first, no premature index).
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.adapters.model_provider import ModelProvider
from backend.models.file import FileObject
from backend.models.material import MaterialAnswer, MaterialChunk
from backend.services.content_scanner import normalize_text
from backend.services.material_ingestion import consent_enabled
from backend.services.memory_retrieval import retrieve_memories

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

_TOP_K_PER_LANE = 8
_FINAL_CONTEXT_CHUNKS = 6
_MEMORY_PER_LEVEL = 5
RRF_K = 60

# Citation pair format the prompt mandates: 「<verbatim excerpt from the
# provided chunk>」[n]. Both delimiters are unambiguous full-width marks.
_CITATION_RE = re.compile(r"「(?P<quote>[^」]{1,400})」\[(?P<ref>\d{1,3})\]")

INSTRUCTIONS = (
    "你是课程学习助教。仅依据提供的课程资料片段回答问题；资料以编号条目"
    "给出，每条注明文件与页码。每个事实性陈述后必须紧跟一个引用：从所引"
    "条目原文中逐字摘录一小段放入「」中，紧跟其来源条目的编号，形如"
    "「……摘录……」[2]。摘录必须是资料原文的连续片段（允许省略号缩短），"
    "不得改写。资料中没有依据时，直接说明资料未覆盖，不要编造引用。"
    "如果提供了「已确认的个人学习记忆」，可结合它组织回答，但引用仍只能"
    "指向课程资料条目。用中文回答。"
)


class GroundingPermissionDenied(Exception):
    """Course has no enabled grounding consent (fail-closed, §3.2)."""


class RetrievedChunk:
    """Everything the citation check needs, from one snapshot read."""

    __slots__ = ("checksum", "chunk_id", "content", "file_id", "filename", "page")

    def __init__(
        self,
        chunk_id: uuid.UUID,
        file_id: uuid.UUID,
        checksum: str | None,
        page: int | None,
        filename: str,
        content: str,
    ) -> None:
        self.chunk_id = chunk_id
        self.file_id = file_id
        self.checksum = checksum
        self.page = page
        self.filename = filename
        self.content = content


def _keyword_tokens(question: str) -> list[str]:
    """Searchable substrings: ASCII words (len>=3) plus CJK bigrams."""

    tokens = {word.lower() for word in re.findall(r"[A-Za-z]{3,}", question)}
    cjk = re.findall(r"[\u4e00-\u9fff]", question)
    tokens.update(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    return sorted(tokens)[:24]


async def retrieve_chunks(
    session: Session,
    provider: ModelProvider,
    *,
    user_id: uuid.UUID,
    course_name: str,
    question: str,
) -> list[RetrievedChunk]:
    """Hybrid retrieval: vector + keyword lanes, RRF-fused (§3.1/§3.7)."""

    started = time.perf_counter()
    base_conditions = [
        MaterialChunk.user_id == user_id,
        MaterialChunk.scan_status == "clean",
        FileObject.course_name == course_name,
    ]
    join = (FileObject, MaterialChunk.file_id == FileObject.id)

    # Vector lane: exact cosine scan (no index yet); missing embeddings are
    # simply outside this lane — the keyword lane still covers them.
    embed = await provider.embed_texts([question])
    question_vec = embed.vectors[0] if embed.vectors else None
    vector_rank: dict[uuid.UUID, int] = {}
    vector_rows: dict[uuid.UUID, tuple[MaterialChunk, FileObject]] = {}
    if question_vec is not None:
        stmt = (
            select(MaterialChunk, FileObject)
            .join(*join)
            .where(*base_conditions, MaterialChunk.embedding.is_not(None))
            .order_by(MaterialChunk.embedding.cosine_distance(question_vec))
            .limit(_TOP_K_PER_LANE)
        )
        for rank, (chunk, file_obj) in enumerate(session.execute(stmt).all()):
            vector_rank[chunk.id] = rank
            vector_rows[chunk.id] = (chunk, file_obj)

    # Keyword lane: ILIKE over normalized content, stable order. The tokens
    # come from the question; more hits rank first (crude but deterministic).
    tokens = _keyword_tokens(question)
    keyword_rank: dict[uuid.UUID, int] = {}
    keyword_rows: dict[uuid.UUID, tuple[MaterialChunk, FileObject]] = {}
    if tokens:
        like_clauses = [MaterialChunk.content.ilike(f"%{token}%") for token in tokens]
        stmt = (
            select(MaterialChunk, FileObject)
            .join(*join)
            .where(and_(*base_conditions, and_(*like_clauses)))
            .order_by(MaterialChunk.file_id, MaterialChunk.chunk_index)
            .limit(_TOP_K_PER_LANE * 4)
        )
        for rank, (chunk, file_obj) in enumerate(session.execute(stmt).all()):
            keyword_rank[chunk.id] = rank
            keyword_rows[chunk.id] = (chunk, file_obj)

    rows = {**vector_rows, **keyword_rows}

    def rrf(cid: uuid.UUID) -> float:
        score = 0.0
        if cid in vector_rank:
            score += 1.0 / (RRF_K + vector_rank[cid] + 1)
        if cid in keyword_rank:
            score += 1.0 / (RRF_K + keyword_rank[cid] + 1)
        return score

    selected = sorted(rows, key=lambda cid: (-rrf(cid), str(cid)))[:_FINAL_CONTEXT_CHUNKS]
    elapsed_ms = (time.perf_counter() - started) * 1000
    # HNSW decision data (§3.7): candidate counts per lane + total latency.
    logger.info(
        "Grounding hybrid retrieval",
        extra={
            "vector_candidates": len(vector_rows),
            "keyword_candidates": len(keyword_rows),
            "selected": len(selected),
            "latency_ms": round(elapsed_ms, 1),
        },
    )
    return [
        RetrievedChunk(
            chunk_id=cid,
            file_id=rows[cid][0].file_id,
            checksum=rows[cid][1].checksum_sha256,
            page=rows[cid][0].page,
            filename=rows[cid][1].filename,
            content=rows[cid][0].content,
        )
        for cid in selected
    ]


def build_context(chunks: list[RetrievedChunk], memories: list, question: str) -> str:
    parts: list[str] = []
    if chunks:
        parts.append("课程资料片段（编号即引用编号）：")
        for i, chunk in enumerate(chunks, start=1):
            page = f"，第 {chunk.page} 页" if chunk.page is not None else ""
            parts.append(f"[{i}] （{chunk.filename}{page}）\n{chunk.content}")
    else:
        parts.append("（本课程暂无可检索的资料片段）")
    if memories:
        parts.append("已确认的个人学习记忆（背景参考，不可作为引用来源）：")
        for memory in memories:
            parts.append(f"- {memory.content}")
    parts.append(f"问题：{question}")
    return "\n\n".join(parts)


def verify_citations(
    answer_text: str, chunks: list[RetrievedChunk]
) -> tuple[str, bool, list[dict]]:
    """Mechanical verification (§3.4): every 「quote」[n] must be findable
    in the cited chunk's normalized text.

    Returns (cleaned_answer, grounded, citations). Failed pairs lose their
    marker in the answer text (the excerpt stays as plain prose); with no
    surviving citation the answer is grounded=false — better no answer than
    a fake-grounded one (frozen §3 of the privacy decision).
    """

    citations: list[dict] = []
    failed_spans: list[tuple[int, int]] = []
    for match in _CITATION_RE.finditer(answer_text):
        ref = int(match.group("ref"))
        quote = match.group("quote")
        chunk = chunks[ref - 1] if 1 <= ref <= len(chunks) else None
        if chunk is not None:
            normalized_quote = normalize_text(quote)
            span_start = chunk.content.find(normalized_quote) if normalized_quote else -1
            if span_start >= 0:
                citations.append(
                    {
                        "file_id": str(chunk.file_id),
                        "checksum": chunk.checksum,
                        "page": chunk.page,
                        "span_start": span_start,
                        "span_end": span_start + len(normalized_quote),
                        "quote": normalized_quote,
                    }
                )
                continue
        failed_spans.append(match.span())

    cleaned = _strip_failed_markers(answer_text, failed_spans)
    return cleaned, bool(citations), citations


def _strip_failed_markers(text: str, failed_spans: list[tuple[int, int]]) -> str:
    """Remove the trailing ``[n]`` of each failed 「…」[n] pair (keep quote)."""

    for start, end in sorted(failed_spans, reverse=True):
        # end points just past ']'; the marker is the trailing [n] inside the
        # match: find its '[' by scanning back from end-1.
        marker_open = text.rfind("[", start, end)
        if marker_open != -1:
            text = text[:marker_open] + text[end:]
    return text


async def answer_question(
    session: Session,
    provider: ModelProvider,
    *,
    user_id: uuid.UUID,
    course_name: str,
    question: str,
    model_version: str,
) -> MaterialAnswer:
    """Full grounded-answer pipeline (see module docstring for ordering)."""

    if not consent_enabled(session, user_id, course_name):
        raise GroundingPermissionDenied(course_name)

    chunks = await retrieve_chunks(
        session, provider, user_id=user_id, course_name=course_name, question=question
    )
    # Confirmed L1/L2 via the shared floor (§3.6): two explicit level calls,
    # no parallel retrieval semantics invented here.
    memories = [
        *retrieve_memories(session, user_id=user_id, level=1, limit=_MEMORY_PER_LEVEL),
        *retrieve_memories(session, user_id=user_id, level=2, limit=_MEMORY_PER_LEVEL),
    ]
    context = build_context(chunks, memories, question)
    answer_text = await provider.generate(context, INSTRUCTIONS)
    cleaned, grounded, citations = verify_citations(answer_text, chunks)

    record = MaterialAnswer(
        user_id=user_id,
        course_name=course_name,
        question=question,
        answer=cleaned,
        grounded=grounded,
        citations=citations,
        chunk_ids=[str(chunk.chunk_id) for chunk in chunks],
        memory_ids=[str(memory.id) for memory in memories],
        model_version=model_version,
        prompt_version=PROMPT_VERSION,
    )
    session.add(record)
    session.flush()
    return record


def list_answers(
    session: Session,
    *,
    user_id: uuid.UUID,
    course_name: str,
    limit: int,
    offset: int,
) -> tuple[list[MaterialAnswer], int]:
    conditions = [
        MaterialAnswer.user_id == user_id,
        MaterialAnswer.course_name == course_name,
    ]
    total = session.scalar(select(func.count()).select_from(MaterialAnswer).where(*conditions)) or 0
    rows = list(
        session.scalars(
            select(MaterialAnswer)
            .where(*conditions)
            .order_by(MaterialAnswer.created_at.desc(), MaterialAnswer.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total)
