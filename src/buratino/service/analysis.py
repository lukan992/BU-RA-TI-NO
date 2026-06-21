"""Core OCR-only analysis service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from buratino import __version__
from buratino.models.contracts import AggregatedVerdict, DocumentFactResult, DocumentPhrResult, RankingDebugInfo
from buratino.models.domain import FileEvidence, PhrRecord, PhrTarget, VerificationTarget
from buratino.models.errors import NotFoundError
from buratino.models.result_contract import (
    BuratinoResult,
    ResultDiagnostics,
    ResultExpected,
    ResultFacts,
    ResultModelInfo,
    ResultStatuses,
    validate_result_json,
)
from buratino.repository.events import EventRepository
from buratino.repository.summaries import SummaryRepository
from buratino.service.result_mapping import (
    build_evidence_items_for_event,
    build_evidence_items_for_phr,
    build_supporting_file_entry,
    dataclass_list_to_json,
    lower_verdict_to_business_status,
    plan_check_applies,
    quantitative_event_is_confirmed,
    stringify_expected_plan,
    stringify_observed_plan,
    summarize_supporting_reason,
)
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.aggregator import aggregate_phr_results, select_phr_supporting_results
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier


@dataclass
class BuratinoAnalysisService:
    event_repository: EventRepository
    summary_repository: SummaryRepository
    target_builder: TargetBuilder
    document_ranking_service: DocumentRankingService
    event_verifier: EventVerifier
    phr_verifier: PhrVerifier
    primary_model: str
    ranking_model: str | None
    audit_model: str | None
    ranking_enabled: bool = False
    audit_enabled: bool = False
    date_check_enabled: bool = False
    summary_verdict_enabled: bool = False
    pipeline_version: str = __version__

    def analyze_event(
        self,
        event_id: int,
        *,
        job_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        result_value_id = _optional_int(payload.get("result_value_id"))
        logger.info("analysis started event_id={} result_value_id={} job_id={}", event_id, result_value_id, job_id)

        logger.info("Loading event and PHR for OCR-only analysis")
        event = self.event_repository.get_event(event_id)
        logger.info(
            "loaded event: event_name={} planned_value={} measurement_unit={}",
            event.event_name,
            event.planned_value,
            event.planned_unit,
        )
        try:
            phr = self.event_repository.get_event_phr(event_id)
        except NotFoundError:
            phr = None
        logger.info("loaded phr existence={}", phr is not None)

        logger.info("Loading linked documents")
        file_evidence = self.summary_repository.list_file_evidence(event_id)
        event_target = self.target_builder.build_event_target(event)
        phr_auto_confirmed = phr is not None and phr.phr_value_2025 == 0
        phr_target = self._build_phr_target(event_id=event.event_id, event_name=event.event_name, phr=phr, phr_auto_confirmed=phr_auto_confirmed, event=event)

        ocr_documents = [item for item in file_evidence if item.ocr_text or item.ocr_parts]
        skipped_files = [item.file_name for item in file_evidence if not (item.ocr_text or item.ocr_parts)]
        analyzed_documents = [self._to_document_summary(item) for item in ocr_documents]
        ocr_chunks_count = sum(len(item.ocr_parts) if item.ocr_parts else 1 for item in ocr_documents)
        logger.info("loaded documents count={}", len(file_evidence))
        logger.info("documents with OCR count={}", len(ocr_documents))
        logger.info("documents without OCR count={}", len(skipped_files))
        logger.info("OCR chunks count={}", ocr_chunks_count)
        logger.info("summary verdict disabled={}", not self.summary_verdict_enabled)
        logger.info("date check disabled={}", not self.date_check_enabled)
        logger.info("audit disabled={}", not self.audit_enabled)
        logger.info("ranking disabled={}", not self.ranking_enabled)
        for index, item in enumerate(ocr_documents, start=1):
            logger.debug(
                "ocr document {}/{} file={} ocr_length={} preview={}",
                index,
                len(ocr_documents),
                item.file_name,
                len(item.ocr_text or ""),
                self._short_preview(item.ocr_text or ""),
            )

        ranking_debug = RankingDebugInfo(
            total_docs=len(file_evidence),
            ranking_enabled=False,
            ranking_limit=None,
            selected_doc_ids=[item.document_id for item in analyzed_documents if item.document_id is not None],
            selected_file_names=[item.file_name for item in analyzed_documents],
            rejected_file_names=skipped_files,
        )

        if self.ranking_enabled and analyzed_documents:
            analyzed_documents, ranking_debug, _ = self._rank_documents(
                analyzed_documents=analyzed_documents,
                event_target=event_target,
                phr_target=phr_target,
            )

        event_results: list[DocumentFactResult]
        phr_results: list[DocumentPhrResult]
        if analyzed_documents:
            logger.info("primary model call started model={}", self.primary_model)
            event_results, _ = self.event_verifier.verify_documents(event_target, analyzed_documents, model=self.primary_model)
            phr_results = []
            if phr_target is not None and not phr_auto_confirmed:
                phr_results, _ = self.phr_verifier.verify_documents(phr_target, analyzed_documents, model=self.primary_model)
            logger.info("primary model call finished model={}", self.primary_model)
        else:
            event_results = []
            phr_results = []

        result = self._build_result(
            event=event,
            phr=phr,
            event_target=event_target,
            phr_target=phr_target,
            phr_auto_confirmed=phr_auto_confirmed,
            file_evidence=file_evidence,
            analyzed_documents=analyzed_documents,
            event_results=event_results,
            phr_results=phr_results,
            skipped_files=skipped_files,
            ranking_debug=ranking_debug,
            payload=payload,
        )
        logger.info("doc-level confirmed files={}", [item["filename"] for item in result["supporting_files"]])
        logger.info("event_description_status={}", result["statuses"]["event_description_status"])
        logger.info("plan_status={}", result["statuses"]["plan_status"])
        logger.info("phr_status={}", result["statuses"]["phr_status"])
        logger.info("supporting_files count={}", len(result["supporting_files"]))
        logger.info("diagnostic_reason={}", result["diagnostics"]["diagnostic_reason"])
        validate_result_json(result)
        return result

    def _build_result(
        self,
        *,
        event,
        phr: PhrRecord | None,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
        phr_auto_confirmed: bool,
        file_evidence: list[FileEvidence],
        analyzed_documents,
        event_results: list[DocumentFactResult],
        phr_results: list[DocumentPhrResult],
        skipped_files: list[str],
        ranking_debug: RankingDebugInfo,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del ranking_debug
        plan_applicable = plan_check_applies(event_target)
        event_support = [
            result for result in event_results if quantitative_event_is_confirmed(result, event_target)
        ]
        event_reference = event_support[0] if event_support else None

        if plan_applicable:
            # planned_value present in xlsx: the event is confirmed only when the
            # plan is confirmed, and plan_status can never be "Не применимо".
            if event_reference is not None:
                event_status = "Подтверждено"
                plan_status = "Подтверждено"
            else:
                event_status = "Не подтверждено"
                plan_status = "Не подтверждено"
        else:
            # qualitative event (no positive planned_value): no plan to verify.
            event_status = "Подтверждено" if event_reference is not None else "Не подтверждено"
            plan_status = "Не применимо"

        if phr_auto_confirmed:
            phr_status = "Подтверждено"
            phr_reference = None
        elif phr_target is None:
            phr_status = "Не применимо"
            phr_reference = None
        else:
            phr_confirmed = select_phr_supporting_results(phr_results)
            phr_reference = phr_confirmed[0] if phr_confirmed else None
            phr_status = lower_verdict_to_business_status(
                aggregate_phr_results(phr_results).status,
                not_applicable=False,
            )

        if not analyzed_documents:
            diagnostic_reason = "OCR отсутствует"
        elif event_status == "Подтверждено" or phr_status == "Подтверждено":
            diagnostic_reason = "Найдено OCR-подтверждение."
        elif plan_applicable:
            diagnostic_reason = self._quantitative_negative_diagnostic(
                event_results=event_results,
                event_target=event_target,
            )
        else:
            diagnostic_reason = "OCR проанализирован, подтверждение не найдено."

        evidence_items = []
        supporting_files = []
        if event_reference is not None:
            supporting_files.append(
                build_supporting_file_entry(
                    document_id=event_reference.document_id,
                    filename=event_reference.file_name,
                    reason=summarize_supporting_reason(event_reference),
                )
            )
            evidence_items.extend(
                build_evidence_items_for_event(
                    event_reference,
                    include_plan=plan_applicable,
                )
            )
        if phr_reference is not None and phr_reference.file_name not in {item.filename for item in supporting_files}:
            supporting_files.append(
                build_supporting_file_entry(
                    document_id=phr_reference.document_id,
                    filename=phr_reference.file_name,
                    reason=summarize_supporting_reason(phr_reference),
                )
            )
        if phr_reference is not None:
            evidence_items.extend(build_evidence_items_for_phr(phr_reference))

        result = BuratinoResult(
            pipeline_name="buratino",
            pipeline_version=self.pipeline_version,
            event_id=event.event_id,
            report_id=_optional_int(payload.get("report_id")),
            result_value_id=_optional_int(payload.get("result_value_id")),
            event_name=event.event_name,
            statuses=ResultStatuses(
                event_description_status=event_status,
                phr_status=phr_status,
                plan_status=plan_status,
            ),
            expected=ResultExpected(
                event_description=event.event_description or event.event_name,
                phr=phr.phr_name if phr is not None else None,
                plan=stringify_expected_plan(event_target),
            ),
            facts=ResultFacts(
                event_description_fact=event_reference.evidence_quote if event_reference is not None else None,
                phr_fact=phr_reference.evidence_quote if phr_reference is not None else None,
                plan_fact=stringify_observed_plan(event_reference),
            ),
            supporting_files=supporting_files,
            evidence_items=evidence_items,
            diagnostics=ResultDiagnostics(
                evidence_source_used="ocr",
                ocr_available=bool(analyzed_documents),
                analyzed_files=[item.file_name for item in analyzed_documents],
                skipped_files=skipped_files,
                diagnostic_reason=diagnostic_reason,
            ),
            model_info=ResultModelInfo(
                primary_model=self.primary_model,
                ranking_model=self.ranking_model if self.ranking_enabled else None,
                audit_model=self.audit_model if self.audit_enabled else None,
            ),
        )
        return result.to_dict()

    def _quantitative_negative_diagnostic(self, *, event_results, event_target: VerificationTarget) -> str:
        below_target = next(
            (
                result
                for result in event_results
                if result.comparison_result == "below_target" and result.observed_value is not None
            ),
            None,
        )
        if below_target is not None:
            observed = below_target.observed_value
            observed_unit = below_target.observed_unit or event_target.planned_unit or ""
            planned_value = self._format_number(event_target.planned_value)
            planned_unit = event_target.planned_unit or ""
            return (
                f"OCR подтверждает факт выполнения, но найдено {observed} {observed_unit}".strip()
                + f", что ниже плана {planned_value} {planned_unit}."
            )

        semantic_only = next(
            (
                result
                for result in event_results
                if result.completion_signal or result.matched_action or result.matched_subject
            ),
            None,
        )
        if semantic_only is not None:
            planned_value = self._format_number(event_target.planned_value)
            planned_unit = event_target.planned_unit or ""
            return (
                "OCR подтверждает только смысл выполнения, "
                f"но не доказывает достижение планового значения {planned_value} {planned_unit}."
            )

        return "OCR проанализирован, количественное подтверждение не найдено."

    def _rank_documents(
        self,
        *,
        analyzed_documents,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
    ):
        if not self.ranking_enabled:
            return analyzed_documents, RankingDebugInfo(
                total_docs=len(analyzed_documents),
                ranking_enabled=False,
                ranking_limit=None,
                selected_doc_ids=[item.document_id for item in analyzed_documents if item.document_id is not None],
                selected_file_names=[item.file_name for item in analyzed_documents],
                rejected_file_names=[],
            ), None
        return self.document_ranking_service.rank_documents_with_debug(
            event_target=event_target,
            phr_target=phr_target,
            documents=analyzed_documents,
            limit=len(analyzed_documents),
            model=self.ranking_model or self.primary_model,
        )

    def _build_phr_target(
        self,
        *,
        event_id: int,
        event_name: str,
        phr: PhrRecord | None,
        phr_auto_confirmed: bool,
        event,
    ) -> PhrTarget | None:
        if phr is None:
            return None
        if phr_auto_confirmed:
            return PhrTarget(
                event_id=event_id,
                event_name=event_name,
                phr_name=phr.phr_name,
                phr_value_2025=phr.phr_value_2025,
                phr_unit=phr.phr_unit,
            )
        return self.target_builder.build_phr_target(event, phr)

    @staticmethod
    def _to_document_summary(item: FileEvidence):
        from buratino.models.domain import DocumentSummary

        ocr_text = item.ocr_text or ""
        return DocumentSummary(
            document_id=item.document_id,
            file_name=item.file_name,
            evidence_text=ocr_text,
            evidence_source="ocr",
            source_table=item.source_table,
            ocr_text=item.ocr_text,
            summary_text=item.summary_text,
            ocr_parts=item.ocr_parts,
        )

    @staticmethod
    def _format_number(value: float | None) -> str:
        if value is None:
            return "null"
        if value.is_integer():
            return str(int(value))
        return str(value)

    @staticmethod
    def _short_preview(text: str) -> str | None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return None
        return cleaned[:300]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    rendered = str(value).strip()
    if not rendered:
        return None
    return int(rendered)
