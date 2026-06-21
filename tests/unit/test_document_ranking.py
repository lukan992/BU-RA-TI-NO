from __future__ import annotations

import json
from pathlib import Path

import pytest

from buratino.llm.json_parser import parse_document_ranking_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, VerificationTarget
from buratino.models.errors import LlmOutputError, RepositoryError
from buratino.verifier.document_ranking import DocumentRankingService
from conftest import create_prompt_assets


class FakeLlmClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_json(self, *, model: str, prompt: str) -> str:
        return self.response


class SequencedLlmClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _ranking_payload(*items: dict[str, object]) -> str:
    return json.dumps({"ranked_documents": list(items)})


def test_parse_document_ranking_result_accepts_valid_payload() -> None:
    payload = """
    {
      "ranked_documents": [
        {
          "doc_id": "doc-1",
          "score": 10,
          "reason_codes": ["event_completion_candidate"],
          "short_reason": "Most relevant summary."
        }
      ]
    }
    """

    result = parse_document_ranking_result(payload)

    assert result[0].document_id == "doc-1"
    assert result[0].score == 10


def test_parse_document_ranking_result_rejects_extra_keys() -> None:
    payload = """
    {
      "ranked_documents": [
        {
          "doc_id": "doc-1",
          "score": 10,
          "reason_codes": ["event_completion_candidate"],
          "short_reason": "Most relevant summary.",
          "extra": "bad"
        }
      ]
    }
    """

    with pytest.raises(LlmOutputError, match="Ranking document schema mismatch"):
        parse_document_ranking_result(payload)


def test_document_ranking_service_selects_documents_in_score_order(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    service = DocumentRankingService(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=FakeLlmClient(
            _ranking_payload(
                {
                    "doc_id": "doc-2",
                    "score": 20,
                    "reason_codes": ["event_completion_candidate"],
                    "short_reason": "Best match.",
                },
                {
                    "doc_id": "doc-1",
                    "score": 10,
                    "reason_codes": ["mentions_target_object"],
                    "short_reason": "Second match.",
                },
            )
        ),
        ranking_model="ranking",
    )

    ranked = service.rank_documents(
        event_target=_target(),
        phr_target=None,
        documents=_documents(),
        limit=2,
    )

    assert [document.file_name for document in ranked] == ["b.pdf", "a.pdf"]


def test_document_ranking_service_rejects_unknown_document(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    service = DocumentRankingService(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=FakeLlmClient(
            _ranking_payload(
                {
                    "doc_id": "doc-x",
                    "score": 10,
                    "reason_codes": ["event_completion_candidate"],
                    "short_reason": "Unknown doc.",
                }
            )
        ),
        ranking_model="ranking",
    )

    with pytest.raises(LlmOutputError, match="Ranking selected unknown document"):
        service.rank_documents(
            event_target=_target(),
            phr_target=None,
            documents=_documents()[:2],
            limit=1,
        )


def test_document_ranking_service_recovers_from_context_overflow_with_grouped_ranking(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    service = DocumentRankingService(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=SequencedLlmClient(
            [
                RepositoryError("LLM request failed: maximum context length exceeded"),
                _ranking_payload(
                    {
                        "doc_id": "doc-1",
                        "score": 10,
                        "reason_codes": ["event_completion_candidate"],
                        "short_reason": "group 1",
                    }
                ),
                _ranking_payload(
                    {
                        "doc_id": "doc-3",
                        "score": 9,
                        "reason_codes": ["event_completion_candidate"],
                        "short_reason": "group 2",
                    }
                ),
            ]
        ),
        ranking_model="ranking",
        batch_size=2,
        summary_max_chars=5,
    )

    ranked = service.rank_documents(
        event_target=_target(),
        phr_target=None,
        documents=_documents(),
        limit=2,
    )

    assert [document.file_name for document in ranked] == ["a.pdf", "c.pdf"]


def test_document_ranking_service_returns_debug_lists(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    service = DocumentRankingService(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=FakeLlmClient(
            _ranking_payload(
                {
                    "doc_id": "doc-2",
                    "score": 20,
                    "reason_codes": ["event_completion_candidate"],
                    "short_reason": "Best match.",
                }
            )
        ),
        ranking_model="ranking",
    )

    ranked, debug, error = service.rank_documents_with_debug(
        event_target=_target(),
        phr_target=None,
        documents=_documents(),
        limit=1,
    )

    assert [document.file_name for document in ranked] == ["b.pdf"]
    assert debug.total_docs == 3
    assert debug.ranking_enabled is True
    assert debug.selected_doc_ids == ["doc-2"]
    assert debug.selected_file_names == ["b.pdf"]
    assert debug.rejected_file_names == ["a.pdf", "c.pdf"]
    assert error is None


def _target() -> VerificationTarget:
    return VerificationTarget(
        event_id=1,
        event_name="Event",
        event_description="Description",
        event_type="qualitative",
        normalized_action="Act",
        normalized_subject="Subject",
        planned_value=0,
        planned_unit="шт",
    )


def _documents() -> list[DocumentSummary]:
    return [
        DocumentSummary("doc-1", "a.pdf", "ocr-1", "ocr", summary_text="summary 1"),
        DocumentSummary("doc-2", "b.pdf", "ocr-2", "ocr", summary_text="summary 2"),
        DocumentSummary("doc-3", "c.pdf", "ocr-3", "ocr", summary_text="summary 3"),
    ]
