"""Unit tests for in-memory resume parsing (PDF, DOCX, TXT)."""

import io

import docx
import pytest

from jobpilot.resume.parser import (
    extract_docx_text,
    extract_resume_text,
    extract_txt_text,
)


def create_minimal_pdf_bytes(text: str) -> bytes:
    """Helper to generate a valid PDF byte string in memory."""
    from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
    from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(100, 750, text)
    c.save()
    buf.seek(0)
    return buf.read()


def create_minimal_docx_bytes(paragraphs: list[str]) -> bytes:
    """Helper to generate a valid DOCX byte string in memory."""
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def test_extract_txt_text() -> None:
    content = b"John Doe\nSoftware Engineer\nSkills: Python, FastAPI"
    text = extract_txt_text(content)
    assert "John Doe" in text
    assert "Python, FastAPI" in text


def test_extract_docx_text() -> None:
    paragraphs = ["Jane Smith", "Education: MIT BS CS 2025", "Projects: Distributed Raft KV Store"]
    docx_bytes = create_minimal_docx_bytes(paragraphs)
    text = extract_docx_text(docx_bytes)
    assert "Jane Smith" in text
    assert "Distributed Raft" in text


def test_extract_resume_text_dispatcher() -> None:
    # TXT
    txt_bytes = b"Jane Doe - ML Intern"
    assert "ML Intern" in extract_resume_text("resume.txt", txt_bytes)

    # DOCX
    paragraphs = ["Alex Rivera", "Experience: SWE Intern"]
    docx_bytes = create_minimal_docx_bytes(paragraphs)
    assert "Alex Rivera" in extract_resume_text("resume.docx", docx_bytes)


def test_extract_resume_text_unsupported_format() -> None:
    with pytest.raises(ValueError, match="Unsupported file format"):
        extract_resume_text("resume.png", b"fake image bytes")


def test_extract_empty_bytes() -> None:
    with pytest.raises(ValueError, match="is empty"):
        extract_resume_text("resume.txt", b"")
