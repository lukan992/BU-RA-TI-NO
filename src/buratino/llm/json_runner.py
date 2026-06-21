"""Shared strict-JSON generation with repair retries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from buratino.llm.client import LlmClient
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.errors import LlmOutputError, LlmStepError

ResultT = TypeVar("ResultT")

RAW_RESPONSE_PREVIEW_LIMIT = 1000
DEFAULT_JSON_REPAIR_RETRIES = 2


@dataclass(frozen=True)
class JsonStepErrorInfo:
    stage: str
    error_type: str
    raw_response_preview: str | None
    model_name: str
    prompt_name: str
    message: str


class JsonStepFailure(LlmStepError):
    def __init__(self, info: JsonStepErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


@dataclass(frozen=True)
class JsonStepResult(Generic[ResultT]):
    value: ResultT
    raw_response: str


def run_json_step(
    *,
    stage: str,
    llm_client: LlmClient,
    prompt_loader: PromptLoader,
    model: str,
    prompt_name: str,
    payload: dict[str, object],
    parse_result: Callable[[str], ResultT],
    repair_retries: int = DEFAULT_JSON_REPAIR_RETRIES,
) -> JsonStepResult[ResultT]:
    prompt = prompt_loader.render(prompt_name, payload)
    return run_prompt_json_step(
        stage=stage,
        llm_client=llm_client,
        prompt_loader=prompt_loader,
        model=model,
        prompt_name=prompt_name,
        prompt=prompt,
        parse_result=parse_result,
        repair_retries=repair_retries,
    )


def run_prompt_json_step(
    *,
    stage: str,
    llm_client: LlmClient,
    prompt_loader: PromptLoader,
    model: str,
    prompt_name: str,
    prompt: str,
    parse_result: Callable[[str], ResultT],
    repair_retries: int = DEFAULT_JSON_REPAIR_RETRIES,
) -> JsonStepResult[ResultT]:
    raw_response = _generate_and_parse(
        llm_client=llm_client,
        prompt_loader=prompt_loader,
        model=model,
        prompt_name=prompt_name,
        prompt=prompt,
        parse_result=parse_result,
        repair_retries=repair_retries,
        stage=stage,
    )
    return JsonStepResult(value=parse_result(raw_response), raw_response=raw_response)


def _generate_and_parse(
    *,
    llm_client: LlmClient,
    prompt_loader: PromptLoader,
    model: str,
    prompt_name: str,
    prompt: str,
    parse_result: Callable[[str], ResultT],
    repair_retries: int,
    stage: str,
) -> str:
    raw_response = llm_client.generate_json(model=model, prompt=prompt)
    try:
        parse_result(raw_response)
        return raw_response
    except LlmOutputError as exc:
        last_exc = exc
        last_raw = raw_response
        for _ in range(repair_retries):
            repair_prompt = prompt_loader.render(
                "json_repair.md",
                {
                    "target_prompt_name": prompt_name,
                    "original_prompt": prompt,
                    "raw_response": last_raw,
                    "validation_error": str(last_exc),
                },
            )
            repaired_raw = llm_client.generate_json(model=model, prompt=repair_prompt)
            try:
                parse_result(repaired_raw)
                return repaired_raw
            except LlmOutputError as repair_exc:
                last_exc = repair_exc
                last_raw = repaired_raw
        raise JsonStepFailure(
            JsonStepErrorInfo(
                stage=stage,
                error_type=_classify_output_error(last_exc, last_raw),
                raw_response_preview=_preview(last_raw),
                model_name=model,
                prompt_name=prompt_name,
                message=str(last_exc),
            )
        ) from last_exc


def _classify_output_error(exc: Exception, raw_response: str | None) -> str:
    rendered = str(exc).lower()
    if raw_response is not None and not raw_response.strip():
        return "empty_response"
    if "malformed json" in rendered:
        return "malformed_json"
    if "schema mismatch" in rendered:
        return "schema_mismatch"
    if "must be a json object" in rendered:
        return "non_object_json"
    return "invalid_llm_output"


def _preview(raw_response: str | None) -> str | None:
    if raw_response is None:
        return None
    stripped = raw_response.strip()
    if not stripped:
        return ""
    return stripped[:RAW_RESPONSE_PREVIEW_LIMIT]
