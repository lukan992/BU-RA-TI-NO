# SPEC.md

## 1. Обзор технической реализации

Проект реализован как Python CLI `buratino`. Pipeline загружает данные мероприятия и документов из PostgreSQL, при необходимости ранжирует документы, выполняет doc-level LLM-анализ, aggregation, relation/date check для подтверждающих документов, logic audit и сохраняет итоговый JSON. Doc-level, relation и audit теперь передают короткий structured evidence trace. Для batch-запуска `verify-list` несколько `event_id` обрабатываются параллельно с bounded concurrency.

## 2. Структура проекта

- `src/buratino/` — CLI, конфиг, доменные модели, репозитории, verifier, audit, export.
- `src/buratino/report/status_explanation.py` — формирование коротких пользовательских объяснений для `event_reasoning` и `phr_reasoning`.
- `tests/unit/` — модульные тесты.
- `tests/integration/` — интеграционные проверки CLI и pipeline.
- `prompts/` — обязательные prompt-файлы.
- `docs/` — продуктовая и техническая документация, журнал изменений агента.
- `output/` — JSON/XLSX результаты прогонов.
- `ids/` — входные списки `event_id` и служебные выгрузки.

## 3. API и интерфейсы

- `buratino verify <event_id>` — проверка одного мероприятия.
- `buratino verify-list <ids_file>` — batch-проверка списка ID с отдельными JSON и общим XLSX.
- Итоговый JSON-контракт сохраняет как минимум:
  - идентификаторы мероприятия;
  - `event_fact_status`;
  - `phr_fact_status`;
  - `supporting_files`;
  - `confirming_documents_relation`;
  - `evidence_trace`;
  - сведения об audit и моделях.

## 4. Данные и модели

- Источники событий: `public.xlsx_events`, `public.xlsx_event_phr`.
- Основной текстовый источник документов: `document_summary_results.summary_text`.
- OCR и OCR parts используются для overflow recovery и выборочного doc-level анализа.
- Verdicts и итоговые контракты описаны в `src/buratino/models/contracts.py`.
- `ReasoningTrace` хранит только `reason_codes`, `evidence_items`, `missing_requirements`, `short_rationale`, `confidence`.
- `ConfirmingDocumentsRelation` дополнительно хранит per-document `relation_matrix` с relation/date status и флагом `allowed_as_supporting_file`.
- Top-level `event_reasoning` и `phr_reasoning` формируются кодом из итогового статуса, значимых документов, evidence items и relation/date результатов; перед записью formatter humanizes internal reasoning fields и не пропускает в пользовательский текст technical keys вроде `observed_quantity`, `found_signals`, `missing_requirements` и `reason_codes`.
- Prompt-файлы в `prompts/` являются частью JSON-контракта: их схемы синхронизируются с обязательными полями парсеров, и отсутствие обязательного ключа рассматривается как ошибка ответа LLM.

## 5. Интеграции

- PostgreSQL для чтения мероприятий, ПХР, документов, OCR и извлеченных дат.
- LiteLLM для вызовов `RANKING_MODEL`, `PRIMARY_MODEL`, `AUDIT_MODEL`.

## 6. Переменные окружения

- Обязательные:
  - `RANKING_MODEL`
  - `PRIMARY_MODEL`
  - `AUDIT_MODEL`
- База данных:
  - `DATABASE_URL` или пара `MAIN_DATABASE_URL` / `RUNTIME_DATABASE_URL`
  - `MAIN_DB_SCHEMA`
  - `RUNTIME_DB_SCHEMA`
- LLM:
  - `LLM_BACKEND`
  - `LLM_API_BASE`
  - `LLM_API_KEY`
  - `LLM_TIMEOUT_SECONDS`
  - `LLM_TEMPERATURE`
  - `LLM_MAX_TOKENS`
- Batch и ranking:
  - `EVENT_MAX_CONCURRENCY` default `3`
  - `MAX_DOCUMENTS_TO_ANALYZE`
  - `RANKING_BATCH_SIZE`
  - `RANKING_SUMMARY_MAX_CHARS`
- Structured trace:
  - `EVIDENCE_TRACE_ENABLED` default `true`
  - `REASONING_TRACE_MODE` default `structured`
  - `REASONING_TRACE_MAX_ITEMS` default `5`
  - `SHORT_RATIONALE_MAX_CHARS` default `300`
  - `EVIDENCE_QUOTE_MAX_CHARS` default `500`
- Overflow recovery:
  - `OCR_CHUNK_MAX_CHARS`
  - `OCR_CHUNK_OVERLAP_CHARS`
  - `OCR_CHUNK_MAX_CHUNKS`
  - `CONFIRMING_RELATION_MAX_TEXT_CHARS`
  - `CONFIRMING_RELATION_BATCH_SIZE`
- Пути и логирование:
  - `PROMPTS_DIR`
  - `OUTPUT_DIR`
  - `LOG_LEVEL`

## 7. Запуск и деплой

- Основной инструмент окружения и запуска — `uv`.
- Типовые команды:
  - `uv run buratino verify <event_id> --output-dir ./output`
  - `uv run buratino verify-list <ids_file> --output-dir ./output --xlsx ./output/batch_results.xlsx`
  - `uv run pytest`

## 8. Технические правила и ограничения

- Поведение fail-closed: без явного подтверждения итог должен быть `не подтверждено`.
- Event fact и PHR fact проверяются отдельно.
- `supporting_files` формируются только из decision-significant документов после aggregation, relation/date filter и audit.
- Aggregation подтверждает event/PHR только если doc-level verdict подтвержден и `reasoning_trace.evidence_items` не пуст.
- PHR doc-level parser нормализует случайный `comparison_result=not_applicable` в `insufficient_data`, чтобы не падать на fail-closed ответах модели.
- Ranking возвращает только shortlist с `doc_id`, `score`, `reason_codes`, `short_reason`; итоговое решение он не принимает.
- Context overflow обрабатывается через chunking/reduce:
  - doc-level шаги могут повторяться по chunked evidence;
  - ranking может переходить на grouped ranking;
  - relation-check может переходить на grouped relation и fragment-level fallback.
- Итоговый XLSX для batch собирается только после завершения всех `event_id` и сохраняет порядок входного списка.
- Каждый запуск `verify` и `verify-list` записывает Loguru-логи в `OUTPUT_DIR/buratino.log`; файл очищается в начале нового запуска.

## 9. Нерешенные технические вопросы

- Нет единой retry/backoff политики для timeout-ошибок LiteLLM.
- Production-схема деплоя и операционные лимиты LLM требуют отдельного описания.
