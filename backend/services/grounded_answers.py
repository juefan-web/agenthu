"""Grounded course-material Q&A (TASKS/m3-grounded-answers.md §3).

Orchestrates one answer end to end, all inside the caller's session so the
chunks, their file checksums, and the memories used for verification are one
consistent snapshot (§5: citation anchors cannot drift mid-check):

consent re-check (same ``consent_enabled`` as the embedding path — one gate,
never a second copy) -> hybrid retrieval (pgvector cosine + keyword, RRF
fusion; clean chunks only) -> confirmed-memory context via the shared
``retrieve_memories`` floor — memory content only under an active global
model-context consent -> provider generate (``store=False`` pinned in
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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.adapters.model_provider import ModelProvider
from backend.models.file import FileObject
from backend.models.material import MaterialAnswer, MaterialChunk
from backend.services.content_scanner import normalize_text
from backend.services.material_ingestion import consent_enabled
from backend.services.memory_retrieval import retrieve_memories
from backend.services.model_consent import active_consent_version

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2"

_TOP_K_PER_LANE = 8
_FINAL_CONTEXT_CHUNKS = 6
_MEMORY_PER_LEVEL = 5
RRF_K = 60

# Citation pair format the prompt mandates: 「<verbatim excerpt from the
# provided chunk>」[n]. Both delimiters are unambiguous full-width marks.
_CITATION_RE = re.compile(r"「(?P<quote>[^」]{1,400})」\[(?P<ref>\d{1,3})\]")

# Ellipsis forms the v2 prompt permits for shortening a quote: whole spans
# may be elided; every retained segment must stay verbatim and in order.
_ELLIPSIS_RE = re.compile(r"…{1,2}|\.{3}")

INSTRUCTIONS = (
    "你是课程学习助教。仅依据提供的课程资料片段回答问题；资料以编号条目"
    "给出，每条注明文件与页码。每个事实性陈述后必须紧跟一个引用：从所引"
    "条目原文中逐字摘录一小段放入「」中，紧跟其来源条目的编号，形如"
    "「……摘录……」[2]。摘录必须是资料原文的逐字片段；如需缩短，只能用"
    "省略号「……」整段略去中间内容，保留的字词不得增删或改写。资料中没有"
    "依据时，直接说明资料未覆盖，不要编造引用。"
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

    # Timing is split so the HNSW decision (§3.7) gets DB-scan latency that
    # is not inflated by the provider embed roundtrip.
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
    embed_ms = (time.perf_counter() - started) * 1000
    scan_started = time.perf_counter()
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

    # Keyword lane: ILIKE over normalized content, ANY-token semantics (OR) —
    # a question almost always carries function words absent from the corpus,
    # so ANDing the tokens zeroes this lane for real questions (found in the
    # M3 acceptance round: keyword_candidates=0 while the corpus contained
    # the content tokens). Stable order by (file_id, chunk_index); ranking
    # pressure comes from RRF fusion, not per-lane hit counts.
    tokens = _keyword_tokens(question)
    keyword_rank: dict[uuid.UUID, int] = {}
    keyword_rows: dict[uuid.UUID, tuple[MaterialChunk, FileObject]] = {}
    if tokens:
        like_clauses = [MaterialChunk.content.ilike(f"%{token}%") for token in tokens]
        stmt = (
            select(MaterialChunk, FileObject)
            .join(*join)
            .where(and_(*base_conditions, or_(*like_clauses)))
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
    elapsed_ms = (time.perf_counter() - scan_started) * 1000
    # HNSW decision data (§3.7): candidate counts per lane; scan_ms is the
    # DB-side portion only (embed_ms excluded — it is provider roundtrip).
    logger.info(
        "Grounding hybrid retrieval",
        extra={
            "vector_candidates": len(vector_rows),
            "keyword_candidates": len(keyword_rows),
            "selected": len(selected),
            "scan_ms": round(elapsed_ms, 1),
            "embed_ms": round(embed_ms, 1),
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


def _locate_quote(haystack: str, quote: str) -> tuple[int, int] | None:
    """Locate a possibly-ellipsis-shortened quote as ordered verbatim
    segments (audit gamma, ruling 3 / 方案 B).

    The v2 prompt permits shortening a quote ONLY by eliding whole spans
    with an ellipsis; each retained segment must appear verbatim and after
    the previous one. Returns ``(first_segment_start, last_segment_end)``
    or ``None`` when any segment is missing or out of order. A quote
    without ellipsis degenerates to a plain ``find`` (single segment).
    """

    segments = [segment for segment in _ELLIPSIS_RE.split(quote) if segment]
    if not segments:
        return None
    offset = 0
    first_start = -1
    last_end = -1
    for segment in segments:
        found = haystack.find(segment, offset)
        if found < 0:
            return None
        if first_start < 0:
            first_start = found
        offset = found + len(segment)
        last_end = offset
    return first_start, last_end


def verify_citations(
    answer_text: str, chunks: list[RetrievedChunk]
) -> tuple[str, bool, list[dict]]:
    """Mechanical verification (§3.4): every 「quote」[n] must be findable
    in the cited chunk's normalized text — verbatim, or as ordered
    verbatim segments when the model legally elided a middle span with an
    ellipsis.

    Returns (cleaned_answer, grounded, citations). Failed pairs lose their
    marker in the answer text (the excerpt stays as plain prose); with no
    surviving citation the answer is grounded=false — better no answer than
    a fake-grounded one (frozen §3 of the privacy decision).
    """

    citations: list[dict] = []
    failed_spans: list[tuple[int, int]] = []
    # §3.4/§6: the haystack is the chunk's NORMALIZED text. Clean chunks are
    # stored raw (the scanner only normalizes when it flags — and flagged
    # chunks never reach retrieval), so an NFC-composition difference, e.g. a
    # decomposed accent sequence from PDF extraction, would otherwise drop a
    # genuine verbatim quote. Normalization is identity on stored text
    # without such sequences, so spans keep indexing the stored content in
    # the common case (§6 already de-scopes exact span rendering).
    haystacks = [normalize_text(chunk.content) for chunk in chunks]
    for match in _CITATION_RE.finditer(answer_text):
        ref = int(match.group("ref"))
        quote = match.group("quote")
        chunk = chunks[ref - 1] if 1 <= ref <= len(chunks) else None
        if chunk is not None:
            normalized_quote = normalize_text(quote)
            located = _locate_quote(haystacks[ref - 1], normalized_quote)
            if located is not None:
                span_start, span_end = located
                citations.append(
                    {
                        "file_id": str(chunk.file_id),
                        "checksum": chunk.checksum,
                        "page": chunk.page,
                        "span_start": span_start,
                        "span_end": span_end,
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
    # no parallel retrieval semantics invented here. The course consent above
    # covers chunks only — memory content additionally requires an active
    # global model-context consent (same gate as agent_tools).
    memories: list = []
    if active_consent_version(session, user_id) is not None:
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
