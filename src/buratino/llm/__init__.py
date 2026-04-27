"""LLM adapters and prompt helpers."""

from buratino.llm.client import LlmClient, LiteLlmClient
from buratino.llm.json_parser import (
    parse_audit_result,
    parse_event_document_result,
    parse_event_type_result,
    parse_phr_document_result,
)
from buratino.llm.prompt_loader import PromptLoader

__all__ = [
    "LlmClient",
    "LiteLlmClient",
    "PromptLoader",
    "parse_audit_result",
    "parse_event_document_result",
    "parse_event_type_result",
    "parse_phr_document_result",
]
