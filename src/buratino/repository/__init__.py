"""Repository interfaces and adapters."""

from buratino.repository.events import EventRepository, PostgresEventRepository
from buratino.repository.summaries import PostgresSummaryRepository, SummaryRepository

__all__ = [
    "EventRepository",
    "PostgresEventRepository",
    "PostgresSummaryRepository",
    "SummaryRepository",
]
