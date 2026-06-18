"""Doc-level event verification."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_event_document_result, TraceLimits
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import DocumentFactResult
from buratino.models.domain import DocumentSummary, VerificationTarget
from buratino.verifier.ocr_chunking import OcrChunker, verify_with_overflow_recovery


@dataclass
class EventVerifier:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    primary_model: str
    ocr_chunker: OcrChunker = field(default_factory=lambda: OcrChunker(40000, 1500, 120))
    trace_limits: TraceLimits = field(default_factory=TraceLimits)

    def verify_documents(
        self,
        target: VerificationTarget,
        documents: list[DocumentSummary],
        *,
        model: str | None = None,
    ) -> tuple[list[DocumentFactResult], list[DocumentSummary]]:
        llm_model = model or self.primary_model
        results: list[DocumentFactResult] = []
        effective_documents: list[DocumentSummary] = []
        for index, document in enumerate(documents, start=1):
            logger.info("Event LLM analysis: document {}/{} file={} source={}", index, len(documents), document.file_name, document.evidence_source)
            result, effective_document = verify_with_overflow_recovery(
                document=document,
                label="Event",
                render_prompt=lambda current_document: self.prompt_loader.render(
                    "event_fact_summary.md",
                    self._build_payload(target, current_document),
                ),
                generate_json=lambda prompt: self.llm_client.generate_json(model=llm_model, prompt=prompt),
                parse_result=lambda raw_response: parse_event_document_result(
                    raw_response,
                    trace_limits=self.trace_limits,
                ),
                chunker=self.ocr_chunker,
                is_confirmed_result=lambda item: item.fact_status == "подтверждено",
                finalize_result=self._finalize_chunk_result,
            )
            logger.info(
                "Event LLM result: document {}/{} status={} comparison={}",
                index,
                len(documents),
                result.fact_status,
                result.comparison_result,
            )
            results.append(result)
            effective_documents.append(effective_document)
        return results, effective_documents

    @staticmethod
    def _finalize_chunk_result(
        result: DocumentFactResult,
        document: DocumentSummary,
        chunk_index: int,
        chunk_count: int,
    ) -> DocumentFactResult:
        return replace(
            result,
            document_id=document.document_id,
            file_name=document.file_name,
            reasoning=f"{result.reasoning} Вывод получен по chunked OCR, chunk {chunk_index}/{chunk_count}.",
        )

    @staticmethod
    def _build_payload(target: VerificationTarget, document: DocumentSummary) -> dict[str, object]:
        return {
            "event_id": target.event_id,
            "event_name": target.event_name,
            "event_description": target.event_description,
            "event_type": target.event_type,
            "planned_value": target.planned_value,
            "planned_unit": target.planned_unit,
            "normalized_action": target.normalized_action,
            "normalized_subject": target.normalized_subject,
            "document_id": document.document_id,
            "file_name": document.file_name,
            "evidence_source": document.evidence_source,
            "evidence_text": document.evidence_text,
        }
