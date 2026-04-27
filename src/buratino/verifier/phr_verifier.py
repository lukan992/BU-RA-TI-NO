"""Doc-level PHR verification."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_phr_document_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import DocumentPhrResult
from buratino.models.domain import DocumentSummary, PhrTarget


@dataclass
class PhrVerifier:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    primary_model: str

    def verify_documents(
        self,
        target: PhrTarget,
        documents: list[DocumentSummary],
        *,
        model: str | None = None,
    ) -> list[DocumentPhrResult]:
        llm_model = model or self.primary_model
        results: list[DocumentPhrResult] = []
        for index, document in enumerate(documents, start=1):
            logger.info(
                "PHR LLM analysis: document {}/{} file={} source={}",
                index,
                len(documents),
                document.file_name,
                document.evidence_source,
            )
            payload = {
                "event_id": target.event_id,
                "event_name": target.event_name,
                "phr_name": target.phr_name,
                "phr_value_2025": target.phr_value_2025,
                "phr_unit": target.phr_unit,
                "document_id": document.document_id,
                "file_name": document.file_name,
                "evidence_source": document.evidence_source,
                "evidence_text": document.evidence_text,
            }
            prompt = self.prompt_loader.render("phr_fact_summary.md", payload)
            raw_response = self.llm_client.generate_json(model=llm_model, prompt=prompt)
            result = parse_phr_document_result(raw_response)
            logger.info(
                "PHR LLM result: document {}/{} status={} comparison={}",
                index,
                len(documents),
                result.phr_fact_status,
                result.comparison_result,
            )
            results.append(result)
        return results
