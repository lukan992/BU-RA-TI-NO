# AGENTS.md

## Project overview
This repository contains `buratino`, a local Python CLI tool for verifying one event by document summaries from PostgreSQL.

Current MVP scope:
- verify one `event_id`
- load event data from PostgreSQL
- load document summaries
- verify:
  - event fact
  - PHR fact
- run second-model audit
- save result to JSON
- optionally export XLSX

Do not expand scope unless explicitly asked.
Non-goals for current stage:
- batch processing
- UI
- OCR as primary source
- full reranking
- legal automation

---

## Product rules
Always preserve these business rules:

1. Verdicts are binary only:
   - `подтверждено`
   - `не подтверждено`

2. Decision policy is fail-closed:
   - if there is no explicit confirmation, result must be `не подтверждено`

3. Event fact and PHR fact are separate checks and must not be merged into one status.

4. Use two different models:
   - `PRIMARY_MODEL` for document analysis
   - `AUDIT_MODEL` for result audit

5. If either model is missing in `.env`, treat it as configuration error.

6. Prompt files live in `prompts/` and must be treated as first-class project artifacts.

7. Current MVP works on `summary_text`.
   Architecture should stay compatible with future OCR-based source replacement.

---

## Repo expectations
Prefer this structure unless the repo already contains an accepted alternative:

- `src/buratino/`
- `tests/unit/`
- `tests/integration/`
- `prompts/`
- `docs/`
- `output/`

Keep business logic out of CLI glue code.
Prefer small modules with explicit contracts.

Recommended layers:
- config
- models / schemas
- repository
- target builder
- verifier
- audit
- report/export
- cli

---

## Coding rules
- Use Python.
- Prefer clear, boring, testable code over clever abstractions.
- Add type hints for public functions and core domain logic.
- Keep side effects at the edges.
- Avoid hidden global state.
- Do not hardcode model names, DB credentials, or paths that belong in config.
- Prefer deterministic behavior and explicit error handling.
- Preserve stable JSON contracts once introduced.
- Do not introduce silent fallback logic for invalid LLM output.

---

## LLM rules
- All prompt outputs must be strict JSON when the prompt requires JSON.
- Fail on malformed JSON; do not invent repaired meaning silently.
- Do not allow the audit model to ignore evidence constraints.
- Evidence must be tied to actual source document data passed into the step.
- No hallucinated values, units, files, or reasoning.
- Prefer smaller, explicit schemas over loose free-form responses.

---

## Verification rules
### Event type
- `planned_value = 0` => qualitative
- `planned_value > 1` => quantitative
- `planned_value = 1` => requires explicit type decision logic

### Quantitative confirmation
Confirm only when all needed signals are present:
- action found
- subject found
- number found
- unit found
- observed >= planned

### Qualitative confirmation
Confirm only when there is a direct fact of execution.

Do not count as confirmation:
- plans
- intentions
- forecasts

### PHR
PHR is always quantitative.

---

## Data handling rules
Primary working source in MVP:
- document summaries from DB

Event sources:
- `public.xlsx_events`
- `public.xlsx_event_phr`

Do not invent missing DB fields.
If data required by the contract is absent, return a clear error.

---

## Output contract rules
The final result must remain machine-readable.
JSON output is the primary artifact.
XLSX is a derived artifact built from the verified result, not a separate source of truth.

At minimum preserve:
- event identifiers
- event type
- event fact status
- phr fact status
- primary files
- logic audit validity
- model names
- reasoning/evidence at document level if required by current contract

---

## Testing and validation
Before considering work done:

1. Run unit tests.
2. Run integration tests if the change affects DB access, CLI, or end-to-end flow.
3. Validate at least one happy path and one fail-closed path.
4. Validate malformed LLM output handling.
5. Validate missing model configuration handling.
6. Validate JSON contract stability.

If tests do not exist yet, add the smallest relevant tests for the change.

---

## Commands
Prefer `uv` for Python environment and dependency management.

Common workflow:
- install dependencies
- run tests
- run lint/format if configured
- run CLI verify for one `event_id`

If the exact command is missing, inspect the repository first and use the existing project standard instead of inventing a new one.

---

## Change policy
For substantial tasks:
1. first inspect existing code
2. then make a short implementation plan
3. then implement
4. then run relevant checks
5. then summarize what changed and any remaining risks

Do not perform broad refactors unless they are required for the requested task.

---

## What done means
A task is done only if:
- code matches current MVP scope
- business rules above are preserved
- relevant tests pass or are added
- CLI behavior remains reproducible
- JSON contract remains clear and stable
- prompts/config/docs are updated when behavior changes