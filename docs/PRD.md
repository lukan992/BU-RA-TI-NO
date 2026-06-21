# PRD.md

## 1. Назначение проекта

`buratino` — независимый pipeline-worker для OCR-only анализа одного мероприятия по данным из PostgreSQL. Он получает job, проверяет описание мероприятия, ПХР и план только по OCR, сохраняет собственный результат в БД и завершает job.

## 2. Пользователи и роли

- Внешний orchestrator или aggregator, который создает записи в `buratino_analysis_jobs`.
- Оператор или инженер, который запускает `buratino worker`, `verify`, `verify-list` и `migrate`.
- Сервис сравнения, который читает `buratino_event_analysis_results`, но не управляется из `buratino`.

## 3. Основные сценарии

- Внешний сервис создает pending job для `event_id` и при необходимости передает `report_id` / `result_value_id`.
- `buratino worker` claim-ит job, выполняет OCR-only анализ и сохраняет `result_json`.
- `buratino verify` использует тот же анализатор локально и пишет JSON/XLSX только как вспомогательные CLI-артефакты.
- `buratino verify-list` пакетно запускает тот же analysis service для нескольких `event_id`.

## 4. Функциональные требования

- `buratino` должен сохранять независимый результат pipeline без финального решения за всю систему.
- Бизнес-статусы должны использовать только значения:
  - `Подтверждено`
  - `Не подтверждено`
  - `Не применимо`
  - `Не проверялось`
- Проверки должны формироваться отдельно по:
  - `event_description_status`
  - `phr_status`
  - `plan_status`
- Применимость плановой проверки определяется наличием планового значения в `xlsx_events`, а не классификацией типа мероприятия моделью: если `planned_value` задан и положителен, `plan_status` не может быть `Не применимо`. `Не применимо` допускается только при отсутствующем или нулевом `planned_value`.
- Для мероприятия с плановым значением `event_description_status` подтверждается только вместе с подтверждением плана: при `plan_status = Не подтверждено` статус описания тоже `Не подтверждено`. Нельзя иметь `event_description_status = Подтверждено` при `plan_status = Не применимо`, если `planned_value` задан.
- Для планового значения 1 единица подтверждением плана считается OCR-подтверждение факта создания результата/выполнения события (достижение 1 единицы). Для значения больше 1 требуется фактическое значение, не ниже планового.
- Если OCR нет ни в одном связанном документе, job должна завершаться business-результатом `Не подтверждено` с диагностикой `OCR отсутствует`.
- Summary может использоваться только как diagnostics/debug; summary не может быть evidence для verdict.
- `buratino` не должен вычислять подписи, регионы, сроки, judge-result, manual verification и финальное `Подтверждено`.

## 5. Ожидаемый результат

- Основной артефакт: `result_json` с `pipeline_name`, `pipeline_version`, `statuses`, `expected`, `facts`, `supporting_files`, `evidence_items`, `diagnostics`, `model_info`.
- Для успешной worker-job дополнительно создается строка в `buratino_event_analysis_results`.
- CLI-XLSX должен отражать только buratino-поля: описание мероприятия, ПХР, план, supporting files, diagnostic reason и путь к JSON.

## 6. Ошибочные сценарии

- Retryable ошибки worker: временный сбой LLM/сети/БД, malformed JSON после repair retries.
- Non-retryable ошибки worker: битый payload, отсутствующий `event_id`, неконсистентный result contract.
- Если результат анализа невалиден, worker не должен помечать job как `completed`.

## 7. Ограничения и правила

- Источник evidence для verdict — только OCR.
- `AUDIT_ENABLED=false`, `RANKING_ENABLED=false`, `SUMMARY_VERDICT_ENABLED=false`, `DATE_CHECK_ENABLED=false` по умолчанию.
- `buratino` не пишет в comparison/judge таблицы.
- JSON является источником истины; XLSX — производный CLI-отчет.

## 8. Нерешенные вопросы

- Требует уточнения production deployment и внешний lifecycle создания jobs.
- Требует уточнения отдельная operational policy для retry/backoff на уровне orchestrator.
