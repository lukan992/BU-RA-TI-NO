create extension if not exists pgcrypto;

create table if not exists buratino_event_analysis_results (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references buratino_analysis_jobs(id),
    event_id bigint not null,
    report_id bigint null,
    result_value_id bigint null,
    pipeline_name text not null default 'buratino',
    pipeline_version text null,
    event_name text null,
    event_description_status text not null,
    event_description_expected text null,
    event_description_fact text null,
    phr_status text not null,
    phr_expected text null,
    phr_fact text null,
    plan_status text not null,
    plan_expected text null,
    plan_fact text null,
    supporting_files text null,
    supporting_document_ids jsonb not null default '[]'::jsonb,
    evidence_items jsonb not null default '[]'::jsonb,
    diagnostic_reason text null,
    result_json jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_buratino_event_analysis_results_event_id
on buratino_event_analysis_results (event_id);

create index if not exists idx_buratino_event_analysis_results_job_id
on buratino_event_analysis_results (job_id);
