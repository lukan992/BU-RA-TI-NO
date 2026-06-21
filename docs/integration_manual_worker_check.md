# Integration Manual Worker Check

Локальная цель этого сценария — безопасно проверить `buratino worker` на старой dev/staging/copy БД с реальным OCR.

Важно:

- не использовать production DB без отдельного подтверждения;
- debug job создается только вручную и только для non-production testing;
- миграции `buratino` добавляют только свои таблицы и индексы.

## Шаг 1. Подготовить `.env.integration`

```bash
cp .env.integration.example .env.integration
# заполнить DATABASE_URL/RUNTIME_DATABASE_URL/LLM_API_KEY
```

## Шаг 2. Применить миграции

```bash
docker compose -f docker-compose.integration.yml run --rm buratino-worker uv run buratino migrate
```

Или локально:

```bash
set -a && source .env.integration && set +a
uv run buratino migrate
```

## Шаг 3. Найти event/result с OCR

```sql
select event_id, result_value_id, event_name, planned_value, planned_unit
from xlsx_events
where planned_value is not null
limit 20;
```

Проверка связанных документов и OCR по тем же таблицам, что использует repository:

```sql
select d.event_id, d.document_id, d.file_name, length(o.full_text) as ocr_length
from documents d
left join ocr_results o on o.document_id = d.document_id
where d.event_id in ('<EVENT_ID>', '<RESULT_VALUE_ID>')
order by d.file_name
limit 50;
```

## Шаг 4. Preflight

```bash
docker compose -f docker-compose.integration.yml run --rm buratino-worker \
  uv run buratino integration-preflight --event-id <EVENT_ID> --result-value-id <RESULT_VALUE_ID>
```

## Шаг 5. Создать debug job

```bash
docker compose -f docker-compose.integration.yml run --rm buratino-worker \
  uv run buratino enqueue-debug-job --event-id <EVENT_ID> --result-value-id <RESULT_VALUE_ID> --allow-debug
```

Если предпочитается env-защита вместо CLI-флага:

```bash
export ALLOW_INTEGRATION_DEBUG_COMMANDS=true
```

## Шаг 6. Запустить worker на одну job

```bash
docker compose -f docker-compose.integration.yml up --build
```

Или:

```bash
docker compose -f docker-compose.integration.yml run --rm buratino-worker \
  uv run buratino worker --max-jobs 1
```

## Шаг 7. Смотреть логи

```bash
docker compose -f docker-compose.integration.yml logs -f buratino-worker
```

Ожидаемые строки:

- `claimed job`
- `loaded event`
- `loaded documents`
- `documents with OCR`
- `OCR chunks`
- `primary model call`
- `event_description_status`
- `saved buratino_event_analysis_results`
- `completed job`

## Шаг 8. Проверить БД

```bash
docker compose -f docker-compose.integration.yml run --rm buratino-worker \
  uv run buratino inspect-job --event-id <EVENT_ID> --result-value-id <RESULT_VALUE_ID>
```

И SQL:

```sql
select id, event_id, result_value_id, status, attempts, last_error, error_type, error_stage, result_payload, completed_at
from buratino_analysis_jobs
where event_id = <EVENT_ID>
order by created_at desc
limit 5;

select id, event_id, result_value_id, event_description_status, plan_status, phr_status, supporting_files, diagnostic_reason, created_at
from buratino_event_analysis_results
where event_id = <EVENT_ID>
order by created_at desc
limit 5;
```
