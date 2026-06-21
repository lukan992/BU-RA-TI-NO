# SPEC.md

## 1. Обзор технической реализации

Проект реализован как Python CLI `buratino`. Актуальный pipeline загружает данные мероприятия и документов из PostgreSQL, при необходимости ранжирует документы, выполняет только OCR-based doc-level LLM-анализ, агрегирует verdicts, затем отдельно считает deadline enrichment по подтверждающим `supporting_files` и сохраняет итоговый JSON/XLSX. Summary используется только для ranking shortlist и diagnostics; relation/date filter и audit больше не меняют финальные event/PHR verdicts. Для batch-запуска `verify-list` несколько `event_id` обрабатываются параллельно с bounded concurrency.

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
  - `evidence_trace`;
  - deadline fields (`event_deadline_status`, `event_deadline_reason`, `event_deadline_date`, `event_deadline_source_file`, `event_deadline_source`, `event_deadline_raw_text`, `implementation_deadline_raw`, `implementation_deadline_normalized`, `date_checked_files`, `date_missing_files`, `date_late_files`, `date_on_time_files`, `supporting_files_date_status`);
  - diagnostic fields (`event_diagnostic_reasoning`, `phr_diagnostic_reasoning`, `diagnostic_stage`, `diagnostic_reason`, ranking/debug/error fields);
  - сведения о моделях и признаке audit `logic_is_valid`.

## 4. Данные и модели

- Источники событий: `public.xlsx_events`, `public.xlsx_event_phr`.
- Доступные текстовые источники документа: `document_summary_results.summary_text`, `ocr_results` и `ocr_parts`.
- Финальный verdict использует только `ocr_results`/`ocr_parts`. `summary_text` остается вспомогательным источником для ranking shortlist и diagnostics.
- `EVIDENCE_SOURCE_MODE` сохраняется в конфиге для совместимости, но основной pipeline работает как OCR-first verification.
- Verdicts и итоговые контракты описаны в `src/buratino/models/contracts.py`.
- `ReasoningTrace` хранит только `reason_codes`, `evidence_items`, `missing_requirements`, `short_rationale`, `confidence`.
- Top-level `event_reasoning` и `phr_reasoning` формируются кодом из итогового статуса, значимых документов, evidence items и relation/date результатов; перед записью formatter humanizes internal reasoning fields и не пропускает в пользовательский текст technical keys вроде `observed_quantity`, `found_signals`, `missing_requirements` и `reason_codes`.
- `VerificationReport` хранит отдельный diagnostic/debug layer: источники evidence, shortlist ranking, analyzed files, doc-level confirmed files, OCR chunk usage, документы с пустым evidence trace, error diagnostics (`error_stage`, `error_type`, `raw_response_preview`, `model_name`, `prompt_name`) и deadline/date diagnostics.
- Prompt-файлы в `prompts/` являются частью JSON-контракта: их схемы синхронизируются с обязательными полями парсеров, и отсутствие обязательного ключа рассматривается как ошибка ответа LLM.

## 5. Интеграции

- PostgreSQL для чтения мероприятий, ПХР, документов, OCR и извлеченных дат.
- LiteLLM для вызовов `PRIMARY_MODEL`; дополнительно для `RANKING_MODEL` и `AUDIT_MODEL`, если соответствующие флаги включены.

## 6. Переменные окружения

- Обязательные:
  - `PRIMARY_MODEL`
- Условно обязательные:
  - `RANKING_MODEL`, если `RANKING_ENABLED=true`
  - `AUDIT_MODEL`, если `AUDIT_ENABLED=true`
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
  - `RANKING_ENABLED` default `false`
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
  - `EVIDENCE_SOURCE_MODE` default `ocr_first`
  - `AUDIT_ENABLED` default `false`
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

- Поведение fail-closed: без явного OCR-подтверждения итог должен быть `не подтверждено`.
- Event fact и PHR fact проверяются отдельно.
- `supporting_files` формируются только из decision-significant OCR документов после aggregation и больше не сокращаются date/relation проверкой.
- Aggregation подтверждает event/PHR только если doc-level verdict подтвержден и `reasoning_trace.evidence_items` не пуст.
- Если LLM возвращает malformed/empty JSON или schema mismatch, каждый JSON-step делает до двух retries через `json_repair.md`; после окончательной ошибки pipeline сохраняет fail-closed result с diagnostic error вместо молчаливого падения шага.
- PHR doc-level parser нормализует случайный `comparison_result=not_applicable` в `insufficient_data`, чтобы не падать на fail-closed ответах модели.
- Ranking возвращает только shortlist с `doc_id`, `score`, `reason_codes`, `short_reason`; итоговое решение он не принимает.
- Ranking дополнительно пишет debug: `total_docs`, флаг включения, limit, selected doc ids / file names и rejected file names.
- Deadline enrichment выполняется только после вычисления `supporting_files`: сначала по `date_extraction_results.final_text`, затем fallback на OCR text; он пишет top-level date fields, но не меняет verdict и supporting files.
- Context overflow обрабатывается через chunking/reduce:
  - doc-level шаги выполняются по OCR chunks;
  - ranking может переходить на grouped ranking.
- Итоговый XLSX для single-event и batch сохраняет не только пользовательские объяснения, но и diagnostic/debug поля из JSON-контракта.
- Итоговый XLSX для batch собирается только после завершения всех `event_id` и сохраняет порядок входного списка.
- Каждый запуск `verify` и `verify-list` записывает Loguru-логи в `OUTPUT_DIR/buratino.log`; файл очищается в начале нового запуска.

## 9. Нерешенные технические вопросы

- Нет единой retry/backoff политики для timeout-ошибок LiteLLM.
- Production-схема деплоя и операционные лимиты LLM требуют отдельного описания.
