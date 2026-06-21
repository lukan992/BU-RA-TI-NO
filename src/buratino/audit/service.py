"""Second-model logic audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_runner import run_json_step
from buratino.llm.json_parser import parse_audit_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import (
    AggregatedVerdict,
    AuditResult,
    ConfirmingDocumentsRelation,
    DocumentFactResult,
    DocumentPhrResult,
)
from buratino.models.domain import PhrTarget, VerificationTarget


@dataclass
class AuditService:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    audit_model: str

    def audit(
        self,
        *,
        event_target: VerificationTarget,
        phr_target: PhrTarget | None,
        aggregated_event: AggregatedVerdict,
        aggregated_phr: AggregatedVerdict,
        event_documents: list[DocumentFactResult],
        phr_documents: list[DocumentPhrResult],
        supporting_files: list[str],
        confirming_documents_relation: ConfirmingDocumentsRelation | None,
    ) -> AuditResult:
        payload = {
            "audit_mode": "consistency_check",
            "target_event_data": asdict(event_target),
            "target_phr_data": asdict(phr_target) if phr_target is not None else None,
            "aggregated_event_result": asdict(aggregated_event),
            "aggregated_phr_result": asdict(aggregated_phr),
            "document_level_event_results": [asdict(item) for item in event_documents],
            "document_level_phr_results": [asdict(item) for item in phr_documents],
            "supporting_files": supporting_files,
            "confirming_documents_relation": (
                asdict(confirming_documents_relation) if confirming_documents_relation is not None else None
            ),
        }
        logger.info("Audit LLM request started")
        result = run_json_step(
            stage="audit",
            llm_client=self.llm_client,
            prompt_loader=self.prompt_loader,
            model=self.audit_model,
            prompt_name="logic_audit.md",
            payload=payload,
            parse_result=parse_audit_result,
        ).value
        logger.info("Audit LLM result parsed")
        return result
