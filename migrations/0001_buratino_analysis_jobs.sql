create extension if not exists pgcrypto;

create table if not exists buratino_analysis_jobs (
    id uuid primary key default gen_random_uuid(),
    event_id bigint not null,
    report_id bigint null,
    result_value_id bigint null,
    status text not null default 'pending',
    priority integer not null default 0,
    payload jsonb not null default '{}'::jsonb,
    result_payload jsonb null,
    attempts integer not null default 0,
    max_attempts integer not null default 3,
    available_at timestamptz not null default now(),
    claimed_by text null,
    claimed_at timestamptz null,
    lease_expires_at timestamptz null,
    last_error text null,
    error_type text null,
    error_stage text null,
    correlation_id text null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz null
);

create index if not exists idx_buratino_analysis_jobs_claim
on buratino_analysis_jobs (status, available_at, priority desc, created_at);

create index if not exists idx_buratino_analysis_jobs_event_id
on buratino_analysis_jobs (event_id);

create index if not exists idx_buratino_analysis_jobs_correlation_id
on buratino_analysis_jobs (correlation_id);

create unique index if not exists uq_buratino_analysis_jobs_active_event
on buratino_analysis_jobs (event_id, coalesce(result_value_id, -1))
where status in ('pending', 'claimed');
