"""Course-material text extraction: file bytes -> per-page text -> chunks.

Extractors are deliberately boring per-page text pulls (PDF text layer,
PPTX shape text, plain text). OCR and scanned-image PDFs are out of scope
for this slice; a PDF whose pages extract no text at all yields zero chunks
and the file is marked ``unsupported_type`` rather than silently empty.

Chunking keeps the page as the primary unit (citation anchors are
file+page+span); only pages exceeding ``max_chars`` are split further at
paragraph/sentence boundaries so spans stay meaningful.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

PDF_CONTENT_TYPE = "application/pdf"
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

MAX_CHUNK_CHARS = 2000


class UnsupportedContentTypeError(Exception):
    """No extractor for this content type (file → status unsupported_type)."""


@dataclass(frozen=True)
class ExtractedPage:
    page: int | None  # 1-based page/slide number; None = no page concept
    text: str


@dataclass(frozen=True)
class RawChunk:
    page: int | None
    chunk_index: int
    text: str


def extract_pages(data: bytes, content_type: str, filename: str = "") -> list[ExtractedPage]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ctype == PDF_CONTENT_TYPE or suffix == "pdf":
        return _extract_pdf(data)
    if ctype == PPTX_CONTENT_TYPE or suffix == "pptx":
        return _extract_pptx(data)
    if ctype.startswith("text/") or suffix in {"txt", "md", "markdown"}:
        return [ExtractedPage(page=None, text=data.decode("utf-8", errors="replace"))]
    raise UnsupportedContentTypeError(
        f"No extractor for content type {ctype or '(empty)'} (filename={filename!r})"
    )


def _extract_pdf(data: bytes) -> list[ExtractedPage]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return [
        ExtractedPage(page=i + 1, text=(page.extract_text() or ""))
        for i, page in enumerate(reader.pages)
    ]


def _extract_pptx(data: bytes) -> list[ExtractedPage]:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    pages: list[ExtractedPage] = []
    for i, slide in enumerate(presentation.slides):
        parts: list[str] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = shape.text_frame.text
            if text.strip():
                parts.append(text)
        # Speaker notes are part of the material the lecturer prepared; keep
        # them on the slide's page so citations stay page-granular.
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        if notes.strip():
            parts.append(notes)
        pages.append(ExtractedPage(page=i + 1, text="\n\n".join(parts)))
    return pages


def chunk_pages(pages: list[ExtractedPage], max_chars: int = MAX_CHUNK_CHARS) -> list[RawChunk]:
    """Split pages into ordered chunks, skipping pages with no text."""

    chunks: list[RawChunk] = []
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        for piece in _split_long_text(text, max_chars):
            chunks.append(RawChunk(page=page.page, chunk_index=len(chunks), text=piece))
    return chunks


def _split_long_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    # Greedy paragraph packing, then sentence packing, then hard cut. Split
    # points stay at boundaries the citation span can still express.
    pieces: list[str] = []
    current = ""
    paragraphs = text.split("\n\n")
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars or not current:
            if len(paragraph) <= max_chars:
                current = candidate
                continue
            # Oversized single paragraph: pack by sentence instead.
            if current:
                pieces.append(current)
                current = ""
            for sentence in _split_sentences(paragraph, max_chars):
                pieces.append(sentence)
            continue
        pieces.append(current)
        current = paragraph
    if current:
        pieces.append(current)
    return pieces


def _split_sentences(paragraph: str, max_chars: int) -> list[str]:
    sentences: list[str] = []
    current = ""
    for sentence in paragraph.split("。"):
        s = sentence + "。" if sentence or not current else sentence
        candidate = f"{current}{s}"
        if len(candidate) <= max_chars or not current:
            current = candidate
            continue
        sentences.append(current)
        current = s
    if current:
        sentences.append(current)
    # Hard cut for pathological no-delimiter runs (defensive; keeps every
    # chunk bounded so embeddings never see unbounded input).
    bounded: list[str] = []
    for s in sentences:
        while len(s) > max_chars:
            bounded.append(s[:max_chars])
            s = s[max_chars:]
        bounded.append(s)
    return bounded
