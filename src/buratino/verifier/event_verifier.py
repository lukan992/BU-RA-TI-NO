"""Doc-level event verification."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_runner import JsonStepErrorInfo, JsonStepFailure, run_prompt_json_step
from buratino.llm.json_parser import TraceLimits, parse_event_document_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import DocumentFactResult, ReasoningTrace
from buratino.models.domain import DocumentSummary, VerificationTarget
from buratino.models.errors import RepositoryError
from buratino.verifier.ocr_chunking import (
    OcrChunker,
    verify_with_forced_chunks,
)


@dataclass
class EventVerifier:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    primary_model: str
    evidence_source_mode: str = "summary_first"
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
            result, effective_document = self._verify_document(
                target=target,
                document=document,
                llm_model=llm_model,
                index=index,
                total=len(documents),
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

    def _verify_document(
        self,
        *,
        target: VerificationTarget,
        document: DocumentSummary,
        llm_model: str,
        index: int,
        total: int,
    ) -> tuple[DocumentFactResult, DocumentSummary]:
        if not self._has_ocr(document):
            return self._missing_ocr_result(document), document

        initial_document = document.with_evidence(
            evidence_text=document.ocr_text or document.evidence_text,
            evidence_source="ocr",
        )
        logger.info(
            "Event LLM analysis: document {}/{} file={} source={} mode={}",
            index,
            total,
            document.file_name,
            initial_document.evidence_source,
            self.evidence_source_mode,
        )
        try:
            result, effective_document = self._run_doc_analysis(
                target=target,
                document=initial_document,
                llm_model=llm_model,
            )
        except JsonStepFailure as exc:
            return self._error_result(initial_document, exc.info), initial_document
        except RepositoryError as exc:
            return self._ocr_analysis_failed_result(initial_document, str(exc)), initial_document

        result = self._decorate_result(result, effective_document)
        return result, effective_document

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

    def _run_doc_analysis(
        self,
        *,
        target: VerificationTarget,
        document: DocumentSummary,
        llm_model: str,
    ) -> tuple[DocumentFactResult, DocumentSummary]:
        return verify_with_forced_chunks(
            document=document,
            label="Event",
            render_prompt=lambda current_document: self.prompt_loader.render(
                "event_fact_summary.md",
                self._build_payload(target, current_document),
            ),
            generate_json=lambda prompt: self._generate_json(prompt_name="event_fact_summary.md", prompt=prompt, model=llm_model),
            parse_result=lambda raw_response: parse_event_document_result(
                raw_response,
                trace_limits=self.trace_limits,
            ),
            chunker=self.ocr_chunker,
            is_confirmed_result=lambda item: item.fact_status == "подтверждено",
            finalize_result=self._finalize_chunk_result,
        )

    def _run_ocr_chunk_analysis(
        self,
        *,
        target: VerificationTarget,
        document: DocumentSummary,
        llm_model: str,
    ) -> tuple[DocumentFactResult, DocumentSummary]:
        return verify_with_forced_chunks(
            document=document,
            label="Event",
            render_prompt=lambda current_document: self.prompt_loader.render(
                "event_fact_summary.md",
                self._build_payload(target, current_document),
            ),
            generate_json=lambda prompt: self._generate_json(prompt_name="event_fact_summary.md", prompt=prompt, model=llm_model),
            parse_result=lambda raw_response: parse_event_document_result(
                raw_response,
                trace_limits=self.trace_limits,
            ),
            chunker=self.ocr_chunker,
            is_confirmed_result=lambda item: item.fact_status == "подтверждено",
            finalize_result=self._finalize_chunk_result,
        )

    def _generate_json(self, *, prompt_name: str, prompt: str, model: str) -> str:
        return run_prompt_json_step(
            stage="doc_level",
            llm_client=self.llm_client,
            prompt_loader=self.prompt_loader,
            model=model,
            prompt_name=prompt_name,
            prompt=prompt,
            parse_result=lambda raw_response: parse_event_document_result(
                raw_response,
                trace_limits=self.trace_limits,
            ),
        ).raw_response

    def _decorate_result(
        self,
        result: DocumentFactResult,
        effective_document: DocumentSummary,
        *,
        diagnostic_reason: str | None = None,
    ) -> DocumentFactResult:
        return replace(
            result,
            evidence_source_used=effective_document.evidence_source,
            ocr_available=self._has_ocr(effective_document),
            summary_available=self._has_summary(effective_document),
            diagnostic_reason=diagnostic_reason or result.diagnostic_reason,
            missing_requirements_human=self._humanize_missing_requirements(
                result.reasoning_trace.missing_requirements
            ),
        )

    def _error_result(self, document: DocumentSummary, error_info: JsonStepErrorInfo) -> DocumentFactResult:
        return DocumentFactResult(
            document_id=document.document_id,
            file_name=document.file_name,
            fact_status="не подтверждено",
            reasoning="Doc-level event analysis failed after JSON repair retries.",
            reasoning_trace=ReasoningTrace(
                reason_codes=["llm_json_error"],
                missing_requirements=["valid_json_response"],
                short_rationale="LLM output could not be repaired into strict JSON.",
                confidence="low",
            ),
            evidence_source_used=document.evidence_source,
            ocr_available=self._has_ocr(document),
            summary_available=self._has_summary(document),
            diagnostic_stage=error_info.stage,
            diagnostic_reason="LLM returned malformed or empty JSON after repair retries.",
            missing_requirements_human=["валидный JSON ответ модели"],
            error_stage=error_info.stage,
            error_type=error_info.error_type,
            raw_response_preview=error_info.raw_response_preview,
            model_name=error_info.model_name,
            prompt_name=error_info.prompt_name,
        )

    def _missing_ocr_result(self, document: DocumentSummary) -> DocumentFactResult:
        return DocumentFactResult(
            document_id=document.document_id,
            file_name=document.file_name,
            fact_status="не подтверждено",
            reasoning="OCR отсутствует; документ не анализировался для event-level подтверждения.",
            reasoning_trace=ReasoningTrace(
                reason_codes=["ocr_missing"],
                missing_requirements=["ocr_text"],
                short_rationale="OCR отсутствует, подтверждение не проверялось.",
                confidence="low",
            ),
            evidence_source_used="none",
            ocr_available=False,
            summary_available=self._has_summary(document),
            diagnostic_stage="doc_level",
            diagnostic_reason="OCR отсутствует, документ не анализировался",
            missing_requirements_human=["OCR текст документа"],
        )

    def _ocr_analysis_failed_result(self, document: DocumentSummary, error: str) -> DocumentFactResult:
        return DocumentFactResult(
            document_id=document.document_id,
            file_name=document.file_name,
            fact_status="не подтверждено",
            reasoning="OCR анализ не дал подтверждения из-за ошибки chunk processing.",
            reasoning_trace=ReasoningTrace(
                reason_codes=["ocr_chunk_analysis_failed"],
                missing_requirements=["stable_ocr_chunk_analysis"],
                short_rationale="OCR chunk analysis завершился ошибкой.",
                confidence="low",
            ),
            evidence_source_used="ocr",
            ocr_available=True,
            summary_available=self._has_summary(document),
            diagnostic_stage="doc_level",
            diagnostic_reason=f"OCR chunk analysis failed: {error}",
            missing_requirements_human=["успешный OCR chunk analysis"],
        )

    @staticmethod
    def _has_ocr(document: DocumentSummary) -> bool:
        return bool(document.ocr_text or document.ocr_parts)

    @staticmethod
    def _has_summary(document: DocumentSummary) -> bool:
        return bool(document.summary_text)

    @staticmethod
    def _humanize_missing_requirements(items: list[str]) -> list[str]:
        if not items:
            return []
        mapping = {
            "explicit evidence": "нет явного подтверждающего фрагмента",
            "explicit confirmation": "нет явного подтверждения выполнения",
            "valid_json_response": "нет валидного JSON ответа модели",
        }
        return [mapping.get(item, item.replace("_", " ")) for item in items]
