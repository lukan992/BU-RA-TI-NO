"""Doc-level event verification."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_event_document_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import DocumentFactResult
from buratino.models.domain import DocumentSummary, VerificationTarget


@dataclass
class EventVerifier:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    primary_model: str

    def verify_documents(
        self,
        target: VerificationTarget,
        documents: list[DocumentSummary],
        *,
        model: str | None = None,
    ) -> list[DocumentFactResult]:
        llm_model = model or self.primary_model
        results: list[DocumentFactResult] = []
        for index, document in enumerate(documents, start=1):
            logger.info(
                "Event LLM analysis: document {}/{} file={} source={}",
                index,
                len(documents),
                document.file_name,
                document.evidence_source,
            )
            payload = {
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
            prompt = self.prompt_loader.render("event_fact_summary.md", payload)
            raw_response = self.llm_client.generate_json(model=llm_model, prompt=prompt)
            result = parse_event_document_result(raw_response)
            logger.info(
                "Event LLM result: document {}/{} status={} comparison={}",
                index,
                len(documents),
                result.fact_status,
                result.comparison_result,
            )
            results.append(result)
        return results
