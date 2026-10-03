"""Mechanical citation verification unit tests (grounded-answers §3.4/§5).

The adversarial discipline mirrors the scanner's: a fabricated quote, an
out-of-range reference, and an invisible-character-obfuscated quote must all
be caught; a legitimate excerpt — including one the model copied with a
zero-width artifact — must survive. All cases share the scanner's
normalization, proving the two checks live in one text universe.
"""

from __future__ import annotations

import uuid

from backend.services.grounded_answers import (
    RetrievedChunk,
    _keyword_tokens,
    build_context,
    verify_citations,
)


def _chunk(content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        checksum="deadbeef" * 8,
        page=2,
        filename="lecture1.pdf",
        content=content,
    )


CHUNK_1 = _chunk("傅里叶变换将时域信号分解为频率分量。频谱展示了各频率的幅度。")
CHUNK_2 = _chunk("采样定理要求采样率至少为信号最高频率的两倍。")


def test_valid_citations_survive_with_spans() -> None:
    answer = (
        "变换的核心思想是分解「傅里叶变换将时域信号分解为频率分量」[1]。"
        "采样约束方面「采样率至少为信号最高频率的两倍」[2]。"
    )
    cleaned, grounded, citations = verify_citations(answer, [CHUNK_1, CHUNK_2])
    assert grounded is True
    assert len(citations) == 2
    assert citations[0]["page"] == 2
    assert citations[0]["checksum"] == "deadbeef" * 8
    assert CHUNK_1.content[citations[0]["span_start"] : citations[0]["span_end"]] == (
        "傅里叶变换将时域信号分解为频率分量"
    )
    assert cleaned == answer  # nothing stripped


def test_fabricated_quote_is_dropped_and_marker_stripped() -> None:
    answer = "根据资料「这段话根本不存在于任何课件之中」[1] 所以结论成立。"
    cleaned, grounded, citations = verify_citations(answer, [CHUNK_1])
    assert grounded is False
    assert citations == []
    # The [1] marker is gone; the fabricated excerpt stays as plain prose.
    assert "[1]" not in cleaned
    assert "这段话根本不存在于任何课件之中" in cleaned
    assert "所以结论成立" in cleaned


def test_out_of_range_reference_is_dropped() -> None:
    answer = "引用了一个不存在的条目「采样定理」[7]。"
    cleaned, grounded, citations = verify_citations(answer, [CHUNK_1, CHUNK_2])
    assert grounded is False
    assert citations == []
    assert "[7]" not in cleaned


def test_mixed_valid_and_fabricated_keeps_only_valid() -> None:
    answer = "正确部分「分解为频率分量」[1]，伪造部分「完全编造的内容」[2]。"
    cleaned, grounded, citations = verify_citations(answer, [CHUNK_1, CHUNK_2])
    assert grounded is True
    assert len(citations) == 1
    assert citations[0]["quote"] == "分解为频率分量"
    assert "完全编造的内容」[2]" not in cleaned
    assert "完全编造的内容」" in cleaned  # quote kept, marker gone


def test_zero_width_in_model_quote_survives_shared_normalization() -> None:
    # The model's excerpt carries a zero-width char the chunk does not have.
    # Both sides go through the scanner's normalize_text, so it still matches.
    answer = "零宽变体「分解为频\u200b率分量」[1] 依然可定位。"
    _cleaned, grounded, citations = verify_citations(answer, [CHUNK_1])
    assert grounded is True
    assert citations[0]["quote"] == "分解为频率分量"


def test_decomposed_accent_chunk_matches_composed_quote() -> None:
    # PDF extraction often yields decomposed accent sequences while the
    # model's excerpt is composed. §3.4's haystack is the chunk's NORMALIZED
    # text, so this genuine verbatim quote must survive — before the chunk
    # side went through the shared normalizer it was a false drop.
    chunk = _chunk("cafe\u0301 变换将时域信号分解为频率分量。")
    answer = "定义「café 变换将时域信号分解为频率分量」[1] 如上。"
    _cleaned, grounded, citations = verify_citations(answer, [chunk])
    assert grounded is True
    assert citations[0]["quote"] == "café 变换将时域信号分解为频率分量"


def test_keyword_tokens_split_words_and_cjk_bigrams() -> None:
    tokens = _keyword_tokens("What is the Fourier 变换 sampling 定理?")
    assert "fourier" in tokens and "sampling" in tokens
    # CJK runs become bigrams; tokens never shorter than 2 chars.
    assert "变换" in tokens
    assert all(len(t) >= 2 for t in tokens)


def test_build_context_numbers_chunks_memories_question() -> None:
    class _M:
        content = "该生在滤波作业上平均用时 40 分钟"

    context = build_context([CHUNK_1, CHUNK_2], [_M()], "什么是频谱泄漏")
    assert "[1] （lecture1.pdf，第 2 页）" in context
    assert "[2] （lecture1.pdf，第 2 页）" in context
    assert "已确认的个人学习记忆" in context
    assert "该生在滤波作业上平均用时 40 分钟" in context
    assert "问题：什么是频谱泄漏" in context


def test_cleaned_marker_order_matches_citations_order() -> None:
    # 客户端（GroundedAnswersView，PR #44）按 「quote」[n] 重析清洗后正文，
    # 假定「存活标记序 == citations 数组序」。该不变量由 verify_citations
    # 的单遍循环结构保证——本测试把它钉死，防止未来重构悄悄破坏 B 侧的
    # 渲染假设（中间夹一条伪造引用后，两侧顺序仍须一一对应）。
    answer = (
        "其一「傅里叶变换将时域信号分解为频率分量」[1]，"
        "其二「这段话根本不存在于任何课件之中」[2]，"
        "其三「频谱展示了各频率的幅度」[1]。"
    )
    cleaned, grounded, citations = verify_citations(answer, [CHUNK_1])
    assert grounded is True
    # 伪造者只丢 [2] 标记（「」与摘录保留为散文），存活者原样在位
    assert cleaned == (
        "其一「傅里叶变换将时域信号分解为频率分量」[1]，"
        "其二「这段话根本不存在于任何课件之中」，"
        "其三「频谱展示了各频率的幅度」[1]。"
    )
    assert [c["quote"] for c in citations] == [
        "傅里叶变换将时域信号分解为频率分量",
        "频谱展示了各频率的幅度",
    ]
