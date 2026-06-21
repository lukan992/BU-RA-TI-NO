# SPEC.md

## 1. Обзор технической реализации

`buratino` теперь состоит из общего OCR-only analysis service и двух адаптеров запуска:

- CLI `verify` / `verify-list`, которые пишут локальные JSON/XLSX.
- Worker `buratino worker`, который claim-ит jobs из PostgreSQL и пишет pipeline-результаты в БД.

Core-анализ сосредоточен в `src/buratino/service/analysis.py::BuratinoAnalysisService`. Он загружает event, ПХР и связанные документы, отбирает только OCR-документы, прогоняет doc-level LLM-проверки и собирает независимый `result_json`.

## 2. Структура проекта

- `src/buratino/service/` — analysis service, error classification, migration runner.
- `src/buratino/worker/` — worker loop и heartbeat.
- `src/buratino/repository/jobs.py` — claim / renew / complete / fail для `buratino_analysis_jobs`.
- `src/buratino/repository/analysis_results.py` — запись в `buratino_event_analysis_results`.
- `src/buratino/models/result_contract.py` — новый pipeline result contract.
- `migrations/` — SQL-миграции worker-таблиц.

## 3. Команды и интерфейсы

- `uv run buratino verify <event_id> [--xlsx]`
- `uv run buratino verify-list <ids_file> [--xlsx path]`
- `uv run buratino worker [--once | --max-jobs N]`
- `uv run buratino migrate`
- `uv run buratino seed-smoke-db [--include-fail-case]`
- `uv run buratino smoke-check [--include-fail-case]`
- `uv run buratino integration-preflight --event-id <EVENT_ID> [--result-value-id <RESULT_VALUE_ID>] [--json]`
- `uv run buratino enqueue-debug-job --event-id <EVENT_ID> [--result-value-id <RESULT_VALUE_ID>] [--allow-debug]`
- `uv run buratino inspect-job --event-id <EVENT_ID> [--result-value-id <RESULT_VALUE_ID>] [--json]`

`BuratinoAnalysisService.analyze_event(event_id, *, job_id=None, payload=None) -> dict` — общий точечный API для CLI и worker.

## 4. Result contract

`result_json` обязательно содержит:

- `pipeline_name`, `pipeline_version`, `event_id`, `report_id`, `result_value_id`, `event_name`
- `statuses.event_description_status`, `statuses.phr_status`, `statuses.plan_status`
- `expected.event_description`, `expected.phr`, `expected.plan`
- `facts.event_description_fact`, `facts.phr_fact`, `facts.plan_fact`
- `supporting_files[]`
- `evidence_items[]`
- `diagnostics`
- `model_info`

Допустимые business-статусы:

- `Подтверждено`
- `Не подтверждено`
- `Не применимо`
- `Не проверялось`

`validate_result_json()` валидирует схему и запрещает non-OCR evidence source.

## 5. Job lifecycle

Таблица `buratino_analysis_jobs`:

- `pending` → job доступна для claim.
- `claimed` → job взята worker-ом и имеет lease.
- `completed` → worker успешно записал result row и завершил job.
- `failed` → job завершена ошибкой без result row.
- `cancelled` → внешний статус, worker его не выставляет.

Claim logic:

- eligible: `pending and available_at <= now()` или `claimed and lease_expires_at <= now()`
- ordering: `priority desc, available_at asc, created_at asc`
- locking: `FOR UPDATE SKIP LOCKED`

Активные jobs уникальны по `(event_id, coalesce(result_value_id, -1))` для `pending/claimed`.

## 6. Таблицы

`buratino_analysis_jobs` хранит входной payload, lease, attempts и технические ошибки.

`buratino_event_analysis_results` хранит:

- `job_id`, `event_id`, `report_id`, `result_value_id`
- `pipeline_name`, `pipeline_version`, `event_name`
- статусы / expected / facts по мероприятию, ПХР и плану
- `supporting_files`, `supporting_document_ids`, `evidence_items`
- `diagnostic_reason`
- полный `result_json`

## 7. Источники данных и evidence policy

- Event и ПХР загружаются из `public.xlsx_events` / `public.xlsx_event_phr`.
- Документы и OCR загружаются через `PostgresSummaryRepository.list_file_evidence()`.
- `EVIDENCE_SOURCE_MODE=ocr_only` по умолчанию; summary-only документы помечаются как skipped и не идут в verdict.
- Если OCR отсутствует во всех документах, worker сохраняет completed result с отрицательными статусами и `diagnostic_reason="OCR отсутствует"`.

## 8. Флаги и env

Ключевые флаги:

- `AUDIT_ENABLED=false`
- `RANKING_ENABLED=false`
- `SUMMARY_VERDICT_ENABLED=false`
- `DATE_CHECK_ENABLED=false`
- `EVIDENCE_SOURCE_MODE=ocr_only`

Worker env:

- `BURATINO_WORKER_ID`
- `BURATINO_WORKER_POLL_INTERVAL_SECONDS`
- `BURATINO_JOB_LEASE_SECONDS`
- `BURATINO_JOB_HEARTBEAT_SECONDS`
- `BURATINO_MAX_CONCURRENCY`
- `BURATINO_FAKE_LLM`
- `ALLOW_INTEGRATION_DEBUG_COMMANDS`

В текущей версии `BURATINO_MAX_CONCURRENCY` должен быть равен `1`.

Локальный smoke env (`.env.smoke.example`):

- `LLM_BACKEND=fake`
- `BURATINO_FAKE_LLM=true`
- `PRIMARY_MODEL=fake/buratino-smoke-model`
- локальные `MAIN_DATABASE_URL` / `RUNTIME_DATABASE_URL` на PostgreSQL из `docker-compose.local.yml`

## 9. Local smoke mode

Для локальной проверки worker pipeline без production DB добавлены:

- `docker-compose.local.yml` — PostgreSQL 16 на `127.0.0.1:55432`
- `.env.smoke.example` — локальные env для OCR-only smoke режима
- `scripts/run_smoke.sh` — поднимает БД, запускает миграции, seed, bounded worker и smoke-check
- `src/buratino/llm/fake_client.py` — детерминированный fake backend без сети
- `src/buratino/service/smoke.py` — seed/check helper для локальных данных

`seed-smoke-db` создает минимальные source tables (`xlsx_events`, `xlsx_event_phr`, `documents`, `document_summary_results`, `ocr_results`) если их еще нет, очищает и заново вставляет smoke-case данные:

- `1001/2001` — OCR подтверждает перевыполнение плана
- `1002/2002` — OCR подтверждает только семантику без количества
- `1003/2003` — OCR показывает `8` при плане `12`
- `1004/2004` — документ есть, OCR отсутствует, summary игнорируется

`smoke-check` проверяет, что:

- все 4 jobs завершены как `completed`
- записаны 4 строки в `buratino_event_analysis_results`
- статусы и diagnostics совпадают с ожидаемыми OCR-only кейсами
- `result_json.diagnostics.evidence_source_used == "ocr"`
- summary не попал в evidence

## 10. Manual integration mode on old OCR DB

Добавлены:

- `Dockerfile` — минимальный runtime для `uv run buratino ...`
- `docker-compose.integration.yml` — контейнер `buratino-worker`, который читает `.env.integration` и по умолчанию запускается как `uv run buratino worker --max-jobs 1`
- `.env.integration.example` — шаблон для старой dev/staging/copy БД
- `docs/integration_manual_worker_check.md` — пошаговый runbook

`integration-preflight`:

- не запускает LLM
- не создает job
- проверяет подключение к БД, наличие ключевых таблиц, event, planned value/unit, количество документов и OCR
- предупреждает, если OCR отсутствует

`enqueue-debug-job`:

- создает `pending` job только для ручной проверки
- требует `ALLOW_INTEGRATION_DEBUG_COMMANDS=true` или `--allow-debug`
- не создает дубль, если уже есть active job на `(event_id, result_value_id)`

`inspect-job`:

- сначала ищет result по `result_payload.result_id` последней job (точная привязка к завершённой job), затем fallback на последний result по `event_id/result_value_id`
- умеет печатать machine-readable JSON

Worker logs теперь явно показывают:

- startup config без паролей/секретов
- claim job
- event/documents/OCR counts
- отключенные summary/date/audit/ranking flags
- сохранение result row и complete/fail status

## 11. Технические ограничения

- `buratino` не пишет comparison/judge/manual verification результаты.
- Date/deadline, signatures и regions не входят в worker result contract.
- Применимость плановой проверки задаётся `xlsx_events.planned_value > 0`, а не LLM-классификацией `event_type`; при заданном плановом значении `plan_status` не бывает `Не применимо`. Для `planned_value <= 1` подтверждение события (семантическое OCR-подтверждение) засчитывается как достижение плана; для `planned_value > 1` требуется `comparison_result = meets_target` с фактическим значением и единицей. `event_description_status` для plan-applicable события совпадает с `plan_status`.
- Worker берёт `result_value_id` и `report_id` из колонок job (источник истины) и зеркалит их в payload анализа; `result_json.result_value_id` и колонка `buratino_event_analysis_results.result_value_id` всегда совпадают со значением из job.
- LLM malformed JSON проходит через existing repair-retry wrapper; при окончательной неудаче pipeline остаётся fail-closed.

## 12. Нерешенные технические вопросы

- Оркестратор создания jobs и общая retry policy между сервисами остаются внешней ответственностью.
- Comparison/judge schema только документирована, но не реализована в этом репозитории.
