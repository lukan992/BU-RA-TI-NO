"""Domain-specific exceptions."""


class BuratinoError(Exception):
    """Base application exception."""


class NotFoundError(BuratinoError):
    """Raised when a required domain entity is absent."""


class DataContractError(BuratinoError):
    """Raised when required DB fields or runtime data are absent."""


class RepositoryError(BuratinoError):
    """Raised for repository and storage access problems."""


class ValidationError(BuratinoError):
    """Raised when user input or derived runtime input is invalid."""


class LlmOutputError(BuratinoError):
    """Raised when an LLM response is missing, malformed, or violates schema."""
