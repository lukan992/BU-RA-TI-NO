from __future__ import annotations

from buratino.models.domain import DocumentSummary
from buratino.verifier.ocr_chunking import OcrChunker


def test_ocr_chunker_preserves_part_order_and_max_chars() -> None:
    chunker = OcrChunker(max_chars=20, overlap_chars=5, max_chunks=10)
    document = DocumentSummary(
        document_id="doc-1",
        file_name="report.pdf",
        evidence_text="page 1\n\npage 2",
        evidence_source="ocr",
        ocr_text="page 1\n\npage 2",
        ocr_parts=("page 1", "page 2"),
    )

    result = chunker.build_chunks(document)

    assert not result.exceeded_limit
    assert [chunk.evidence_text for chunk in result.chunks] == ["page 1\n\npage 2"]


def test_ocr_chunker_splits_large_part_with_overlap() -> None:
    chunker = OcrChunker(max_chars=10, overlap_chars=3, max_chunks=10)
    text = "abcdefghijKLMNOPQRST"
    document = DocumentSummary(
        document_id="doc-1",
        file_name="report.pdf",
        evidence_text=text,
        evidence_source="ocr",
        ocr_text=text,
        ocr_parts=(text,),
    )

    result = chunker.build_chunks(document)

    assert not result.exceeded_limit
    assert [chunk.evidence_text for chunk in result.chunks] == [
        "abcdefghij",
        "hijKLMNOPQ",
        "OPQRST",
    ]


def test_ocr_chunker_respects_chunk_limit() -> None:
    chunker = OcrChunker(max_chars=5, overlap_chars=1, max_chunks=2)
    text = "abcdefghijklmnopqrstuvwxyz"
    document = DocumentSummary(
        document_id="doc-1",
        file_name="report.pdf",
        evidence_text=text,
        evidence_source="ocr",
        ocr_text=text,
        ocr_parts=(text,),
    )

    result = chunker.build_chunks(document)

    assert result.exceeded_limit
    assert result.chunks == []


def test_ocr_chunker_splits_summary_evidence_text() -> None:
    chunker = OcrChunker(max_chars=10, overlap_chars=3, max_chunks=10)
    text = "abcdefghijKLMNOPQRST"
    document = DocumentSummary(
        document_id="doc-1",
        file_name="report.pdf",
        evidence_text=text,
        evidence_source="summary",
        summary_text=text,
    )

    result = chunker.build_chunks(document)

    assert not result.exceeded_limit
    assert [chunk.evidence_text for chunk in result.chunks] == [
        "abcdefghij",
        "hijKLMNOPQ",
        "OPQRST",
    ]
