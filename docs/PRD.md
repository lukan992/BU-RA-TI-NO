# PRD.md

## 1. Назначение проекта

`buratino` — локальный CLI-инструмент для проверки одного или нескольких `event_id` по данным из PostgreSQL и текстам документов, уже подготовленным в БД. Основной результат работы — machine-readable JSON; XLSX формируется как производный отчет.

## 2. Пользователи и роли

- Аналитик или оператор, который запускает проверку мероприятий по `event_id`.
- Разработчик или инженер сопровождения, который настраивает `.env`, prompts и batch-прогоны.

## 3. Основные сценарии

- Проверить одно мероприятие командой `verify`.
- Проверить список мероприятий командой `verify-list`.
- Получить по каждому мероприятию итог по факту мероприятия и по ПХР.
- Сформировать JSON-результаты и при необходимости общий XLSX-отчет с пользовательскими полями, deadline enrichment и debug diagnostics.

## 4. Функциональные требования

- Система должна отдельно проверять:
  - факт выполнения мероприятия;
  - факт выполнения ПХР.
- Итоговые verdicts должны быть только:
  - `подтверждено`;
  - `не подтверждено`.
- Если явного подтверждения нет, итог должен быть `не подтверждено`.
- Для doc-level анализа должна использоваться `PRIMARY_MODEL`.
- Основной verdict по мероприятию и ПХР должен формироваться только по OCR/OCR chunks.
- Summary можно использовать только для shortlist ranking и diagnostics; summary не может подтверждать итоговый статус.
- Audit по умолчанию отключен через `AUDIT_ENABLED=false`; при отключенном audit итоговые статусы не пересчитываются, а `logic_is_valid` помечается как `not_checked`.
- Ranking по умолчанию отключен через `RANKING_ENABLED=false`; при отключенном ranking анализируются все документы с OCR.
- Система должна поддерживать `EVIDENCE_SOURCE_MODE`, но в основном pipeline итоговое подтверждение опирается на OCR evidence.
- Doc-level анализ должен сохранять короткий structured evidence trace без свободного Chain-of-Thought.
- Итоговые поля `event_reasoning` и `phr_reasoning` должны быть короткими объяснениями для аналитика на русском языке без технических деталей внутренней обработки.
- Итоговый JSON и XLSX должны дополнительно содержать diagnostic fields: stage/reason, used evidence source, ranking shortlist/debug, OCR availability/chunks, error diagnostics для malformed JSON и deadline/date diagnostics.
- В пользовательских объяснениях нельзя показывать внутренние technical keys вроде `observed_quantity`, `found_signals`, `missing_requirements` и аналогичных кодов.
- Для количественного мероприятия объяснение должно явно сопоставлять плановый показатель и подтвержденное документом количество либо прямо указывать, что нужное количество в документе не подтверждено.
- `supporting_files` должны содержать только decision-significant OCR-файлы, реально повлиявшие на итоговое решение.
- Date/deadline enrichment должен выполняться только после формирования `supporting_files` и не должен менять `event_fact_status`, `phr_fact_status` или состав `supporting_files`.
- Для подтверждающих event-документов система должна дополнительно рассчитывать deadline status:
  - `on_time`;
  - `late`;
  - `document_date_missing`;
  - `deadline_missing`;
  - `not_checked`;
  - `ambiguous`.

## 5. Ограничения и правила

- Источник evidence для финального подтверждения — OCR; summary не должен повышать итоговый verdict даже если содержит подтверждающий текст.
- Structured evidence trace должен хранить только короткие evidence fragments, reason codes, missing requirements и short rationale; длинные рассуждения сохранять нельзя.
- Пользовательское объяснение статуса должно занимать 3-5 предложений и упоминать только decision-significant документы.
- Нельзя объединять event status и PHR status в один общий статус.
- XLSX не является источником истины; источником истины остается JSON.
- При malformed или empty JSON система должна сделать до двух repair retries строгим JSON-only prompt; если восстановление не удалось, итог должен остаться fail-closed и содержать диагностируемую ошибку в JSON/XLSX.
- Ошибка одного `event_id` в `verify-list` не должна останавливать обработку остальных ID.

## 6. Нерешенные вопросы

- Требует уточнения production-режим запуска и деплоя.
- Требует уточнения retry/backoff политика для transport/timeouts LiteLLM; malformed JSON repair для strict JSON уже реализован отдельно.
