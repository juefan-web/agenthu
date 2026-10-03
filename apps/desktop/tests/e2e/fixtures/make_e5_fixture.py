"""Regenerate the E5 synthetic lecture PDF (no real course material).

Hand-rolled minimal PDF, EN-only text layer (CJK in PDF text layers costs a
Type0/CID font chain — the #41 lesson; CJK assertion surfaces live in the
unit/integration suites instead). One long single line per page so the
extracted chunk content is byte-identical to PAGE_TEXTS below — the e5 spec
asserts citation quotes against these constants.

Usage: python make_e5_fixture.py  (from anywhere; writes e5-lecture.pdf
next to this file and verifies the pypdf extraction round-trip).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

PAGE_TEXTS = [
    (
        "The sampling theorem requires that the sampling rate must be at least "
        "twice the highest frequency present in the signal. This lower bound is "
        "called the Nyquist rate."
    ),
    (
        "Aliasing occurs when the sampling rate falls below the Nyquist rate. "
        "The folded spectrum overlaps and the original signal cannot be "
        "recovered exactly."
    ),
]


def _content_object(text: str) -> bytes:
    stream = f"BT /F1 11 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    return b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"


def build_pdf() -> bytes:
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 6 0 R >> >> /Contents 4 0 R >>",
        _content_object(PAGE_TEXTS[0]),
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 6 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        _content_object(PAGE_TEXTS[1]),
    ]
    for text in PAGE_TEXTS:
        for bad in ("(", ")", "\\"):
            if bad in text:
                raise ValueError(
                    f"page text contains PDF literal-string delimiter {bad!r}: {text!r}"
                )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


def main() -> None:
    target = Path(__file__).with_name("e5-lecture.pdf")
    pdf = build_pdf()
    target.write_bytes(pdf)
    extracted = [page.extract_text() for page in PdfReader(target).pages]
    if extracted != PAGE_TEXTS:
        raise SystemExit(f"extraction round-trip mismatch:\n{extracted!r}\nvs\n{PAGE_TEXTS!r}")
    print(f"wrote {target} ({len(pdf)} bytes), extraction round-trip verified")


if __name__ == "__main__":
    main()
