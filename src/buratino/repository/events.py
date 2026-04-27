"""Event and PHR PostgreSQL repositories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from buratino.models.domain import EventRecord, PhrRecord
from buratino.models.errors import DataContractError, NotFoundError
from buratino.repository._postgres import (
    PostgresIntrospector,
    first_matching_column,
    quote_ident,
)

EVENT_ID_CANDIDATES = ("event_id", "ИД мероприятия", "идмероприятия", "id")
RESULT_VALUE_ID_CANDIDATES = ("result_value_id", "ИД значения результата", "идзначениярезультата")
EVENT_NAME_CANDIDATES = ("event_name", "Наименование мероприятия", "мероприятие", "name")
EVENT_DESCRIPTION_CANDIDATES = (
    "event_description",
    "characteristic_description",
    "Описание мероприятия",
    "характеристика мероприятия",
    "описание",
    "description",
)
PLANNED_VALUE_CANDIDATES = (
    "planned_value",
    "Плановое значение",
    "Плановое значение результата",
    "значение",
)
PLANNED_UNIT_CANDIDATES = (
    "planned_unit",
    "measurement_unit",
    "Единица измерения",
    "Ед. изм.",
    "unit",
)
PHR_NAME_CANDIDATES = (
    "phr_name",
    "Наименование ПХР",
    "Наименование показателя",
    "показатель",
)
PHR_VALUE_CANDIDATES = (
    "phr_value_2025",
    "Значение 2025",
    "План 2025",
    "значение",
)
PHR_UNIT_CANDIDATES = (
    "phr_unit",
    "measurement_unit",
    "planned_unit",
    "Единица измерения",
    "Ед. изм.",
    "unit",
)


class EventRepository(Protocol):
    def get_event(self, event_id: int) -> EventRecord:
        """Load one event by id."""

    def get_event_phr(self, event_id: int) -> PhrRecord:
        """Load one PHR record by event id."""


@dataclass
class PostgresEventRepository:
    """PostgreSQL adapter for event-related data."""

    dsn: str
    schema: str = "public"
    event_table: str = "xlsx_events"
    phr_table: str = "xlsx_event_phr"

    def __post_init__(self) -> None:
        self._inspector = PostgresIntrospector(self.dsn, self.schema)

    def get_event(self, event_id: int) -> EventRecord:
        columns = self._inspector.list_columns(self.event_table)
        if not columns:
            raise DataContractError(
                f"Required table is missing or inaccessible: {self.schema}.{self.event_table}"
            )

        event_id_column = first_matching_column(columns, EVENT_ID_CANDIDATES)
        result_value_id_column = first_matching_column(columns, RESULT_VALUE_ID_CANDIDATES)
        name_column = first_matching_column(columns, EVENT_NAME_CANDIDATES)
        description_column = first_matching_column(columns, EVENT_DESCRIPTION_CANDIDATES)
        planned_value_column = first_matching_column(columns, PLANNED_VALUE_CANDIDATES)
        planned_unit_column = first_matching_column(columns, PLANNED_UNIT_CANDIDATES)

        if event_id_column is None or name_column is None:
            raise DataContractError(
                f"Table {self.schema}.{self.event_table} does not expose event identity columns."
            )
        if planned_value_column is None or planned_unit_column is None:
            raise DataContractError(
                f"Table {self.schema}.{self.event_table} does not expose planned value columns."
            )

        select_parts = [
            f"{quote_ident(event_id_column)} AS event_id",
            f"{quote_ident(name_column)} AS event_name",
            (
                f"{quote_ident(description_column)} AS event_description"
                if description_column is not None
                else "NULL AS event_description"
            ),
            f"{quote_ident(planned_value_column)} AS planned_value",
            f"{quote_ident(planned_unit_column)} AS planned_unit",
        ]
        query = f"""
            SELECT {", ".join(select_parts)}
            FROM {quote_ident(self.schema)}.{quote_ident(self.event_table)}
            WHERE {self._event_lookup_condition(event_id_column, result_value_id_column)}
            LIMIT 1
        """
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, self._event_lookup_params(event_id, result_value_id_column))
            row = cursor.fetchone()

        if row is None:
            raise NotFoundError(f"Event not found: {event_id}")

        return EventRecord(
            event_id=int(row["event_id"]),
            event_name=str(row["event_name"]).strip(),
            event_description=_strip_or_none(row["event_description"]),
            planned_value=_to_float(row["planned_value"]),
            planned_unit=_strip_or_none(row["planned_unit"]),
            source_table=f"{self.schema}.{self.event_table}",
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        columns = self._inspector.list_columns(self.phr_table)
        if not columns:
            raise DataContractError(
                f"Required table is missing or inaccessible: {self.schema}.{self.phr_table}"
            )

        event_id_column = first_matching_column(columns, EVENT_ID_CANDIDATES)
        result_value_id_column = first_matching_column(columns, RESULT_VALUE_ID_CANDIDATES)
        phr_name_column = first_matching_column(columns, PHR_NAME_CANDIDATES)
        phr_value_column = first_matching_column(columns, PHR_VALUE_CANDIDATES)
        phr_unit_column = first_matching_column(columns, PHR_UNIT_CANDIDATES)

        if event_id_column is None or phr_name_column is None:
            raise DataContractError(
                f"Table {self.schema}.{self.phr_table} does not expose PHR identity columns."
            )
        if phr_value_column is None or phr_unit_column is None:
            raise DataContractError(
                f"Table {self.schema}.{self.phr_table} does not expose PHR value columns."
            )

        query = f"""
            SELECT
                {quote_ident(event_id_column)} AS event_id,
                {quote_ident(phr_name_column)} AS phr_name,
                {quote_ident(phr_value_column)} AS phr_value_2025,
                {quote_ident(phr_unit_column)} AS phr_unit
            FROM {quote_ident(self.schema)}.{quote_ident(self.phr_table)}
            WHERE {self._event_lookup_condition(event_id_column, result_value_id_column)}
            LIMIT 1
        """
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, self._event_lookup_params(event_id, result_value_id_column))
            row = cursor.fetchone()

        if row is None:
            raise NotFoundError(f"PHR not found for event_id={event_id}")

        return PhrRecord(
            event_id=int(row["event_id"]),
            phr_name=str(row["phr_name"]).strip(),
            phr_value_2025=_to_float(row["phr_value_2025"]),
            phr_unit=_strip_or_none(row["phr_unit"]),
            source_table=f"{self.schema}.{self.phr_table}",
        )

    @staticmethod
    def _event_lookup_condition(event_id_column: str, result_value_id_column: str | None) -> str:
        event_id_condition = f"{quote_ident(event_id_column)} = %s"
        if result_value_id_column is None:
            return event_id_condition
        return f"({event_id_condition} OR {quote_ident(result_value_id_column)} = %s)"

    @staticmethod
    def _event_lookup_params(event_id: int, result_value_id_column: str | None) -> tuple[int, ...]:
        if result_value_id_column is None:
            return (event_id,)
        return (event_id, event_id)


def _strip_or_none(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    rendered = str(value).strip().replace(",", ".")
    if not rendered:
        return None
    try:
        return float(rendered)
    except ValueError as exc:
        raise DataContractError(f"Cannot parse numeric value from {value!r}") from exc
