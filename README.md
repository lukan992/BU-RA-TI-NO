# buratino
# buratino

Локальный Python CLI для верификации одного `event_id` по `summary_text` документов из PostgreSQL.

Что уже реализовано:
- загрузка event, ПХР и summaries из PostgreSQL
- target building и отдельная проверка event fact / PHR fact
- doc-level LLM-анализ первой моделью
- aggregation с fail-closed policy
- logic audit второй моделью
- сохранение machine-readable JSON
- optional XLSX export как производный артефакт

Быстрый старт:

```bash
uv sync --extra dev
uv run pytest
uv run buratino verify 123 --xlsx
```

Минимальная конфигурация:
- заполнить `.env` по примеру из `.env.example`
- положить prompt assets в `prompts/`
- задать `PRIMARY_MODEL`, `AUDIT_MODEL`, `MAIN_DATABASE_URL`, `RUNTIME_DATABASE_URL`
Local Python CLI for verifying one `event_id` by document summaries from PostgreSQL.

Current repository state:
- MVP skeleton only
- config and domain contracts are in place
- repository layer is prepared for PostgreSQL adapters
- CLI validates inputs and wiring

## Quick start

```bash
uv run buratino verify 123
```

## Environment

See `.env.example` for required variables.
