"""Application orchestration for one-event verification."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from loguru import logger

from buratino.audit.service import AuditService
from buratino.models.contracts import AggregatedVerdict, DocumentFactResult, DocumentPhrResult, VerificationReport
from buratino.models.domain import DocumentSummary, PhrTarget, VerificationTarget
from buratino.models.errors import NotFoundError
from buratino.repository.events import EventRepository
from buratino.repository.summaries import SummaryRepository
from buratino.report.json_writer import JsonReportWriter
from buratino.report.xlsx_exporter import XlsxReportExporter
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.aggregator import aggregate_event_results, aggregate_phr_results
from buratino.verifier.confirming_documents_relation import ConfirmingDocumentsRelationService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier


@dataclass(frozen=True)
class VerificationArtifacts:
    report: VerificationReport
    json_path: Path
    xlsx_path: Path | None


@dataclass
class VerificationApp:
    event_repository: EventRepository
    summary_repository: SummaryRepository
    target_builder: TargetBuilder
    event_verifier: EventVerifier
    phr_verifier: PhrVerifier
    audit_service: AuditService
    confirming_documents_relation_service: ConfirmingDocumentsRelationService | None = None

    def verify(
        self,
        *,
        event_id: int,
        output_dir: Path,
        primary_model: str,
        audit_model: str,
        export_xlsx: bool,
        max_documents_to_analyze: int | None = None,
    ) -> VerificationArtifacts:
        logger.info("Loading event data")
        event = self.event_repository.get_event(event_id)
        logger.info(
            "Event loaded: canonical_event_id={}, planned_value={}, unit={}",
            event.event_id,
            event.planned_value,
            event.planned_unit,
        )
        try:
            phr = self.event_repository.get_event_phr(event_id)
            logger.info("PHR loaded: name={}, target={}, unit={}", phr.phr_name, phr.phr_value_2025, phr.phr_unit)
        except NotFoundError:
            phr = None
            logger.warning("PHR is not defined for this event; PHR status will be 'не указано'")

        logger.info("Loading document summaries")
        loaded_documents = self.summary_repository.list_event_documents(event_id)
        logger.info("Loaded document summaries: count={}", len(loaded_documents))

        documents = self._limit_documents(
            self._rerank_noop(loaded_documents),
            max_documents_to_analyze,
        )
        if len(documents) != len(loaded_documents):
            logger.warning(
                "Document analysis limited: selected={} of total={}",
                len(documents),
                len(loaded_documents),
            )

        logger.info("Building verification targets")
        event_target = self.target_builder.build_event_target(event)
        logger.info("Event target built: type={}", event_target.event_type)
        phr_target = self.target_builder.build_phr_target(event, phr) if phr is not None else None
        if phr_target is not None:
            logger.info("PHR target built")

        logger.info("Running event fact document analysis")
        event_results = self.event_verifier.verify_documents(event_target, documents, model=primary_model)
        logger.info("Event fact document analysis completed: count={}", len(event_results))

        phr_results = (
            self.phr_verifier.verify_documents(phr_target, documents, model=primary_model)
            if phr_target is not None
            else []
        )
        if phr_target is not None:
            logger.info("PHR document analysis completed: count={}", len(phr_results))

        logger.info("Aggregating document-level results")
        aggregated_event = aggregate_event_results(event_results)
        aggregated_phr = (
            aggregate_phr_results(phr_results)
            if phr_target is not None
            else AggregatedVerdict(
                status="не указано",
                primary_file=None,
                reasoning=self._build_missing_phr_reasoning(),
                supporting_files=[],
            )
        )
        aggregated_event = replace(
            aggregated_event,
            reasoning=self._build_event_reasoning(
                target=event_target,
                documents=documents,
                results=event_results,
                aggregated=aggregated_event,
            ),
        )
        if phr_target is not None:
            aggregated_phr = replace(
                aggregated_phr,
                reasoning=self._build_phr_reasoning(
                    target=phr_target,
                    documents=documents,
                    results=phr_results,
                    aggregated=aggregated_phr,
                ),
            )
        logger.info(
            "Aggregation completed: event_status={}, phr_status={}",
            aggregated_event.status,
            aggregated_phr.status,
        )

        logger.info("Running logic audit")
        primary_audit = self.audit_service.audit(
            event_target=event_target,
            phr_target=phr_target,
            aggregated_event=aggregated_event,
            aggregated_phr=aggregated_phr,
            event_documents=event_results,
            phr_documents=phr_results,
        )
        logger.info("Logic audit completed: logic_is_valid={}", primary_audit.logic_is_valid)
        final_event_status = primary_audit.corrected_event_status
        final_phr_status = self._safe_phr_status(
            phr_target=phr_target,
            aggregated_phr=aggregated_phr,
            corrected_phr_status=primary_audit.corrected_phr_status,
        )

        relation = None
        relation_error = None
        if self.confirming_documents_relation_service is not None:
            relation, relation_error = self.confirming_documents_relation_service.build(
                event=event,
                documents=documents,
                event_results=event_results,
                event_fact_status=final_event_status,
                event_primary_file=aggregated_event.primary_file,
                event_supporting_files=aggregated_event.supporting_files,
                model=primary_model,
            )

        detected_errors = list(primary_audit.detected_errors)
        if relation_error is not None:
            detected_errors.append(relation_error)

        report = VerificationReport(
            event_id=event.event_id,
            event_name=event.event_name,
            event_type=event_target.event_type,
            event_fact_status=final_event_status,
            phr_fact_status=final_phr_status,
            event_primary_file=aggregated_event.primary_file,
            phr_primary_file=aggregated_phr.primary_file,
            logic_is_valid=primary_audit.logic_is_valid,
            primary_model=primary_model,
            audit_model=audit_model,
            event_reasoning=aggregated_event.reasoning,
            phr_reasoning=aggregated_phr.reasoning,
            detected_errors=detected_errors,
            event_documents=event_results,
            phr_documents=phr_results,
            supporting_files=_merge_unique(
                aggregated_event.supporting_files,
                aggregated_phr.supporting_files,
            ),
            audit_reasoning=primary_audit.corrected_reasoning,
            confirming_documents_relation=relation,
        )

        json_writer = JsonReportWriter(output_dir)
        logger.info("Writing JSON report")
        json_path = json_writer.write(report)

        xlsx_path: Path | None = None
        if export_xlsx:
            logger.info("Writing XLSX report")
            xlsx_path = XlsxReportExporter(output_dir).export(report)

        logger.info("Verification completed")
        return VerificationArtifacts(
            report=report,
            json_path=json_path,
            xlsx_path=xlsx_path,
        )

    @staticmethod
    def _rerank_noop(documents: list[DocumentSummary]) -> list[DocumentSummary]:
        return documents

    @staticmethod
    def _limit_documents(
        documents: list[DocumentSummary],
        max_documents_to_analyze: int | None,
    ) -> list[DocumentSummary]:
        if max_documents_to_analyze is None:
            return documents
        return documents[:max_documents_to_analyze]

    @staticmethod
    def _safe_phr_status(
        *,
        phr_target: PhrTarget | None,
        aggregated_phr: AggregatedVerdict,
        corrected_phr_status: str,
    ) -> str:
        if phr_target is None:
            return "не указано"
        if aggregated_phr.status != "подтверждено":
            return "не подтверждено"
        return corrected_phr_status

    def _build_event_reasoning(
        self,
        *,
        target: VerificationTarget,
        documents: list[DocumentSummary],
        results: list[DocumentFactResult],
        aggregated: AggregatedVerdict,
    ) -> str:
        document_map = {document.file_name: document for document in documents}
        reference_result = self._select_event_reference_result(results, aggregated.primary_file)
        reference_document = (
            document_map.get(reference_result.file_name) if reference_result is not None else None
        )
        if aggregated.status == "подтверждено" and reference_result is not None and reference_document is not None:
            if target.event_type == "quantitative":
                signal_sentence = (
                    f"В evidence найдены действие \"{reference_result.matched_action or 'не указано'}\", "
                    f"объект \"{reference_result.matched_subject or 'не указан'}\", "
                    f"сигнал завершения \"{reference_result.completion_signal or 'не указан'}\" "
                    f"и фактическое значение {reference_result.observed_value} "
                    f"{reference_result.observed_unit or ''}".strip()
                    + "."
                )
                decision_sentence = (
                    f"Сравнение результата определено как {reference_result.comparison_result}, "
                    f"поэтому статус мероприятия установлен как \"подтверждено\"."
                )
            else:
                signal_sentence = (
                    f"В evidence найдены действие \"{reference_result.matched_action or 'не указано'}\", "
                    f"объект \"{reference_result.matched_subject or 'не указан'}\" "
                    f"и прямой сигнал выполнения \"{reference_result.completion_signal or 'не указан'}\"."
                )
                decision_sentence = "Этого достаточно для качественного подтверждения, поэтому статус мероприятия установлен как \"подтверждено\"."
            quote_sentence = self._build_quote_sentence(reference_result.evidence_quote)
            return " ".join(
                [
                    f"Основой вывода выбран {reference_document.evidence_source} документа \"{reference_document.file_name}\".",
                    signal_sentence,
                    quote_sentence,
                    decision_sentence,
                ]
            )

        missing_signals = self._describe_missing_event_signals(target, reference_result)
        reference_sentence = self._build_reference_sentence(
            documents=documents,
            reference_document=reference_document,
        )
        quote_sentence = self._build_negative_quote_sentence(
            reference_result.evidence_quote if reference_result is not None else None
        )
        return " ".join(
            [
                reference_sentence,
                missing_signals,
                quote_sentence,
                "По правилу fail-closed статус мероприятия установлен как \"не подтверждено\".",
            ]
        )

    def _build_phr_reasoning(
        self,
        *,
        target: PhrTarget,
        documents: list[DocumentSummary],
        results: list[DocumentPhrResult],
        aggregated: AggregatedVerdict,
    ) -> str:
        document_map = {document.file_name: document for document in documents}
        reference_result = self._select_phr_reference_result(results, aggregated.primary_file)
        reference_document = (
            document_map.get(reference_result.file_name) if reference_result is not None else None
        )
        if aggregated.status == "подтверждено" and reference_result is not None and reference_document is not None:
            value_with_unit = (
                f"{reference_result.observed_value} {reference_result.observed_unit or ''}".strip()
                if reference_result.observed_value is not None
                else "не указано"
            )
            return " ".join(
                [
                    f"Основой вывода выбран {reference_document.evidence_source} документа \"{reference_document.file_name}\".",
                    f"В evidence явно подтверждены метрика \"{reference_result.metric_matched or target.phr_name}\", требуемая характеристика объекта и привязка количества к самому объекту метрики; зафиксировано значение {value_with_unit}.",
                    self._build_quote_sentence(reference_result.evidence_quote),
                    "Поэтому строгие правила ПХР выполнены, и итоговый статус установлен как \"подтверждено\".",
                ]
            )

        reference_sentence = self._build_reference_sentence(
            documents=documents,
            reference_document=reference_document,
        )
        metric_sentence = self._build_negative_phr_signal_sentence(target, reference_result)
        quote_sentence = self._build_negative_quote_sentence(
            reference_result.evidence_quote if reference_result is not None else None
        )
        return " ".join(
            [
                reference_sentence,
                metric_sentence,
                quote_sentence,
                "По правилу fail-closed статус ПХР установлен как \"не подтверждено\".",
            ]
        )

    @staticmethod
    def _build_missing_phr_reasoning() -> str:
        return "Для мероприятия ПХР не задан в исходных данных. Поэтому doc-level проверка ПХР не запускалась и документы по ПХР не анализировались. Итоговый статус ПХР установлен как \"не указано\"."

    @staticmethod
    def _select_event_reference_result(
        results: list[DocumentFactResult],
        primary_file: str | None,
    ) -> DocumentFactResult | None:
        if primary_file is not None:
            for result in results:
                if result.file_name == primary_file:
                    return result
        return results[0] if results else None

    @staticmethod
    def _select_phr_reference_result(
        results: list[DocumentPhrResult],
        primary_file: str | None,
    ) -> DocumentPhrResult | None:
        if primary_file is not None:
            for result in results:
                if result.file_name == primary_file:
                    return result
        return results[0] if results else None

    @staticmethod
    def _build_reference_sentence(
        *,
        documents: list[DocumentSummary],
        reference_document: DocumentSummary | None,
    ) -> str:
        if reference_document is not None:
            return (
                f"Проверка опиралась на {reference_document.evidence_source} документа "
                f"\"{reference_document.file_name}\"."
            )
        sources = ", ".join(sorted({document.evidence_source for document in documents})) or "evidence"
        return f"Проверка опиралась на проанализированные документы с источниками {sources}."

    @staticmethod
    def _describe_missing_event_signals(
        target: VerificationTarget,
        reference_result: DocumentFactResult | None,
    ) -> str:
        if reference_result is None:
            return "Явного подтверждающего документа не найдено, поэтому обязательные сигналы выполнения не зафиксированы."
        missing: list[str] = []
        if not reference_result.matched_action:
            missing.append("действие")
        if not reference_result.matched_subject:
            missing.append("субъект")
        if not reference_result.completion_signal:
            missing.append("сигнал завершения")
        if target.event_type == "quantitative":
            if reference_result.observed_value is None:
                missing.append("фактическое значение")
            if not reference_result.observed_unit:
                missing.append("единица измерения")
        rendered_missing = ", ".join(missing) if missing else "обязательные сигналы"
        return f"В выбранном evidence не подтверждены следующие обязательные сигналы: {rendered_missing}."

    @staticmethod
    def _build_negative_phr_signal_sentence(
        target: PhrTarget,
        reference_result: DocumentPhrResult | None,
    ) -> str:
        if reference_result is None:
            return (
                f"Для метрики \"{target.phr_name}\" не найден документ, где одновременно подтверждены "
                "характеристика объекта, принадлежность количества объекту метрики и достаточное значение."
            )
        parts: list[str] = []
        if not reference_result.metric_matched:
            parts.append("метрика не совпала")
        if not reference_result.characteristic_explicitly_matched:
            parts.append("характеристика объекта не подтверждена явно")
        if not reference_result.quantity_refers_to_metric_object:
            parts.append("количество не привязано к объекту метрики")
        if reference_result.observed_value is None:
            parts.append("фактическое значение отсутствует")
        if not reference_result.observed_unit:
            parts.append("единица измерения отсутствует")
        rendered = "; ".join(parts) if parts else "обязательные признаки ПХР не выполнены"
        return f"В выбранном evidence для метрики \"{target.phr_name}\" установлено, что {rendered}."

    @staticmethod
    def _build_quote_sentence(evidence_quote: str | None) -> str:
        if evidence_quote:
            return f"Ключевой фрагмент evidence: \"{evidence_quote}\"."
        return "В документе есть прямой фактический фрагмент, достаточный для подтверждения."

    @staticmethod
    def _build_negative_quote_sentence(evidence_quote: str | None) -> str:
        if evidence_quote:
            return f"Имеющийся фрагмент \"{evidence_quote}\" не дает прямого подтверждения выполнения."
        return "Прямой подтверждающий фрагмент в evidence не найден."


def _merge_unique(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged
