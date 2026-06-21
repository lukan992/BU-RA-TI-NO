"""LLM-based document ranking before detailed analysis."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

from loguru import logger

from buratino.llm.json_runner import JsonStepFailure, JsonStepErrorInfo, run_json_step
from buratino.llm.client import is_context_overflow_error
from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_document_ranking_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import RankedDocument, RankingDebugInfo
from buratino.models.domain import DocumentSummary, PhrTarget, VerificationTarget
from buratino.models.errors import LlmOutputError, RepositoryError


@dataclass
class DocumentRankingService:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    ranking_model: str
    batch_size: int = 5
    summary_max_chars: int = 6000

    def rank_documents(
        self,
        *,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
        documents: list[DocumentSummary],
        limit: int,
        model: str | None = None,
    ) -> list[DocumentSummary]:
        ranked, _, _ = self.rank_documents_with_debug(
            event_target=event_target,
            phr_target=phr_target,
            documents=documents,
            limit=limit,
            model=model,
        )
        return ranked

    def rank_documents_with_debug(
        self,
        *,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
        documents: list[DocumentSummary],
        limit: int,
        model: str | None = None,
    ) -> tuple[list[DocumentSummary], RankingDebugInfo, JsonStepErrorInfo | None]:
        if len(documents) <= limit:
            return documents, RankingDebugInfo(
                total_docs=len(documents),
                ranking_enabled=False,
                ranking_limit=limit,
                selected_doc_ids=[document.document_id for document in documents if document.document_id is not None],
                selected_file_names=[document.file_name for document in documents],
                rejected_file_names=[],
            ), None

        logger.info("Running document ranking: total={} limit={}", len(documents), limit)
        try:
            ranked = self._rank_documents_once(
                event_target=event_target,
                phr_target=phr_target,
                documents=documents,
                limit=limit,
                model=model,
                summary_max_chars=None,
            )
        except RepositoryError as exc:
            if not is_context_overflow_error(exc):
                raise
            logger.warning(
                "Document ranking overflow: event_id={} total_documents={}; retrying with grouped ranking",
                event_target.event_id,
                len(documents),
            )
            ranked = self._rank_documents_grouped(
                event_target=event_target,
                phr_target=phr_target,
                documents=documents,
                limit=limit,
                model=model,
            )
        except JsonStepFailure as exc:
            logger.warning(
                "Document ranking returned invalid JSON after retries: event_id={} error_type={}",
                event_target.event_id,
                exc.info.error_type,
            )
            selected = self._limit_documents(documents, limit)
            return selected, self._build_debug(documents=documents, selected=selected, limit=limit, ranking_enabled=True), exc.info
        selected = self._select_ranked_documents(documents=documents, ranked=ranked, limit=limit)
        return selected, self._build_debug(documents=documents, selected=selected, limit=limit, ranking_enabled=True), None

    def _rank_documents_once(
        self,
        *,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
        documents: list[DocumentSummary],
        limit: int,
        model: str | None,
        summary_max_chars: int | None,
    ) -> list[RankedDocument]:
        payload = {
            "event_id": event_target.event_id,
            "event_name": event_target.event_name,
            "event_description": event_target.event_description,
            "planned_value": event_target.planned_value,
            "planned_unit": event_target.planned_unit,
            "event_type": event_target.event_type,
            "phr_name": phr_target.phr_name if phr_target is not None else None,
            "phr_value_2025": phr_target.phr_value_2025 if phr_target is not None else None,
            "phr_unit": phr_target.phr_unit if phr_target is not None else None,
            "selection_limit": limit,
            "documents": [
                {
                    "document_id": document.document_id,
                    "file_name": document.file_name,
                    "summary_text": self._limit_summary(document.summary_text, summary_max_chars),
                }
                for document in documents
            ],
        }
        return run_json_step(
            stage="ranking",
            llm_client=self.llm_client,
            prompt_loader=self.prompt_loader,
            model=model or self.ranking_model,
            prompt_name="document_ranking.md",
            payload=payload,
            parse_result=parse_document_ranking_result,
        ).value

    def _rank_documents_grouped(
        self,
        *,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
        documents: list[DocumentSummary],
        limit: int,
        model: str | None,
    ) -> list[RankedDocument]:
        candidates: list[DocumentSummary] = []
        seen: set[tuple[str | None, str]] = set()
        for group in _batched(documents, self.batch_size):
            group_limit = min(limit, len(group))
            ranked_group = self._rank_documents_once(
                event_target=event_target,
                phr_target=phr_target,
                documents=group,
                limit=group_limit,
                model=model,
                summary_max_chars=self.summary_max_chars,
            )
            selected_group = self._select_ranked_documents(documents=group, ranked=ranked_group, limit=group_limit)
            for document in selected_group:
                identity = (document.document_id, document.file_name)
                if identity not in seen:
                    seen.add(identity)
                    candidates.append(document)

        if len(candidates) <= limit:
            return [
                RankedDocument(
                    document_id=document.document_id,
                    file_name=document.file_name,
                    rank=index,
                    reasoning="Selected by grouped ranking fallback.",
                    score=max(limit - index + 1, 0),
                    reason_codes=["grouped_ranking_fallback"],
                    short_reason="Selected by grouped ranking fallback.",
                )
                for index, document in enumerate(candidates, start=1)
            ]

        try:
            return self._rank_documents_once(
                event_target=event_target,
                phr_target=phr_target,
                documents=candidates,
                limit=limit,
                model=model,
                summary_max_chars=self.summary_max_chars,
            )
        except RepositoryError as exc:
            if not is_context_overflow_error(exc):
                raise
            narrowed_candidates = candidates[: max(limit, self.batch_size)]
            return self._rank_documents_once(
                event_target=event_target,
                phr_target=phr_target,
                documents=narrowed_candidates,
                limit=limit,
                model=model,
                summary_max_chars=self.summary_max_chars,
            )

    @staticmethod
    def _limit_summary(summary_text: str | None, max_chars: int | None) -> str | None:
        if summary_text is None or max_chars is None or len(summary_text) <= max_chars:
            return summary_text
        return summary_text[:max_chars]

    @staticmethod
    def _select_ranked_documents(
        *,
        documents: list[DocumentSummary],
        ranked: list[RankedDocument],
        limit: int,
    ) -> list[DocumentSummary]:
        if len(ranked) > limit:
            raise LlmOutputError(
                f"Ranking returned {len(ranked)} documents, which exceeds selection_limit={limit}."
            )

        available = {(document.document_id, document.file_name): document for document in documents}
        documents_by_id: dict[str, list[DocumentSummary]] = {}
        for document in documents:
            if document.document_id is not None:
                documents_by_id.setdefault(document.document_id, []).append(document)
        ranked_sorted = sorted(
            enumerate(ranked, start=1),
            key=lambda item: (-item[1].score, item[0]),
        )
        selected: list[DocumentSummary] = []
        seen: set[tuple[str | None, str]] = set()
        for rank, item in ranked_sorted:
            if item.document_id is None:
                raise LlmOutputError("Ranking selected document without doc_id.")
            item = RankedDocument(
                document_id=item.document_id,
                file_name=item.file_name,
                rank=rank,
                reasoning=item.reasoning,
                score=item.score,
                reason_codes=item.reason_codes,
                short_reason=item.short_reason,
            )
            resolved_document = available.get((item.document_id, item.file_name))
            if resolved_document is None and item.document_id is not None:
                matched_by_id = documents_by_id.get(item.document_id, [])
                if len(matched_by_id) == 1:
                    resolved_document = matched_by_id[0]
                    logger.warning(
                        "Ranking file_name mismatch for document_id={}: model_file_name={!r}, actual_file_name={!r}",
                        item.document_id,
                        item.file_name,
                        resolved_document.file_name,
                    )
            if resolved_document is None:
                raise LlmOutputError(
                    f"Ranking selected unknown document: document_id={item.document_id!r}, file_name={item.file_name!r}."
                )
            identity = (resolved_document.document_id, resolved_document.file_name)
            if identity in seen:
                raise LlmOutputError("Ranking returned duplicate documents.")
            selected.append(resolved_document)
            seen.add(identity)
        logger.info(
            "Document ranking selected: {}",
            ", ".join(document.file_name for document in selected),
        )
        return selected

    @staticmethod
    def _build_debug(
        *,
        documents: list[DocumentSummary],
        selected: list[DocumentSummary],
        limit: int,
        ranking_enabled: bool,
    ) -> RankingDebugInfo:
        selected_identities = {(document.document_id, document.file_name) for document in selected}
        return RankingDebugInfo(
            total_docs=len(documents),
            ranking_enabled=ranking_enabled,
            ranking_limit=limit,
            selected_doc_ids=[document.document_id for document in selected if document.document_id is not None],
            selected_file_names=[document.file_name for document in selected],
            rejected_file_names=[
                document.file_name
                for document in documents
                if (document.document_id, document.file_name) not in selected_identities
            ],
        )

    @staticmethod
    def _limit_documents(documents: list[DocumentSummary], limit: int) -> list[DocumentSummary]:
        return documents[:limit]


def _batched(items: list[DocumentSummary], batch_size: int) -> list[list[DocumentSummary]]:
    iterator = iter(items)
    batches: list[list[DocumentSummary]] = []
    while batch := list(islice(iterator, batch_size)):
        batches.append(batch)
    return batches
