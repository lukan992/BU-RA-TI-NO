"""Repository interfaces and adapters."""

from buratino.repository.events import EventRepository, PostgresEventRepository
from buratino.repository.analysis_results import BuratinoEventAnalysisResultRepository
from buratino.repository.jobs import BuratinoAnalysisJobRepository
from buratino.repository.summaries import PostgresSummaryRepository, SummaryRepository

__all__ = [
    "BuratinoAnalysisJobRepository",
    "BuratinoEventAnalysisResultRepository",
    "EventRepository",
    "PostgresEventRepository",
    "PostgresSummaryRepository",
    "SummaryRepository",
]
