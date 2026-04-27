# Product Requirements Document

## Buratino

**Статус:** implemented MVP  
**Версия:** 0.0.6  
**Область:** локальный Python CLI для верификации одного мероприятия по summary документов из PostgreSQL с fallback на OCR

---

## 1. Summary

`buratino` — локальный CLI-инструмент для проверки одного мероприятия.

Система:
- загружает карточку мероприятия из PostgreSQL;
- загружает ПХР, если он задан;
- сначала пытается загрузить summaries документов;
- если для документа summary отсутствует, использует OCR как fallback evidence source;
- проверяет факт выполнения мероприятия;
- отдельно проверяет ПХР, если он есть;
- выполняет logic audit второй LLM-моделью;
- сохраняет итог в JSON;
- опционально экспортирует XLSX из итогового JSON.

Primary evidence source в текущей версии:
- `summary_text`, если он существует для документа;
- OCR-текст из `ocr_results`, если summary для документа отсутствует.

OCR больше не рассматривается только как future extension. Он используется как резервный источник evidence для документов без summary.

---

## 2. Goals

- Проверка одного CLI input id.
- Работа с одной PostgreSQL БД `buratino_runtime_v2`.
- Загрузка event/PHR данных из `xlsx_events` и `xlsx_event_phr`.
- Загрузка evidence через `documents` → `document_summary_results`, а при отсутствии summary — через `ocr_results`.
- Раздельная проверка:
  - факта мероприятия;
  - ПХР, если ПХР задан.
- Binary verdict for event fact:
  - `подтверждено`;
  - `не подтверждено`.
- Ternary verdict for PHR fact:
  - `подтверждено`;
  - `не подтверждено`;
  - `не указано`.
- Fail-closed policy для event и для ПХР, если ПХР задан.
- Strict JSON parsing для LLM outputs.
- JSON как primary artifact.
- XLSX как derived artifact.
- Консольное логирование этапов через `loguru`.

---

## 3. Non-Goals

- Batch processing.
- UI.
- Полноценный reranking.
- Legal automation.
- Автоматическое восстановление failed summaries.
- Page-level OCR arbitration.

---

## 4. Data Sources

### 4.1 PostgreSQL

Текущая конфигурация использует одну БД.

```env
DATABASE_URL=postgresql://...
```

Если заданы `MAIN_DATABASE_URL` и/или `RUNTIME_DATABASE_URL`, они переопределяют `DATABASE_URL`, но для текущей установки это не требуется.

Основные таблицы MVP:
- `public.xlsx_events` — карточки мероприятий из XLSX.
- `public.xlsx_event_phr` — ПХР из XLSX.
- `public.documents` — документы и связь с проверяемым id.
- `public.document_summary_results` — summaries документов.
- `public.ocr_results` — OCR-текст документов.

Дополнительные OCR-related таблицы могут существовать, но для текущего fallback достаточно `public.ocr_results`.

### 4.2 Event Lookup

CLI принимает id, который может соответствовать:
- `xlsx_events.event_id`;
- `xlsx_events.result_value_id`;
- `documents.event_id`.

Карточка мероприятия ищется в `xlsx_events` по:

```sql
xlsx_events.event_id = :input_id
OR xlsx_events.result_value_id = :input_id
```

В финальном JSON сохраняется canonical `xlsx_events.event_id`.

### 4.3 Evidence Lookup

Evidence загружается по схеме:

```sql
documents.event_id = :input_id
documents.id = document_summary_results.document_id
documents.id = ocr_results.document_id
```

Правило выбора источника для каждого документа:
1. если есть непустой `document_summary_results.summary_text`, использовать его;
2. если summary отсутствует или пустой, пытаться использовать OCR из `ocr_results`;
3. если для документа отсутствуют и summary, и OCR, документ не может быть использован как evidence source;
4. если по мероприятию нет ни одного документа с usable summary или OCR, verifier возвращает явную ошибку данных.

Repository должен возвращать для каждого документа:
- `document_id`
- `file_name`
- `evidence_text`
- `evidence_source`, где значение одно из:
  - `summary`
  - `ocr`

---

## 5. Configuration

Минимальная `.env`-конфигурация:

```env
PRIMARY_MODEL=openai/gemma-4-e4b
AUDIT_MODEL=openai/<working-audit-model>

DATABASE_URL=postgresql://admin:***@10.14.49.42:30096/buratino_runtime_v2

LLM_API_BASE=http://10.14.49.32:30098
LLM_API_KEY=...
LLM_TIMEOUT_SECONDS=300
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=1000
MAX_DOCUMENTS_TO_ANALYZE=3
LOG_LEVEL=INFO
```

Обязательные переменные:
- `PRIMARY_MODEL`;
- `AUDIT_MODEL`;
- `DATABASE_URL` или оба `MAIN_DATABASE_URL`/`RUNTIME_DATABASE_URL`.

Опциональные переменные:
- `MAIN_DB_SCHEMA`, default `public`;
- `RUNTIME_DB_SCHEMA`, default `public`;
- `PROMPTS_DIR`, default `prompts`;
- `OUTPUT_DIR`, default `output`;
- `LLM_BACKEND`, default `litellm`;
- `LLM_API_BASE`;
- `LLM_API_KEY`;
- `LLM_TIMEOUT_SECONDS`, default `120`;
- `LLM_TEMPERATURE`, default `0`;
- `LLM_MAX_TOKENS`;
- `MAX_DOCUMENTS_TO_ANALYZE`;
- `LOG_LEVEL`, default `INFO`.

---

## 6. Pipeline

1. CLI validation.
2. Загрузка settings из `.env`.
3. Настройка `loguru`.
4. Загрузка мероприятия.
5. Загрузка ПХР.
   Если ПХР не найден, pipeline продолжается, а ПХР фиксируется как не заданный.
6. Загрузка документов.
7. Для каждого документа:
   - попытка взять `summary_text`;
   - при отсутствии summary — fallback на OCR из `ocr_results`.
8. Отбрасывание документов без usable evidence text.
9. Reranking no-op.
10. Опциональное ограничение числа документов через `MAX_DOCUMENTS_TO_ANALYZE`.
11. Построение event target:
   - action;
   - subject;
   - planned_value;
   - unit;
   - event_type.
12. Построение PHR target, если ПХР задан.
13. Doc-level LLM-анализ event fact по `evidence_text`.
14. Doc-level LLM-анализ PHR по `evidence_text`, если ПХР задан.
15. Aggregation.
16. Logic audit.
17. Финальный JSON.
18. XLSX export, если CLI запущен с `--xlsx`.

---

## 7. Event Type

- `planned_value = 0` → `qualitative`.
- `planned_value > 1` → `quantitative`.
- `planned_value = 1` → определяется отдельным LLM prompt `event_type_resolution.md`.

Если LLM возвращает malformed JSON или значение вне схемы, verifier завершается ошибкой.

---

## 8. Verification Rules

### 8.1 Quantitative Event

Подтверждение допускается только если есть все сигналы:
- найдено действие;
- найден субъект;
- есть фактический completion signal;
- найдено число;
- найдена единица;
- `observed >= planned`.

### 8.2 Qualitative Event

Подтверждение допускается только при прямом факте выполнения.

Не считаются подтверждением:
- планы;
- намерения;
- прогнозы;
- целевые формулировки без факта выполнения.

### 8.3 PHR

PHR всегда количественный.

Если ПХР задан, подтверждение допускается только если одновременно выполнены все условия:
- найден нужный показатель;
- явно найдена требуемая характеристика объекта;
- `characteristic_explicitly_matched = true`;
- найдено фактическое число, относящееся именно к объекту метрики;
- `quantity_refers_to_metric_object = true`;
- найдена единица, относящаяся к этому же числу;
- `observed >= target`.

Не допускается подтверждение ПХР, если:
- подтвержден только родовой объект без нужной характеристики;
- число относится к другой сущности, например к филиалам, регионам, организациям или получателям;
- характеристика выведена по смыслу, но не подтверждена текстом;
- в документе есть только общий факт закупки/поставки без указания нужного типа объекта.

Если ПХР не задан в `xlsx_event_phr`, итог должен быть:
- `phr_fact_status = "не указано"`;
- `phr_reasoning = "Для мероприятия ПХР не задан, поэтому проверка ПХР не выполнялась."`;
- `phr_documents = []`.

Если ПХР задан, но evidence недостаточен, ambiguous или отсутствует, verifier должен fail-closed вернуть `не подтверждено`.

---

## 9. LLM Processing

### 9.1 Prompt Assets

Промпты лежат в `prompts/`:

- `event_fact_summary.md`;
- `phr_fact_summary.md`;
- `logic_audit.md`;
- `event_type_resolution.md`.

Требования:
- JSON only;
- строгая схема;
- no hallucination;
- fail-closed.

### 9.2 Model Usage

- `PRIMARY_MODEL` используется для:
  - `event_fact_summary.md`;
  - `phr_fact_summary.md`;
  - `event_type_resolution.md`.
- `AUDIT_MODEL` используется для:
  - `logic_audit.md`.

### 9.3 Evidence Input Contract

Для doc-level event/PHR prompts verifier передает:
- `document_id`
- `file_name`
- `evidence_source`
- `evidence_text`

`evidence_source` обязателен и принимает значения:
- `summary`
- `ocr`

Промпты должны использовать только `evidence_text` как источник фактов и могут кратко упоминать `evidence_source` в reasoning.

### 9.4 Strict JSON

LLM output должен быть валидным JSON с точным набором ключей. Лишние ключи, отсутствующие ключи и malformed JSON считаются ошибкой.

Для doc-level PHR результата обязательна следующая схема:

```json
{
  "document_id": "string or null",
  "file_name": "string",
  "phr_fact_status": "подтверждено | не подтверждено",
  "reasoning": "3-4 sentences grounded only in evidence_text",
  "metric_matched": "string | null",
  "characteristic_explicitly_matched": true,
  "quantity_refers_to_metric_object": true,
  "observed_value": "number | string | null",
  "observed_unit": "string | null",
  "comparison_result": "meets_target | below_target | insufficient_data",
  "evidence_quote": "short exact quote from evidence_text or null"
}
```

Семантические ограничения для этой схемы:
- если `characteristic_explicitly_matched = false`, тогда `phr_fact_status` обязан быть `не подтверждено`;
- если `quantity_refers_to_metric_object = false`, тогда `phr_fact_status` обязан быть `не подтверждено`.

Для doc-level event результата reasoning тоже должен быть 3-4 предложениями и объяснять, на каком evidence и по каким сигналам сделан вывод.

---

## 10. JSON Output

Минимальные верхнеуровневые поля:

```json
{
  "event_id": 0,
  "event_name": "",
  "event_type": "qualitative",
  "event_fact_status": "не подтверждено",
  "phr_fact_status": "не указано",
  "event_primary_file": null,
  "phr_primary_file": null,
  "logic_is_valid": true,
  "primary_model": "",
  "audit_model": "",
  "event_reasoning": "",
  "phr_reasoning": "",
  "detected_errors": [],
  "event_documents": [],
  "phr_documents": [],
  "supporting_files": [],
  "audit_reasoning": ""
}
```

Требования к верхнеуровневому reasoning:
- `event_reasoning` должен состоять из 3-4 предложений;
- `phr_reasoning` должен состоять из 3-4 предложений, если ПХР задан;
- если ПХР не задан, `phr_reasoning` должен явно сообщать, что ПХР отсутствует и поэтому не проверялся;
- reasoning должен объяснять, на основе какого evidence source (`summary` или `ocr`), какого документа и каких ключевых сигналов был сделан вывод;
- reasoning не должен быть однофразовым и не должен ограничиваться формулировкой вроде "явного подтверждения не найдено".

`phr_documents` должен содержать элементы, соответствующие doc-level PHR schema из раздела 9.4.

JSON является primary artifact. XLSX строится только из итогового report object.

---

## 11. Error Handling

Явные ошибки:
- нет event в `xlsx_events`;
- нет документов;
- документы найдены, но у всех отсутствуют и summaries, и OCR;
- все usable evidence texts пустые;
- отсутствуют обязательные таблицы;
- отсутствуют обязательные колонки;
- ошибка подключения к БД;
- ошибка LLM transport;
- LLM timeout;
- malformed JSON;
- JSON schema mismatch;
- нет `PRIMARY_MODEL`;
- нет `AUDIT_MODEL`;
- invalid configuration values.

Отсутствие ПХР не считается fatal error. Это фиксируется в результате как `phr_fact_status = "не указано"`.

---

## 12. Logging

CLI выводит этапы в консоль через `loguru`.

Логируются:
- старт проверки;
- загрузка event;
- загрузка/отсутствие ПХР;
- загрузка summaries;
- fallback на OCR для документов без summary;
- количество документов;
- ограничение `MAX_DOCUMENTS_TO_ANALYZE`;
- построение target;
- запуск LLM по каждому документу;
- источник evidence для каждого документа (`summary` или `ocr`);
- результат LLM по каждому документу;
- aggregation;
- logic audit;
- запись JSON/XLSX.

Секреты, DB URL, API key, большие summary-тексты и большие OCR-тексты в INFO-логах не выводятся.

---

## 13. Success Criteria

- CLI запускается командой:

```bash
uv run buratino verify <event_id>
```

- Для валидного мероприятия с summaries и/или OCR создается JSON в `output/`.
- `--xlsx` создает XLSX.
- Event fact и PHR fact остаются отдельными статусами.
- Event verdicts binary only.
- `phr_fact_status` использует:
  - `подтверждено`
  - `не подтверждено`
  - `не указано`
- Если summary отсутствует, verifier использует OCR fallback без ручного вмешательства.
- Fail-closed policy сохраняется для event и для заданного ПХР.
- Malformed LLM JSON не исправляется молча.
- Logs показывают текущий этап выполнения.
- Unit/integration tests проходят.
- PHR не подтверждается по общему объекту без нужной характеристики.
- PHR не подтверждается, если число относится к получателям, филиалам, регионам или другой сущности вместо объекта метрики.
- Верхнеуровневые reasoning поля содержат 3-4 предложения с объяснением основания вывода.

---

## 14. Current Operational Notes

- `MAX_DOCUMENTS_TO_ANALYZE` нужен как временный operational throttle, потому что полноценный reranking еще не реализован.
- Если `MAX_DOCUMENTS_TO_ANALYZE` задан, анализируется только первые N документов из repository order.
- Для production-quality проверки нужно заменить no-op reranking на осмысленный отбор документов.
- OCR fallback используется только для документов, у которых отсутствует usable summary.
- Если для одного документа доступны и summary, и OCR, приоритет остается за summary.

---

## 15. Risks

- Summary может быть неполным.
- OCR может содержать шум, ошибки распознавания и ложные числа.
- Summary и OCR для разных документов могут иметь разное качество.
- Summary может не содержать явного указания на требуемую характеристику объекта.
- LiteLLM endpoint/model alias может зависать или timeout-иться.
- Без reranking ограничение документов может пропустить подтверждающий файл.
- Более длинные reasoning поля в 3-4 предложения увеличивают риск многословия, поэтому prompts должны требовать конкретику, а не общие фразы.

---

## 16. Future

- OCR evidence source как полноценный first-class input без fallback semantics.
- Reranking документов.
- Parallel LLM calls.
- Better progress reporting with timings.
- Batch processing.
- UI.
- Confidence scoring.
- Page-level OCR evidence.
