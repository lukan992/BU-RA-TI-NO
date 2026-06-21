# AGENTS_LOG.md

Краткий журнал изменений, сделанных AI-агентом.

---

## 2026-06-21

### Запрос
Кратко: исправить два бага после integration-прогона — потеря `result_value_id` при сохранении результата и неверный `plan_status`/`event_description_status` для количественного мероприятия (`planned_value=1` давал `plan_status=Не применимо`).

### Измененные файлы
- `src/buratino/worker/runner.py`
- `src/buratino/repository/analysis_results.py`
- `src/buratino/service/integration_debug.py`
- `src/buratino/service/result_mapping.py`
- `src/buratino/service/analysis.py`
- `tests/unit/test_analysis_plan_status.py` (новый)
- `tests/unit/test_worker_runner.py`
- `tests/unit/test_integration_debug.py`
- `docs/PRD.md`, `docs/SPEC.md`

### Изменения
- Worker зеркалит `job.result_value_id`/`job.report_id` (источник истины — колонки job) в payload анализа, поэтому `result_json.result_value_id` и колонка результата больше не теряются.
- `inspect-job` сначала ищет result по `result_payload.result_id` последней job, затем fallback по `event_id/result_value_id`; добавлен `BuratinoEventAnalysisResultRepository.get_result_by_id`.
- Применимость плановой проверки теперь определяется `planned_value > 0` из `xlsx_events`, а не LLM-`event_type` (`plan_check_applies`). При заданном плановом значении `plan_status` не может быть `Не применимо`; `event_description_status` подтверждается только вместе с планом. Для `planned_value <= 1` семантическое OCR-подтверждение засчитывается как достижение 1 единицы.

### Проверка
- Выполнено: `uv run pytest -q` — 117 passed (включая 5 новых regression-тестов).
- Выполнено: `bash scripts/run_smoke.sh` — Smoke check passed for events 1001-1004, 4 result rows.

### Документация
- PRD.md: обновлен (правила применимости плана и связь event_description/plan).
- SPEC.md: обновлен (inspect-job по result_id, источник истины для result_value_id, правила plan_status).

### Примечания
- `_resolve_event_type` намеренно не менялся: существующий тест LLM-классификации для `planned_value=1` остаётся в силе, корректность плана обеспечена decoupling в маппинге результата.

## 2026-06-08

### Запрос
Кратко: добавить файл лога для каждого прогона с перезаписью в начале нового запуска.

### Измененные файлы
- `src/buratino/logging.py`
- `src/buratino/cli/main.py`
- `tests/unit/test_cli.py`
- `docs/SPEC.md`

### Изменения
- `configure_logging` научен писать логи не только в `stderr`, но и в `OUTPUT_DIR/buratino.log`.
- Для команд `verify` и `verify-list` лог-файл создается перед запуском pipeline и открывается в режиме `w`, поэтому предыдущий лог полностью очищается.
- Добавлены unit-тесты на создание лог-файла и его перезапись при повторном запуске.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_cli.py tests/unit/test_config.py -q`
- Результат: успешно.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- Лог-файл общий для одного запуска CLI и располагается рядом с output-артефактами.

## 2026-06-08

### Запрос
Кратко: проверить все ожидаемые поля и prompt-файлы, чтобы модели всегда получали полный JSON-контракт и не падали на пропущенных ключах.

### Измененные файлы
- `prompts/document_ranking.md`
- `prompts/event_fact_summary.md`
- `prompts/phr_fact_summary.md`
- `prompts/confirming_documents_relation.md`
- `prompts/event_type_resolution.md`
- `prompts/logic_audit.md`
- `tests/unit/test_prompt_contracts.py`
- `docs/SPEC.md`

### Изменения
- Усилены все prompt-файлы: каждый из них теперь явно говорит, что все ключи схемы обязательны, а пустые массивы нужно возвращать как `[]`.
- Для `logic_audit.md` отдельно зафиксировано обязательное присутствие `rule_violations` и `final_supporting_files`.
- Добавлен тест, который проверяет наличие обязательных ключей в реальных prompt-файлах и ловит рассинхрон с парсерами.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_json_parser.py tests/unit/test_prompt_contracts.py -q`
- Результат: успешно.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- Это не меняет бизнес-логику, а только делает JSON-контракты для LLM жестче и проверяемее.

## 2026-06-08

### Запрос
Кратко: проверить ошибку `comparison_result must be one of: below_target, insufficient_data, meets_target` и исправить ее.

### Измененные файлы
- `src/buratino/llm/json_parser.py`
- `prompts/phr_fact_summary.md`
- `tests/unit/test_json_parser.py`
- `docs/SPEC.md`

### Изменения
- Для PHR-parser добавлена нормализация `comparison_result=not_applicable` в `insufficient_data`, чтобы прогон не падал на fail-closed ответах модели.
- В PHR prompt добавлено явное запрещение `not_applicable` и правило использовать `insufficient_data`, если данных недостаточно.
- Добавлен unit-тест на нормализацию этого случая.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_json_parser.py -q`
- Результат: успешно.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- Исправление касается только устойчивости парсинга ответа модели; бизнес-логика fail-closed сохранена.

## 2026-05-21 16:00

### Запрос
Кратко: собрать отдельным файлом `event_id` с ошибкой relation-step `ContextWindowExceededError`.

### Изменения
- Добавлен файл `ids/relation_overflow_ids.txt` со списком проблемных `event_id`.
- Созданы `docs/SPEC.md` и `docs/AGENTS_LOG.md`, так как они отсутствовали в проекте.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: отсутствовал и создан.

### Примечания
- В список включены уникальные `event_id`, найденные в сохраненных JSON-результатах с ошибкой `Confirming documents relation check failed`.

## 2026-05-21 16:20

### Запрос
Кратко: проанализировать `output/97-6/results.xlsx` и выписать все `id` со статусом ошибки.

### Изменения
- Добавлен файл `ids/results_97-6_error_ids.txt` со всеми `input_event_id` из строк `results.xlsx`, где `status=error`.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: не требовал обновления.

### Примечания
- В файле перечислены именно входные `id` из колонки `input_event_id`.

## 2026-05-26 12:17

### Запрос
Кратко: изменить семантику поля с названиями файлов так, чтобы в отчет попадали только decision-significant документы, реально повлиявшие на итоговое решение.

### Изменения
- Обновлена логика `supporting_files`: теперь список собирается только из подтверждающих event/PHR doc-level результатов и финализируется после audit.
- Relation-step начал использовать тот же отфильтрованный event-список, а не просто все подтвержденные doc-level документы.
- Добавлены тесты на составное подтверждение несколькими файлами, строгий PHR-фильтр и очистку списка после audit-flip.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- `supporting_files` сохраняет прежний JSON/XLSX ключ, но его смысл изменен: теперь это только decision-significant файлы.

## 2026-05-26 13:20

### Запрос
Кратко: ускорить `verify-list`, распараллелив обработку разных `event_id` с bounded concurrency.

### Изменения
- Добавлен конфиг `EVENT_MAX_CONCURRENCY` с default `3`.
- `verify-list` переведен на bounded parallel execution через `ThreadPoolExecutor`, при этом каждый `event_id` запускает свой независимый pipeline и пишет свой JSON.
- Итоговый batch XLSX теперь собирается после завершения всех задач с сохранением порядка входных `event_id`.
- Добавлены тесты на чтение нового конфига, соблюдение лимита concurrency, обработку ошибок отдельных ID и стабильный порядок строк в XLSX.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- Внутренний pipeline одного `event_id` остался последовательным; параллелятся только разные мероприятия.

## 2026-05-26 16:07

### Запрос
Кратко: добавить recovery от context overflow во все LLM-шаги, а не только в OCR doc-level анализ.

### Изменения
- Общий chunking helper расширен: теперь он умеет резать `summary`/`evidence_text`, а doc-level recovery работает не только для OCR, но и для summary-based evidence.
- Ranking получил grouped overflow fallback с batching документов и укороченными `summary_text`.
- Relation-check получил grouped overflow fallback по группам подтверждающих документов и fragment-level fallback для oversized single-document cases.
- Добавлены новые конфиги overflow recovery и тесты для ranking, relation, summary chunking и config parsing.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- Recovery покрывает context overflow; автоматические retry/backoff для timeout по-прежнему не добавлялись.

## 2026-05-27

### Запрос
Кратко: переписать папку `docs` по правилам из `AGENTS.md`.

### Изменения
- Переписаны `docs/PRD.md` и `docs/SPEC.md` в коротком формате, привязанном к текущему коду и правилам поддержки документации.
- `docs/prd.md` удален и заменен на `docs/PRD.md`, чтобы путь соответствовал ожидаемому соглашению проекта.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- Изменения затронули только документацию; код и тесты не менялись.

## 2026-06-05 15:20

### Запрос
Кратко: реализовать structured evidence trace без свободного Chain-of-Thought.

### Измененные файлы
- `src/buratino/models/contracts.py`
- `src/buratino/llm/json_parser.py`
- `src/buratino/app.py`
- `src/buratino/audit/service.py`
- `src/buratino/verifier/aggregator.py`
- `src/buratino/verifier/confirming_documents_relation.py`
- `src/buratino/verifier/document_ranking.py`
- `src/buratino/verifier/event_verifier.py`
- `src/buratino/verifier/phr_verifier.py`
- `src/buratino/config/settings.py`
- `src/buratino/bootstrap.py`
- `prompts/event_fact_summary.md`
- `prompts/phr_fact_summary.md`
- `prompts/document_ranking.md`
- `prompts/confirming_documents_relation.md`
- `prompts/logic_audit.md`
- `tests/unit/*`
- `tests/integration/*`
- `docs/PRD.md`
- `docs/SPEC.md`

### Изменения
- Добавлены `EvidenceItem`, `ReasoningTrace`, relation matrix, audit rule violations и top-level `evidence_trace` в JSON-контракт.
- Doc-level parser-ы, ranking, relation-step и audit переведены на новые strict JSON-схемы с лимитами trace.
- Aggregation стала fail-closed по непустому evidence trace; relation/date filter теперь чистит event supporting files до audit.
- Обновлены prompt-ы, unit/integration tests и runtime config для structured trace.

### Проверка
- Выполнено: `uv run pytest`
- Результат: успешно.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- Публичные CLI-команды сохранены.
- Старые ключи JSON сохранены; `evidence_trace` добавлен как расширение контракта.

## 2026-06-05 16:05

### Запрос
Кратко: заменить технические top-level reasoning на короткие объяснения статуса для аналитика.

### Измененные файлы
- `src/buratino/report/status_explanation.py`
- `src/buratino/app.py`
- `tests/unit/test_status_explanation.py`
- `tests/integration/test_cli_fail_closed_path.py`
- `tests/integration/test_cli_happy_path.py`
- `tests/integration/test_missing_phr_path.py`
- `tests/integration/test_ocr_fallback_path.py`
- `docs/PRD.md`
- `docs/SPEC.md`

### Изменения
- Добавлен formatter, который собирает короткие русскоязычные объяснения для `event_reasoning` и `phr_reasoning` из итогового статуса, значимых документов и обязательных признаков.
- Из top-level объяснений убраны технические термины внутренней обработки; тексты теперь опираются только на decision-significant документы.
- Добавлены unit-тесты на запрет технических слов и обновлены integration-тесты на новый формат объяснений.

### Проверка
- Выполнено: `uv run pytest`
- Результат: успешно.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- Внутренние поля document-level reasoning сохранены для диагностики; изменены только top-level объяснения в отчете.

## 2026-06-05 16:25

### Запрос
Кратко: разобраться, почему при ошибке LiteLLM не включилось разбиение на чанки.

### Измененные файлы
- `src/buratino/llm/client.py`
- `tests/unit/test_llm_client.py`

### Изменения
- Расширен детектор context overflow: он теперь распознает формулировку LiteLLM `exceeds the available context size`.
- Добавлен unit-тест на ошибку с реальной структурой сообщения от провайдера.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_llm_client.py tests/integration/test_ocr_fallback_path.py`
- Результат: успешно.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: не требовал обновления.

### Примечания
- После исправления overflow-ошибка должна переводить doc-level шаг в chunked retry вместо немедленного падения.

## 2026-06-05 16:35

### Запрос
Кратко: добавить в логирование вывод используемой `PRIMARY_MODEL`.

### Измененные файлы
- `src/buratino/cli/main.py`
- `tests/unit/test_cli.py`

### Изменения
- В стартовый лог `verify` добавлен фактически используемый `primary_model`.
- В batch-логирование добавлен `primary_model` для общего старта и запуска каждого `event_id`.
- Обновлен unit-тест CLI на новый формат строки логирования.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_cli.py`
- Результат: успешно.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: не требовал обновления.

### Примечания
- Изменение затрагивает только диагностические логи и не меняет логику верификации.

## 2026-06-05 17:05

### Запрос
Кратко: исправить human explanation для количественных проверок и убрать внутренние technical keys из пользовательского текста.

### Измененные файлы
- `src/buratino/report/status_explanation.py`
- `tests/unit/test_status_explanation.py`
- `tests/integration/test_cli_fail_closed_path.py`
- `docs/PRD.md`
- `docs/SPEC.md`

### Изменения
- Переписан formatter top-level explanations: сырые `found_signals` и `missing_requirements` больше не выводятся пользователю напрямую.
- Для quantitative event добавлено человекочитаемое сравнение планового количества и подтвержденного документом количества, включая кейс отсутствующего количества.
- Добавлены проверки на запрет technical keys в explanation и обновлены ожидания для human-readable PHR explanation.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_status_explanation.py`
- Выполнено: `uv run pytest tests/unit/test_cli.py tests/unit/test_status_explanation.py tests/integration/test_cli_fail_closed_path.py`
- Результат: успешно.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- Изменение затрагивает только presentation layer explanation formatter и не меняет внутренние `reasoning_trace` контракты.

## 2026-06-20 19:36

### Запрос
Кратко: изменить pipeline для OCR recall и добавить диагностируемость JSON/XLSX результата.

### Измененные файлы
- `src/buratino/app.py`
- `src/buratino/verifier/event_verifier.py`
- `src/buratino/verifier/phr_verifier.py`
- `src/buratino/verifier/document_ranking.py`
- `src/buratino/verifier/ocr_chunking.py`
- `src/buratino/llm/json_runner.py`
- `src/buratino/audit/service.py`
- `src/buratino/config/settings.py`
- `src/buratino/models/contracts.py`
- `src/buratino/report/xlsx_exporter.py`
- `src/buratino/report/batch_xlsx_exporter.py`
- `prompts/json_repair.md`
- `tests/unit/test_config.py`
- `tests/unit/test_report_contract.py`
- `tests/unit/test_document_ranking.py`
- `tests/integration/test_ocr_fallback_path.py`
- `tests/integration/test_malformed_llm_output.py`
- `tests/integration/test_diagnostic_reporting.py`
- `docs/PRD.md`
- `docs/SPEC.md`

### Изменения
- Добавлен `EVIDENCE_SOURCE_MODE`, включая режим `summary_then_ocr_on_negative` с обязательной OCR chunk re-check после отрицательного summary verdict.
- Добавлен общий strict JSON repair wrapper с 2 retry и fail-closed diagnostic result для ranking/doc-level/audit malformed JSON.
- Расширен report contract и XLSX export diagnostic/debug полями: ranking shortlist, used evidence source, rejected docs, audit change и error diagnostics.

### Проверка
- Выполнено: `uv run pytest tests/unit/test_config.py tests/unit/test_report_contract.py tests/unit/test_document_ranking.py tests/integration/test_ocr_fallback_path.py tests/integration/test_malformed_llm_output.py tests/integration/test_diagnostic_reporting.py tests/integration/test_cli_happy_path.py tests/integration/test_cli_fail_closed_path.py tests/integration/test_audit_logic_flip.py tests/integration/test_missing_phr_path.py`
- Результат: успешно.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- Итоговый JSON/XLSX теперь сохраняет error diagnostics вместо мгновенного падения шага на malformed/empty JSON.

## 2026-06-21 14:30

### Запрос
Кратко: перевести основной verify на OCR-only verdict, отключить влияние audit/date/relation на финальный статус и добавить deadline diagnostics в JSON/XLSX.

### Измененные файлы
- `src/buratino/app.py`
- `src/buratino/bootstrap.py`
- `src/buratino/config/settings.py`
- `src/buratino/models/contracts.py`
- `src/buratino/verifier/event_verifier.py`
- `src/buratino/verifier/phr_verifier.py`
- `src/buratino/verifier/deadline_enrichment.py`
- `src/buratino/report/xlsx_exporter.py`
- `src/buratino/report/batch_xlsx_exporter.py`
- `tests/unit/test_config.py`
- `tests/unit/test_report_contract.py`
- `tests/unit/test_cli.py`
- `tests/integration/test_malformed_llm_output.py`
- `tests/integration/test_ocr_fallback_path.py`
- `tests/integration/test_diagnostic_reporting.py`
- `tests/integration/test_cli_fail_closed_path.py`
- `tests/integration/test_cli_happy_path.py`
- `tests/integration/test_audit_logic_flip.py`
- `tests/integration/test_missing_phr_path.py`
- `docs/PRD.md`
- `docs/SPEC.md`

### Изменения
- Основной pipeline теперь подтверждает event/PHR только по OCR chunks; документы без OCR получают fail-closed diagnostic вместо summary verdict.
- Добавлены `AUDIT_ENABLED=false` и `RANKING_ENABLED=false` по умолчанию; audit больше не меняет итоговые статусы, а `logic_is_valid` помечается как `not_checked`.
- Добавлен отдельный deadline enrichment слой и новые top-level JSON/XLSX поля по срокам, OCR chunks и debug diagnostics.

### Проверка
- Выполнено: `uv run pytest -q`
- Результат: успешно.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- Date/deadline enrichment теперь рассчитывается только по `supporting_files` и не исключает файлы из подтверждения.

## 2026-06-21 19:25

### Запрос
Кратко: пересобрать `buratino-0.0.4` в независимый OCR-only pipeline-worker с jobs/results таблицами и общим analysis service.

### Измененные файлы
- `src/buratino/app.py`
- `src/buratino/bootstrap.py`
- `src/buratino/config/settings.py`
- `src/buratino/models/job.py`
- `src/buratino/models/result_contract.py`
- `src/buratino/repository/summaries.py`
- `src/buratino/repository/jobs.py`
- `src/buratino/repository/analysis_results.py`
- `src/buratino/service/analysis.py`
- `src/buratino/service/errors.py`
- `src/buratino/service/migrations.py`
- `src/buratino/worker/runner.py`
- `src/buratino/report/json_writer.py`
- `src/buratino/report/batch_xlsx_exporter.py`
- `src/buratino/report/buratino_xlsx_exporter.py`
- `src/buratino/cli/main.py`
- `src/buratino/__init__.py`
- `pyproject.toml`
- `migrations/0001_buratino_analysis_jobs.sql`
- `migrations/0002_buratino_event_analysis_results.sql`
- `tests/unit/test_config.py`
- `tests/unit/test_summary_repository.py`
- `tests/unit/test_result_contract_v2.py`
- `tests/unit/test_worker_runner.py`
- `tests/integration/fakes.py`
- `tests/integration/test_audit_logic_flip.py`
- `tests/integration/test_cli_fail_closed_path.py`
- `tests/integration/test_cli_happy_path.py`
- `tests/integration/test_diagnostic_reporting.py`
- `tests/integration/test_malformed_llm_output.py`
- `tests/integration/test_missing_phr_path.py`
- `tests/integration/test_ocr_fallback_path.py`
- `docs/PRD.md`
- `docs/SPEC.md`
- `docs/buratino_integration_contract.md`

### Изменения
- Вынесен общий `BuratinoAnalysisService`; CLI и worker используют один и тот же OCR-only pipeline.
- Добавлены SQL-миграции, job/result repositories, worker loop, `buratino worker` и `buratino migrate`.
- Введен новый `result_json` contract и новый XLSX-экспорт только по полям buratino.
- Summary-only документы исключены из verdict по default `EVIDENCE_SOURCE_MODE=ocr_only`.

### Проверка
- Выполнено: `uv run pytest -q`
- Результат: успешно.

### Документация
- PRD.md: обновлен.
- SPEC.md: обновлен.

### Примечания
- В текущей версии `BURATINO_MAX_CONCURRENCY` поддерживается только как `1`.
- `buratino` не пишет comparison/judge/manual verification результаты.

## 2026-06-21 20:05

### Запрос
Кратко: добавить локальный smoke/integration режим для нового worker flow без production DB и без реального LLM.

### Измененные файлы
- `src/buratino/llm/fake_client.py`
- `src/buratino/service/smoke.py`
- `src/buratino/bootstrap.py`
- `src/buratino/config/settings.py`
- `src/buratino/service/analysis.py`
- `src/buratino/worker/runner.py`
- `src/buratino/cli/main.py`
- `docker-compose.local.yml`
- `.env.smoke.example`
- `scripts/run_smoke.sh`
- `tests/unit/test_fake_llm_client.py`
- `tests/unit/test_cli.py`
- `tests/unit/test_config.py`
- `tests/unit/test_worker_runner.py`
- `README.md`
- `docs/SPEC.md`

### Изменения
- Добавлен deterministic fake LLM backend для `LLM_BACKEND=fake` / `BURATINO_FAKE_LLM=true`.
- Worker получил bounded run режимы `--once` и `--max-jobs`.
- Добавлены команды `seed-smoke-db` и `smoke-check`, а также локальные compose/env/script артефакты для smoke-прогона.
- Quantitative negative diagnostics теперь явно различают semantic-only кейс и below-plan кейс.

### Проверка
- Выполнено: `uv run pytest -q`
- Результат: успешно.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- Реальный docker smoke прогон не проверялся в этой среде; для локального запуска добавлен `bash scripts/run_smoke.sh`.

## 2026-06-21 20:40

### Запрос
Кратко: добавить integration worker check для старой OCR БД через Docker, debug enqueue/inspect/preflight и подробные логи.

### Измененные файлы
- `Dockerfile`
- `docker-compose.integration.yml`
- `.env.integration.example`
- `src/buratino/service/integration_debug.py`
- `src/buratino/cli/main.py`
- `src/buratino/config/settings.py`
- `src/buratino/bootstrap.py`
- `src/buratino/service/analysis.py`
- `src/buratino/worker/runner.py`
- `src/buratino/repository/jobs.py`
- `src/buratino/repository/analysis_results.py`
- `tests/unit/test_cli.py`
- `tests/unit/test_config.py`
- `tests/unit/test_integration_debug.py`
- `README.md`
- `docs/SPEC.md`
- `docs/integration_manual_worker_check.md`

### Изменения
- Добавлены команды `integration-preflight`, `enqueue-debug-job`, `inspect-job`.
- Добавлены guard `ALLOW_INTEGRATION_DEBUG_COMMANDS` и `--allow-debug` для ручного enqueue.
- Worker и `analyze_event()` теперь логируют startup/config/claim/load/save/fail стадии без паролей и без полного OCR.
- Добавлен Docker-based integration режим для старой dev/staging/copy БД с реальным OCR.

### Проверка
- Выполнено: `uv run pytest -q`
- Результат: ожидается после финальной сборки.

### Документация
- PRD.md: не требовал обновления.
- SPEC.md: обновлен.

### Примечания
- `LLM_BACKEND=openrouter` поддержан как alias поверх текущего LiteLLM path.
