# logic.md — как устроен и работает buratino

Документ описывает работу сервиса `buratino` целиком: что он делает, откуда берёт данные,
что и куда сохраняет, что нужно для запуска и как его запускать. Это рабочая инструкция и
карта системы. Связанные документы: [PRD.md](PRD.md) (продуктовые требования),
[SPEC.md](SPEC.md) (техническая спецификация), [buratino_integration_contract.md](buratino_integration_contract.md)
(контракт результата для внешних сервисов), [integration_manual_worker_check.md](integration_manual_worker_check.md)
(ручная проверка на реальной OCR-БД).

---

## 1. Назначение и роль в общей архитектуре

`buratino` — это **независимый pipeline-worker**. Он не является финальным решателем по мероприятию.
Его единственная задача: взять job на анализ одного мероприятия, проверить **только по OCR** факт
выполнения мероприятия, ПХР и планового показателя, и сохранить собственный независимый результат.

```
        внешний сервис-оркестратор
                  │  (создаёт job)
                  ▼
        buratino_analysis_jobs ──────────┐
                  │  claim_next           │
                  ▼                       │
        ┌──────────────────┐             │
        │  buratino worker  │  читает OCR из старой OCR-БД
        │  (этот сервис)    │  (xlsx_events / documents / ocr_results)
        └──────────────────┘             │
                  │  save_result + complete
                  ▼                       │
        buratino_event_analysis_results ──┘

  (отдельно, ВНЕ buratino)
        ivan_pipeline_results
                  │
                  ▼
        comparison / judge service ──► pipeline_comparison_results ──► manual verification / final report
```

`buratino` отвечает за: описание мероприятия, ПХР, плановый показатель, supporting files,
OCR-evidence, диагностику.

`buratino` **НЕ** отвечает за: подписи, регионы, сроки/deadline, финальное поле `Подтверждено`,
сравнение с другим pipeline, judge-модель, ручную верификацию. Это отдельные сервисы и таблицы
(`signature_analysis_results`, `region_analysis_results`, `deadline_analysis_results`,
`pipeline_comparison_results`). `buratino` в эти таблицы не пишет.

---

## 2. Что нужно для работы

1. **PostgreSQL** с двумя логическими источниками (могут быть одной и той же БД):
   - `MAIN_DATABASE_URL` — справочные данные мероприятий (`xlsx_events`, `xlsx_event_phr`);
   - `RUNTIME_DATABASE_URL` — документы и OCR (`documents`, `ocr_results`, `document_summary_results`,
     `date_extraction_results`), а также рабочие таблицы buratino (`buratino_analysis_jobs`,
     `buratino_event_analysis_results`).
   - Если задан только `DATABASE_URL`, он используется как fallback для обоих.
2. **LLM-доступ** через `litellm` (по умолчанию OpenRouter): `LLM_API_BASE`, `LLM_API_KEY`,
   `PRIMARY_MODEL`. Для smoke-режима есть фейковый бэкенд (`LLM_BACKEND=fake`), не требующий сети.
3. **Каталог промптов** `prompts/` (обязателен, проверяется на старте).
4. **Python 3.11+** и пакетный менеджер **uv** (`uv sync`), либо Docker.
5. Применённые **миграции** (`buratino migrate`), создающие рабочие таблицы buratino.

---

## 3. Структура пакета (`src/buratino/`)

| Модуль | Назначение |
|---|---|
| `cli/main.py` | CLI на argparse: подкоманды `verify`, `verify-list`, `worker`, `migrate`, `seed-smoke-db`, `smoke-check`, `integration-preflight`, `enqueue-debug-job`, `inspect-job`. Точка входа `buratino`. |
| `config/settings.py` | `Settings.from_env()` — загрузка `.env` и валидация всех переменных окружения. |
| `bootstrap.py` | DI-сборка: `build_app()` (legacy CLI-pipeline) и `build_analysis_service()` (OCR-only сервис для worker). |
| `service/analysis.py` | `BuratinoAnalysisService.analyze_event()` — ядро OCR-only анализа, возвращает `result_json`. |
| `service/result_mapping.py` | Маппинг внутренних verdict'ов в бизнес-контракт; правила плановой проверки (`plan_check_applies`, `quantitative_event_is_confirmed`). |
| `service/errors.py` | Классификатор ошибок worker'а (`classify_error`) — retryable / non-retryable. |
| `service/migrations.py` | `MigrationRunner` — применяет `migrations/*.sql` по порядку. |
| `service/smoke.py` | Сидинг и проверка smoke-БД (детерминированный прогон без сети). |
| `service/integration_debug.py` | Инструменты ручной интеграции: preflight, enqueue-debug-job, inspect-job, `sanitize_dsn`. |
| `worker/runner.py` | `BuratinoWorker` — цикл claim → heartbeat → analyze → save → complete/fail. |
| `repository/events.py` | `PostgresEventRepository`: `get_event`, `get_event_phr` (из `MAIN`-БД). |
| `repository/summaries.py` | `PostgresSummaryRepository`: `list_event_documents`, `list_file_evidence`, `get_document_date_texts` (из `RUNTIME`-БД). |
| `repository/jobs.py` | `BuratinoAnalysisJobRepository`: `claim_next`, `renew_lease`, `complete`, `fail`, `find_active_job`, `get_latest_job`, `enqueue_debug_job`. |
| `repository/analysis_results.py` | `BuratinoEventAnalysisResultRepository`: `save_result`, `get_latest_result`, `get_result_by_id`. |
| `models/` | `domain.py` (EventRecord, PhrRecord, FileEvidence, VerificationTarget…), `contracts.py` (DocumentFactResult…), `result_contract.py` (`BuratinoResult` + `validate_result_json`), `job.py` (`BuratinoAnalysisJob`). |
| `target_builder/service.py` | `TargetBuilder`: нормализация мероприятия, определение типа (`_resolve_event_type`). |
| `verifier/` | Doc-level анализ: `event_verifier.py`, `phr_verifier.py`, `ocr_chunking.py`, `aggregator.py`, `document_ranking.py`, плюс отключаемые `deadline_enrichment.py`, `confirming_documents_relation.py`. |
| `llm/` | `client.py` (`LiteLlmClient`), `fake_client.py` (smoke), `json_runner.py` (repair-retry обёртка), `json_parser.py`, `prompt_loader.py`. |
| `report/` | Экспортеры: `buratino_xlsx_exporter.py` (новые поля), `batch_xlsx_exporter.py`, `xlsx_exporter.py`, `json_writer.py`. |

---

## 4. Что buratino читает (источники данных)

Все чтения — синхронные через `psycopg` (`row_factory=dict_row`). Имена колонок резолвятся
по списку кандидатов (русские/английские варианты), таблицы — через introspection.

### MAIN-БД
- **`xlsx_events`** — справочник мероприятий. Загружается по `event_id` **или** `result_value_id`
  (`WHERE event_id = %s OR result_value_id = %s`). Поля: `event_id`, `event_name`,
  `event_description`, `planned_value` (плановое значение), `planned_unit` / `measurement_unit`,
  `implementation_deadline`.
- **`xlsx_event_phr`** — ПХР по мероприятию: `phr_name`, `phr_value_2025`, `phr_unit`. Если ПХР нет —
  `phr_status = Не применимо`.

### RUNTIME-БД
- **`documents`** — реестр документов мероприятия (`document_id`, `event_id`, `file_name`).
  Связь: `documents.event_id = ANY(linkage_ids)`, где `linkage_ids` = `{event_id, result_value_id}`.
- **`ocr_results`** — OCR-текст (одна строка на страницу/чанк): `document_id`, `full_text`/`ocr_text`,
  `page`, `created_at`. Группируется по `document_id` в `ocr_parts` и склеенный `ocr_text`.
- **`document_summary_results`** — summary документа. **Не используется как evidence для verdict**
  (только debug при `SUMMARY_VERDICT_ENABLED=true`, который по умолчанию выключен).
- **`date_extraction_results`** — даты документов. Используются только при `DATE_CHECK_ENABLED=true`
  (по умолчанию выключено, в worker не подключается).

Путь связи: `xlsx_events.event_id → documents.event_id → ocr_results.document_id`.

---

## 5. Что buratino производит (выходные данные)

### Таблица `buratino_analysis_jobs` (очередь задач)
Создаётся миграцией `0001`. Ключевые поля: `id (uuid)`, `event_id`, `report_id`, `result_value_id`,
`status`, `priority`, `payload (jsonb)`, `result_payload (jsonb)`, `attempts`, `max_attempts`,
`available_at`, `claimed_by`, `claimed_at`, `lease_expires_at`, `last_error`, `error_type`,
`error_stage`, `correlation_id`, временные метки.
Уникальность активных задач: `uq_buratino_analysis_jobs_active_event` —
`unique (event_id, coalesce(result_value_id, -1)) where status in ('pending','claimed')`.
**Job'ы создаёт внешний сервис.** buratino их только читает/обновляет (в проде).

### Таблица `buratino_event_analysis_results` (результаты)
Создаётся миграцией `0002`. Строка записывается **только при успешном анализе и валидном JSON**.
При ошибке анализа строка не пишется. Поля: `id`, `job_id (FK)`, `event_id`, `report_id`,
`result_value_id`, `pipeline_name='buratino'`, `pipeline_version`, `event_name`,
`event_description_status/expected/fact`, `phr_status/expected/fact`, `plan_status/expected/fact`,
`supporting_files (text)`, `supporting_document_ids (jsonb)`, `evidence_items (jsonb)`,
`diagnostic_reason`, `result_json (jsonb)`.

### `result_json` (самодостаточный контракт)
Возвращается `analyze_event()` и кладётся целиком в `result_json`. Структура и пример —
в [buratino_integration_contract.md](buratino_integration_contract.md). Кратко:
```json
{
  "pipeline_name": "buratino",
  "pipeline_version": "0.x.y",
  "event_id": 123, "report_id": null, "result_value_id": 123,
  "event_name": "...",
  "statuses": { "event_description_status": "...", "phr_status": "...", "plan_status": "..." },
  "expected": { "event_description": "...", "phr": null, "plan": "1 Единица" },
  "facts":    { "event_description_fact": "...", "phr_fact": null, "plan_fact": null },
  "supporting_files": [ { "document_id": "...", "filename": "...", "reason": "..." } ],
  "evidence_items":   [ { "document_id": "...", "filename": "...", "page_number": null,
                          "chunk_id": "...", "text_fragment": "...", "supports": ["event_description","plan"] } ],
  "diagnostics": { "evidence_source_used": "ocr", "ocr_available": true,
                   "analyzed_files": [...], "skipped_files": [...], "diagnostic_reason": "..." },
  "model_info": { "primary_model": "...", "ranking_model": null, "audit_model": null }
}
```
Контракт жёстко валидируется `validate_result_json()` (точный набор ключей, типы, значения статусов).

### `result_payload` успешной job
При `complete` в job записывается:
```json
{ "ok": true, "result_id": "<uuid>", "event_id": 123,
  "event_description_status": "...", "phr_status": "...", "plan_status": "...",
  "supporting_files_count": 2 }
```

---

## 6. Жизненный цикл job

Статусы job: `pending` → `claimed` → `completed` | `failed`; retryable-ошибка возвращает в `pending`.
(`cancelled` зарезервирован.)

```
worker.run():
  loop:
    job = claim_next()          # FOR UPDATE SKIP LOCKED, атомарно переводит в 'claimed', attempts+1
    if not job: sleep(poll_interval); continue
    _process_job(job):
        start heartbeat thread  # renew_lease каждые HEARTBEAT_SECONDS
        payload = job.payload + {result_value_id, report_id из колонок job}   # колонки job — источник истины
        result_json = analysis_service.analyze_event(event_id, payload=payload)
        в одной транзакции:
            renew_lease()       # если lease потерян → RuntimeError (job не завершается успехом)
            result_id = save_result(job, result_json)   # validate + insert
            complete(result_payload с result_id)        # только текущий owner, status='claimed'
        on exception:
            classify_error(exc) → fail(retryable=?, retry_at=now+poll_interval)
        stop heartbeat
```

**`claim_next`**: eligible = `(pending AND available_at<=now())` OR `(claimed AND lease_expires_at<=now())`;
сортировка `priority DESC, available_at ASC, created_at ASC`; `FOR UPDATE SKIP LOCKED`.

**`renew_lease`** продлевает lease только текущему owner с непросроченным lease; если 0 строк —
lease потерян, worker не завершает job как успех.

**`complete`/`fail`** обновляют только строку с `status='claimed' AND claimed_by=worker_id`.
**`fail`**: если retryable и `attempts < max_attempts` → `pending` с `available_at=retry_at`;
иначе → `failed`.

Гарантия согласованности: `save_result` и `complete` выполняются в одной транзакции worker'а.
Если insert результата упал — job не становится `completed`.

---

## 7. Логика анализа (OCR-only)

`BuratinoAnalysisService.analyze_event(event_id, *, job_id=None, payload=None)`:

1. Загрузить мероприятие (`get_event`) и ПХР (`get_event_phr`, опционально).
2. Загрузить связанные документы и их OCR (`list_file_evidence`).
3. Отобрать документы **с OCR**; документы без OCR попадают в `skipped_files` и **не анализируются по summary**.
4. Построить таргеты (`build_event_target`, `build_phr_target`). OCR при необходимости режется на чанки
   (`OcrChunker`: `OCR_CHUNK_MAX_CHARS`, `OCR_CHUNK_OVERLAP_CHARS`, `OCR_CHUNK_MAX_CHUNKS`).
5. Отправить OCR-чанки в `PRIMARY_MODEL` через `event_verifier`/`phr_verifier` (JSON-ответ с repair-retry).
6. Свести doc-level результаты в три бизнес-статуса и собрать `supporting_files`, `evidence_items`, диагностику.
7. Провалидировать `result_json` и вернуть.

**Ranking** по умолчанию выключен (`RANKING_ENABLED=false`) — анализируются все документы с OCR.
**Audit**, **date/deadline**, **summary-verdict** по умолчанию выключены и в OCR-only сервисе не влияют на verdict.

### Правила статусов (ключевая логика)

Применимость плановой проверки задаётся **наличием планового значения в xlsx**, а не LLM-типом мероприятия:
`plan_check_applies(target) = planned_value is not None and planned_value > 0`.

- **planned_value > 0 (план применим):**
  - `event_description_status = Подтверждено` **тогда и только тогда**, когда подтверждён план;
    иначе `Не подтверждено`. `plan_status` совпадает с этим решением (`Подтверждено`/`Не подтверждено`).
    `plan_status` в этом случае **никогда не `Не применимо`**.
  - Подтверждение плана (`quantitative_event_is_confirmed`):
    - `planned_value <= 1` (план в 1 единицу): достаточно семантического OCR-подтверждения факта
      (создан объект / выполнено событие = достигнута 1 единица);
    - `planned_value > 1`: требуется `fact_status=подтверждено` + evidence + `comparison_result=meets_target`
      + ненулевые `observed_value` и `observed_unit`.
- **planned_value отсутствует или = 0 (качественное мероприятие):**
  - `plan_status = Не применимо`;
  - `event_description_status = Подтверждено`, если есть семантическое OCR-подтверждение, иначе `Не подтверждено`.
- **ПХР:** `Подтверждено`/`Не подтверждено` по `phr_verifier`; ПХР отсутствует → `Не применимо`;
  плановое значение ПХР = 0 → авто-`Подтверждено`.
- **Нет OCR ни у одного документа:** все статусы `Не подтверждено`, `diagnostic_reason="OCR отсутствует"`,
  job завершается `completed` (это бизнес-результат, не ошибка).

### Словарь бизнес-статусов
`Подтверждено`, `Не подтверждено`, `Не применимо`, `Не проверялось` — единый для
`event_description_status`, `phr_status`, `plan_status`. Технические статусы job
(`pending`/`claimed`/`completed`/`failed`/`cancelled`) в бизнес-поля не попадают.

---

## 8. Классификация ошибок (`classify_error`)

| Ситуация | retryable | error_type / stage |
|---|---|---|
| `JsonStepFailure` (битый/пустой JSON от LLM после repair) | да | из info |
| `NotFoundError` (event/PHR не найден) | нет | `not_found` / `load_event` |
| `ValidationError` / `DataContractError` (контракт/данные) | нет | `invalid_input` / `analysis` |
| `RepositoryError` с «llm request failed» / «failed to connect» | да | `temporary_backend_error` |
| прочий `RepositoryError` | да | `repository_error` |
| любое прочее исключение | нет | `unexpected_error` |

Retryable-ошибка возвращает job в `pending` (пока есть попытки), иначе — `failed`.

---

## 9. Конфигурация (переменные окружения)

Загружается `Settings.from_env()` из `.env` (или другого файла). Полный список см. в
[SPEC.md](SPEC.md); ниже — практически значимые.

**БД:** `MAIN_DATABASE_URL`, `RUNTIME_DATABASE_URL` (или `DATABASE_URL` как fallback),
`MAIN_DB_SCHEMA`, `RUNTIME_DB_SCHEMA` (по умолчанию `public`).

**LLM:** `LLM_BACKEND` (`litellm`/`openrouter`/`fake`), `LLM_API_BASE`, `LLM_API_KEY`, `PRIMARY_MODEL`,
`RANKING_MODEL`, `AUDIT_MODEL` (последние два = `disabled`, если фичи выключены), `LLM_TIMEOUT_SECONDS`,
`LLM_TEMPERATURE`, `LLM_MAX_TOKENS`.

**Feature flags (целевые значения для OCR-only worker):**
```
EVIDENCE_SOURCE_MODE=ocr_only      # primary evidence — только OCR (без summary-fallback)
SUMMARY_VERDICT_ENABLED=false      # summary не влияет на verdict
DATE_CHECK_ENABLED=false           # сроки не участвуют в buratino
AUDIT_ENABLED=false                # audit не вызывается и не меняет результат
RANKING_ENABLED=false              # анализируются все документы с OCR
```

**OCR-чанкинг:** `OCR_CHUNK_MAX_CHARS` (≈40000), `OCR_CHUNK_OVERLAP_CHARS` (≈1500),
`OCR_CHUNK_MAX_CHUNKS` (≈120).

**Worker:** `BURATINO_WORKER_ID`, `BURATINO_WORKER_POLL_INTERVAL_SECONDS` (≈5),
`BURATINO_JOB_LEASE_SECONDS` (≈600), `BURATINO_JOB_HEARTBEAT_SECONDS` (≈60),
`BURATINO_MAX_CONCURRENCY` (только `1` в текущей версии).

**Прочее:** `PROMPTS_DIR` (`prompts`), `OUTPUT_DIR` (`output`), `LOG_LEVEL`,
`ALLOW_INTEGRATION_DEBUG_COMMANDS` (разрешает debug-команды), `BURATINO_FAKE_LLM`/`LLM_BACKEND=fake`
(детерминированный smoke без сети).

**Секреты:** реальные `.env.integration` и `.env.smoke` добавлены в `.gitignore`; в репозитории —
только `*.example`-шаблоны. Реальные ключи/пароли в git не коммитятся.

---

## 10. Миграции

Каталог `migrations/`, применяются по алфавиту через `MigrationRunner` (psycopg, идемпотентные
`create ... if not exists`). Файлы:
- `0001_buratino_analysis_jobs.sql` — таблица очереди + индексы (`...claim`, `...event_id`,
  `...correlation_id`) + partial-unique активной задачи.
- `0002_buratino_event_analysis_results.sql` — таблица результатов + индексы по `event_id`/`job_id`.
Оба начинаются с `create extension if not exists pgcrypto;` (для `gen_random_uuid()`).
Применяются к `RUNTIME_DATABASE_URL`.

Запуск: `uv run buratino migrate` (печатает применённые файлы).

---

## 11. CLI-команды

Точка входа — `buratino` (`pyproject.toml [project.scripts]`). Через uv: `uv run buratino <cmd>`.

| Команда | Что делает |
|---|---|
| `worker [--once] [--max-jobs N]` | Запускает рабочий цикл (claim → analyze → save → complete/fail). `--once`/`--max-jobs` — выйти после N задач. |
| `migrate` | Применяет SQL-миграции к RUNTIME-БД. |
| `verify --event-id N [--output-dir DIR] [--xlsx]` | Синхронный CLI-прогон одного мероприятия (legacy-pipeline `build_app`), пишет JSON/XLSX локально. |
| `verify-list --ids-file FILE [--xlsx PATH] [--stop-on-error]` | Пакетный прогон списка `event_id` с `EVENT_MAX_CONCURRENCY`, общий XLSX. |
| `integration-preflight --event-id N [--result-value-id R] [--json]` | Диагностика готовности данных: planned_value/unit, наличие ПХР, нужные таблицы, число документов и документов с OCR, превью OCR, активные флаги. Сеть LLM не дёргает. |
| `enqueue-debug-job --event-id N [--result-value-id R] [--allow-debug] ...` | **Только для отладки.** Создаёт pending-job (в проде job создаёт внешний сервис). Требует `ALLOW_INTEGRATION_DEBUG_COMMANDS=true` или `--allow-debug`. Не создаёт дубль активной задачи. |
| `inspect-job --event-id N [--result-value-id R] [--json]` | Показывает последнюю job и связанный result. Result ищется сначала по `result_payload.result_id` последней job, затем fallback по `event_id/result_value_id`. |
| `seed-smoke-db [--include-fail-case]` / `smoke-check` | Сидинг и проверка детерминированной smoke-БД (см. ниже). |

---

## 12. Как запускать

### 12.1. Локальный smoke (без сети, детерминированный)
Полный путь автоматизирован в `scripts/run_smoke.sh`:
```bash
bash scripts/run_smoke.sh
```
Он поднимает Postgres (`docker-compose.local.yml`, порт `55432`), копирует `.env.smoke.example → .env.smoke`,
затем: `buratino migrate` → `buratino seed-smoke-db` → `buratino worker --max-jobs 4` → `buratino smoke-check`.
LLM-бэкенд фейковый (`LLM_BACKEND=fake`, `PRIMARY_MODEL=fake/buratino-smoke-model`). Сеть и реальные ключи не нужны.

### 12.2. Ручная интеграция против реальной OCR-БД
```bash
cp .env.integration.example .env.integration      # заполнить реальными DSN и LLM_API_KEY (НЕ коммитить)
set -a && . ./.env.integration && set +a
uv run buratino migrate
uv run buratino integration-preflight --event-id <ID> --result-value-id <RID> --json
# создать job (в проде это делает внешний сервис; для отладки):
ALLOW_INTEGRATION_DEBUG_COMMANDS=true uv run buratino enqueue-debug-job --event-id <ID> --result-value-id <RID> --allow-debug
uv run buratino worker --once
uv run buratino inspect-job --event-id <ID> --result-value-id <RID> --json
```
Подробности — в [integration_manual_worker_check.md](integration_manual_worker_check.md).

### 12.3. Docker
- Образ: `Dockerfile` (python:3.12-slim + uv, копирует src/prompts/migrations/docs/scripts,
  `uv sync --frozen`). `CMD` по умолчанию — `buratino worker --max-jobs 1`.
- Интеграционный compose: `docker-compose.integration.yml` (сервис `buratino-worker`, `env_file: .env.integration`).
```bash
docker compose -f docker-compose.integration.yml up --build
```

### 12.4. Production worker
1. Применить миграции: `buratino migrate` (к RUNTIME-БД).
2. Внешний сервис создаёт pending-job в `buratino_analysis_jobs` (см. контракт ниже).
3. Запустить процесс worker: `buratino worker` (без `--once`, бесконечный poll).
   Масштабирование — несколькими процессами; конкурентный claim безопасен за счёт
   `FOR UPDATE SKIP LOCKED`. В текущей версии один процесс обрабатывает по одной job
   (`BURATINO_MAX_CONCURRENCY=1`).

---

## 13. Контракт интеграции для внешних сервисов

**Создание job (делает внешний оркестратор):** вставить строку в `buratino_analysis_jobs` со
`status='pending'`, заполнив `event_id` и (при наличии) `result_value_id`/`report_id`. Эти колонки —
**источник истины**: worker зеркалит их в payload анализа, поэтому `result_json.result_value_id` и
колонка результата всегда совпадают со значением из job. `payload` может нести доп. контекст,
но идентификаторы берутся из колонок. Активная уникальность — по `(event_id, coalesce(result_value_id,-1))`.

**Чтение результата:** по `job.result_payload.result_id` (точная привязка к завершённой job) —
строка в `buratino_event_analysis_results`; либо последний результат по `event_id`/`result_value_id`.
`result_json` самодостаточен для слоя сравнения/judge.

**Сравнение** (`ivan_pipeline_results` vs `buratino_event_analysis_results`), judge и manual verification
выполняет **отдельный сервис**. buratino в `pipeline_comparison_results` не пишет.

---

## 14. Тесты

```bash
uv sync --extra dev
uv run pytest -q
```
Покрытие включает: jobs (claim/lease/complete/fail, reclaim протухших, защита owner), анализ
(OCR подтверждает event/PHR/plan; summary не используется; нет OCR → не анализируем по summary;
date/audit/ranking не влияют по умолчанию; количественный таргет обязателен), контракт `result_json`,
worker (сохранение `result_value_id`, поведение при ошибках), inspect-job (поиск по `result_id`).

---

## 15. Логи и диагностика

Worker логирует (loguru, без секретов — DSN санитизируется): startup-конфиг и активные флаги,
claim job, число документов/OCR/чанков, итоговые статусы и `diagnostic_reason`, сохранение result и
complete/fail c `error_type`/`error_stage`/`retryable`/`attempts`. Поле `diagnostic_reason` в результате
объясняет вердикт (например: «OCR подтверждает факт выполнения, но найдено 8 ед, что ниже плана 12 ед.»
или «OCR отсутствует»).

---

## 16. Чего buratino не делает (намеренно)

- Не вычисляет подписи, регионы, сроки/deadline и финальное `Подтверждено`.
- Не сравнивает себя с другим pipeline, не запускает judge, не делает manual verification.
- Не использует summary, дату или audit как фактор verdict (в OCR-only режиме по умолчанию).
- Не создаёт production-job самостоятельно (это делает внешний сервис; `enqueue-debug-job` — только для отладки).
