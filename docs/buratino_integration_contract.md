# buratino integration contract

## Result JSON

`buratino` публикует независимый pipeline result в формате:

```json
{
  "pipeline_name": "buratino",
  "pipeline_version": "0.1.0",
  "event_id": 123,
  "report_id": null,
  "result_value_id": null,
  "event_name": "string",
  "statuses": {
    "event_description_status": "Подтверждено",
    "phr_status": "Не применимо",
    "plan_status": "Подтверждено"
  },
  "expected": {
    "event_description": "string",
    "phr": null,
    "plan": "2 ед"
  },
  "facts": {
    "event_description_fact": "короткий OCR-фрагмент",
    "phr_fact": null,
    "plan_fact": "2 ед"
  },
  "supporting_files": [],
  "evidence_items": [],
  "diagnostics": {
    "evidence_source_used": "ocr",
    "ocr_available": true,
    "analyzed_files": [],
    "skipped_files": [],
    "diagnostic_reason": "string"
  },
  "model_info": {
    "primary_model": "string",
    "ranking_model": null,
    "audit_model": null
  }
}
```

## Result tables

- `buratino_analysis_jobs` — входной queue/lease state.
- `buratino_event_analysis_results` — успешные pipeline results.

`buratino` пишет строку в `buratino_event_analysis_results` только после успешной валидации `result_json`.

## Non-goals

`buratino` не пишет:

- signature results
- region results
- deadline results
- pipeline comparison results
- judge results
- final manual verification state

## Downstream comparison

Предполагаемый downstream слой может хранить агрегированный результат отдельно:

```sql
pipeline_comparison_results (
    id uuid primary key,
    event_id bigint not null,
    buratino_result_id uuid null,
    ivan_result_id uuid null,
    comparison_status text not null,
    conflict boolean not null,
    judge_status text null,
    judge_result_json jsonb null,
    final_status text null,
    manual_verification_required boolean not null default false,
    created_at timestamptz not null default now()
)
```

`buratino` не должен писать в эту таблицу.
