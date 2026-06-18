"""Shared OCR chunking and fallback helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, TypeVar

from loguru import logger

from buratino.llm.client import is_context_overflow_error
from buratino.models.domain import DocumentSummary
from buratino.models.errors import RepositoryError

ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class ChunkBuildResult:
    chunks: list[DocumentSummary]
    exceeded_limit: bool = False


@dataclass(frozen=True)
class ChunkedVerificationOutcome:
    effective_document: DocumentSummary
    raw_response: str


@dataclass(frozen=True)
class OcrChunker:
    max_chars: int
    overlap_chars: int
    max_chunks: int

    def build_chunks(self, document: DocumentSummary) -> ChunkBuildResult:
        if document.evidence_source != "ocr":
            return self.build_text_chunks(document)

        parts = tuple(part for part in document.ocr_parts if part.strip()) or (
            (document.ocr_text,) if document.ocr_text else ()
        )
        if not parts:
            return self.build_text_chunks(document)

        normalized_parts: list[str] = []
        for part in parts:
            normalized_parts.extend(self._normalize_part(part))

        chunks: list[str] = []
        current = ""
        for part in normalized_parts:
            candidate = part if not current else f"{current}\n\n{part}"
            if len(candidate) <= self.max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = self._with_overlap(chunks[-1], part) if chunks else part
        if current:
            chunks.append(current)

        if len(chunks) > self.max_chunks:
            return ChunkBuildResult(chunks=[], exceeded_limit=True)

        return ChunkBuildResult(
            chunks=[
                replace(document, evidence_text=chunk_text, evidence_source="ocr")
                for chunk_text in chunks
            ]
        )

    def build_text_chunks(self, document: DocumentSummary) -> ChunkBuildResult:
        text = document.evidence_text.strip()
        if not text:
            return ChunkBuildResult(chunks=[])

        normalized_parts = self._normalize_part(text)
        if not normalized_parts:
            return ChunkBuildResult(chunks=[])

        if len(normalized_parts) > self.max_chunks:
            return ChunkBuildResult(chunks=[], exceeded_limit=True)

        return ChunkBuildResult(
            chunks=[
                replace(document, evidence_text=chunk_text, evidence_source=document.evidence_source)
                for chunk_text in normalized_parts
            ]
        )

    def _normalize_part(self, part: str) -> list[str]:
        stripped = part.strip()
        if not stripped:
            return []
        if len(stripped) <= self.max_chars:
            return [stripped]

        paragraphs = [item.strip() for item in stripped.split("\n\n") if item.strip()]
        if len(paragraphs) > 1:
            normalized: list[str] = []
            current = ""
            for paragraph in paragraphs:
                candidate = paragraph if not current else f"{current}\n\n{paragraph}"
                if len(candidate) <= self.max_chars:
                    current = candidate
                    continue
                if current:
                    normalized.append(current)
                if len(paragraph) <= self.max_chars:
                    current = paragraph
                    continue
                normalized.extend(self._split_by_chars(paragraph))
                current = ""
            if current:
                normalized.append(current)
            return normalized

        return self._split_by_chars(stripped)

    def _split_by_chars(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.max_chars, len(text))
            chunks.append(text[start:end].strip())
            if end >= len(text):
                break
            start = max(end - self.overlap_chars, start + 1)
        return [chunk for chunk in chunks if chunk]

    def _with_overlap(self, previous_chunk: str, next_part: str) -> str:
        overlap = previous_chunk[-self.overlap_chars :].strip()
        if overlap:
            candidate = f"{overlap}\n\n{next_part}"
        else:
            candidate = next_part
        if len(candidate) <= self.max_chars:
            return candidate
        return next_part


def verify_with_ocr_chunk_fallback(
    *,
    document: DocumentSummary,
    label: str,
    render_prompt: Callable[[DocumentSummary], str],
    generate_json: Callable[[str], str],
    parse_result: Callable[[str], ResultT],
    chunker: OcrChunker,
    is_confirmed_result: Callable[[ResultT], bool],
    finalize_result: Callable[[ResultT, DocumentSummary, int, int], ResultT],
) -> tuple[ResultT, DocumentSummary]:
    raw_response = generate_json(render_prompt(document))
    result = parse_result(raw_response)
    return result, document


def verify_with_overflow_recovery(
    *,
    document: DocumentSummary,
    label: str,
    render_prompt: Callable[[DocumentSummary], str],
    generate_json: Callable[[str], str],
    parse_result: Callable[[str], ResultT],
    chunker: OcrChunker,
    is_confirmed_result: Callable[[ResultT], bool],
    finalize_result: Callable[[ResultT, DocumentSummary, int, int], ResultT],
) -> tuple[ResultT, DocumentSummary]:
    try:
        return verify_with_ocr_chunk_fallback(
            document=document,
            label=label,
            render_prompt=render_prompt,
            generate_json=generate_json,
            parse_result=parse_result,
            chunker=chunker,
            is_confirmed_result=is_confirmed_result,
            finalize_result=finalize_result,
        )
    except RepositoryError as exc:
        if not is_context_overflow_error(exc):
            raise

        chunk_build = chunker.build_chunks(document)
        if chunk_build.exceeded_limit:
            logger.warning(
                "{} LLM chunking skipped: file={} chunk_count_exceeded_limit={}",
                label,
                document.file_name,
                chunker.max_chunks,
            )
        elif chunk_build.chunks:
            logger.warning(
                "{} LLM context overflow: file={} source=ocr; retrying with chunked OCR",
                label,
                document.file_name,
            )
            chunk_outcome = _verify_chunks(
                document=document,
                label=label,
                chunks=chunk_build.chunks,
                render_prompt=render_prompt,
                generate_json=generate_json,
                parse_result=parse_result,
                is_confirmed_result=is_confirmed_result,
                finalize_result=finalize_result,
            )
            if chunk_outcome is not None:
                return chunk_outcome

        if document.evidence_source != "ocr" or document.summary_text is None:
            raise
        logger.warning(
            "{} LLM context overflow: file={} source=ocr; retrying with summary",
            label,
            document.file_name,
        )
        summary_document = document.with_evidence(
            evidence_text=document.summary_text,
            evidence_source="summary",
        )
        try:
            raw_response = generate_json(render_prompt(summary_document))
            result = parse_result(raw_response)
            return result, summary_document
        except RepositoryError as summary_exc:
            if not is_context_overflow_error(summary_exc):
                raise
            summary_chunk_build = chunker.build_chunks(summary_document)
            if summary_chunk_build.exceeded_limit:
                logger.warning(
                    "{} LLM summary chunking skipped: file={} chunk_count_exceeded_limit={}",
                    label,
                    document.file_name,
                    chunker.max_chunks,
                )
                raise
            if not summary_chunk_build.chunks:
                raise
            logger.warning(
                "{} LLM context overflow: file={} source=summary; retrying with chunked summary",
                label,
                document.file_name,
            )
            chunk_outcome = _verify_chunks(
                document=summary_document,
                label=label,
                chunks=summary_chunk_build.chunks,
                render_prompt=render_prompt,
                generate_json=generate_json,
                parse_result=parse_result,
                is_confirmed_result=is_confirmed_result,
                finalize_result=finalize_result,
            )
            if chunk_outcome is not None:
                return chunk_outcome
            raise


def _verify_chunks(
    *,
    document: DocumentSummary,
    label: str,
    chunks: list[DocumentSummary],
    render_prompt: Callable[[DocumentSummary], str],
    generate_json: Callable[[str], str],
    parse_result: Callable[[str], ResultT],
    is_confirmed_result: Callable[[ResultT], bool],
    finalize_result: Callable[[ResultT, DocumentSummary, int, int], ResultT],
) -> tuple[ResultT, DocumentSummary] | None:
    chunk_results: list[ResultT] = []
    for chunk_index, chunk in enumerate(chunks, start=1):
        logger.info(
            "{} LLM chunk analysis: file={} chunk={}/{}",
            label,
            document.file_name,
            chunk_index,
            len(chunks),
        )
        try:
            raw_response = generate_json(render_prompt(chunk))
        except RepositoryError as exc:
            if is_context_overflow_error(exc):
                logger.warning(
                    "{} LLM chunk overflow: file={} chunk={}/{}",
                    label,
                    document.file_name,
                    chunk_index,
                    len(chunks),
                )
                return None
            raise
        chunk_results.append(parse_result(raw_response))

    selected_index = next(
        (index for index, item in enumerate(chunk_results) if is_confirmed_result(item)),
        0,
    )
    selected_result = finalize_result(
        chunk_results[selected_index],
        document,
        selected_index + 1,
        len(chunks),
    )
    effective_document = document.with_evidence(
        evidence_text=chunks[selected_index].evidence_text,
        evidence_source="ocr",
    )
    return selected_result, effective_document
