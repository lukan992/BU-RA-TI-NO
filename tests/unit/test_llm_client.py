from buratino.llm.client import is_context_overflow_error
from buratino.models.errors import RepositoryError


def test_context_overflow_detector_matches_common_provider_error() -> None:
    error = RepositoryError("LLM request failed: This model's maximum context length is 128000 tokens.")

    assert is_context_overflow_error(error) is True


def test_context_overflow_detector_matches_nested_cause() -> None:
    try:
        raise ValueError("context_length_exceeded")
    except ValueError as exc:
        error = RepositoryError("LLM request failed")
        error.__cause__ = exc

    assert is_context_overflow_error(error) is True


def test_context_overflow_detector_matches_available_context_size_error() -> None:
    error = RepositoryError(
        "LLM request failed: litellm.BadRequestError: request (180340 tokens) exceeds the available context size (131072 tokens)"
    )

    assert is_context_overflow_error(error) is True


def test_context_overflow_detector_ignores_unrelated_errors() -> None:
    error = RepositoryError("LLM request failed: temporary network issue")

    assert is_context_overflow_error(error) is False
