# buratino

Независимый OCR-only pipeline-worker для анализа одного мероприятия по данным PostgreSQL.

Что делает текущая версия:

- claim-ит jobs из `buratino_analysis_jobs`
- анализирует мероприятие, ПХР и план только по OCR
- сохраняет независимый `result_json` в `buratino_event_analysis_results`
- поддерживает локальные CLI-команды `verify`, `verify-list`, `worker`, `migrate`, `seed-smoke-db`, `smoke-check`
- поддерживает debug/integration CLI-команды `integration-preflight`, `enqueue-debug-job`, `inspect-job`

Что не делает:

- не принимает финальное решение за всю систему
- не считает signatures / regions / deadlines / judge / manual verification
- не использует summary как evidence для verdict

## Quick start

```bash
uv sync --extra dev
uv run pytest -q
uv run buratino migrate
uv run buratino worker
```

Локальная проверка одного события:

```bash
uv run buratino verify 123 --xlsx
```

## Local smoke test without production DB

Локальный smoke-прогон поднимает отдельный PostgreSQL, seed-ит 4 OCR-only jobs и гоняет worker на fake LLM backend без сети.

Ручной сценарий:

```bash
cp -n .env.smoke.example .env.smoke
set -a
. ./.env.smoke
set +a

docker compose -f docker-compose.local.yml up -d postgres
uv run buratino migrate
uv run buratino seed-smoke-db
uv run buratino worker --max-jobs 4
uv run buratino smoke-check
```

Или одним скриптом:

```bash
bash scripts/run_smoke.sh
```

Дополнительно:

- `uv run buratino worker --once` — один claim attempt и выход с кодом `0`, даже если jobs нет.
- `uv run buratino worker --max-jobs N` — обработать до `N` jobs и завершиться.
- `LLM_BACKEND=fake` или `BURATINO_FAKE_LLM=true` включает детерминированный локальный backend для smoke/integration сценариев.

## Real OCR integration check

Для ручной проверки на старой dev/staging/copy БД с OCR:

```bash
cp .env.integration.example .env.integration
docker compose -f docker-compose.integration.yml run --rm buratino-worker uv run buratino migrate
docker compose -f docker-compose.integration.yml run --rm buratino-worker \
  uv run buratino integration-preflight --event-id <EVENT_ID> --result-value-id <RESULT_VALUE_ID>
docker compose -f docker-compose.integration.yml run --rm buratino-worker \
  uv run buratino enqueue-debug-job --event-id <EVENT_ID> --result-value-id <RESULT_VALUE_ID> --allow-debug
docker compose -f docker-compose.integration.yml up --build
```

Подробный runbook: [docs/integration_manual_worker_check.md](/home/aidar/projects/mirea_projects/BU-RA-TI-NO/buratino-0.0.4/docs/integration_manual_worker_check.md)
