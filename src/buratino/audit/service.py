"""Second-model logic audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_audit_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import AggregatedVerdict, AuditResult, DocumentFactResult, DocumentPhrResult
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
    ) -> AuditResult:
        payload = {
            "audit_mode": "consistency_check",
            "target_event_data": asdict(event_target),
            "target_phr_data": asdict(phr_target) if phr_target is not None else None,
            "aggregated_event_result": asdict(aggregated_event),
            "aggregated_phr_result": asdict(aggregated_phr),
            "document_level_event_results": [asdict(item) for item in event_documents],
            "document_level_phr_results": [asdict(item) for item in phr_documents],
        }
        prompt = self.prompt_loader.render("logic_audit.md", payload)
        logger.info("Audit LLM request started")
        raw_response = self.llm_client.generate_json(model=self.audit_model, prompt=prompt)
        result = parse_audit_result(raw_response)
        logger.info("Audit LLM result parsed")
        return result
