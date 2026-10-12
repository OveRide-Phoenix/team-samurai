CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_schema_migrations (
    version text PRIMARY KEY,
    source_sha256 char(64) NOT NULL CHECK (length(source_sha256) = 64),
    applied_at bigint NOT NULL,
    receipt jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_workspaces (
    workspace_id uuid PRIMARY KEY,
    workspace_kind text NOT NULL CHECK (workspace_kind IN ('personal', 'shared')),
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL CHECK (updated_at >= created_at)
);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_workspace_memberships (
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    user_id text NOT NULL CHECK (length(user_id) > 0),
    role text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    authorization_epoch bigint NOT NULL DEFAULT 1 CHECK (authorization_epoch >= 1),
    active boolean NOT NULL DEFAULT true,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL CHECK (updated_at >= created_at),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_samurai_workspace_memberships_user
    ON "{{schema}}".samurai_workspace_memberships(user_id) WHERE active;

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_workspace_quotas (
    workspace_id uuid PRIMARY KEY REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    company_limit integer NOT NULL DEFAULT 10 CHECK (company_limit = 10),
    member_limit integer NOT NULL DEFAULT 10 CHECK (member_limit = 10),
    file_limit integer NOT NULL DEFAULT 100 CHECK (file_limit = 100),
    stored_bytes_limit bigint NOT NULL DEFAULT 104857600 CHECK (stored_bytes_limit = 104857600),
    per_file_bytes_limit bigint NOT NULL DEFAULT 10485760 CHECK (per_file_bytes_limit = 10485760),
    active_job_limit integer NOT NULL DEFAULT 3 CHECK (active_job_limit = 3),
    schedule_limit integer NOT NULL DEFAULT 20 CHECK (schedule_limit = 20),
    knowledge_chunk_limit integer NOT NULL DEFAULT 1000 CHECK (knowledge_chunk_limit = 1000),
    company_count integer NOT NULL DEFAULT 0 CHECK (company_count >= 0),
    member_count integer NOT NULL DEFAULT 1 CHECK (member_count >= 0),
    file_count integer NOT NULL DEFAULT 0 CHECK (file_count >= 0),
    stored_bytes bigint NOT NULL DEFAULT 0 CHECK (stored_bytes >= 0),
    active_job_count integer NOT NULL DEFAULT 0 CHECK (active_job_count >= 0),
    schedule_count integer NOT NULL DEFAULT 0 CHECK (schedule_count >= 0),
    knowledge_chunk_count integer NOT NULL DEFAULT 0 CHECK (knowledge_chunk_count >= 0),
    updated_at bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_companies (
    company_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    canonical_state jsonb NOT NULL CHECK (jsonb_typeof(canonical_state) = 'object'),
    state_sha256 char(64) NOT NULL CHECK (length(state_sha256) = 64),
    current_revision bigint NOT NULL CHECK (current_revision >= 0),
    legacy_owner_id text,
    legacy_session_id text,
    legacy_parent_session_id text,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL CHECK (updated_at >= created_at),
    CHECK ((legacy_owner_id IS NULL) = (legacy_session_id IS NULL)),
    CHECK ((legacy_session_id IS NULL) = (legacy_parent_session_id IS NULL)),
    UNIQUE (legacy_owner_id, legacy_session_id)
);
CREATE INDEX IF NOT EXISTS idx_samurai_companies_workspace
    ON "{{schema}}".samurai_companies(workspace_id);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_company_actor_bindings (
    company_id uuid NOT NULL REFERENCES "{{schema}}".samurai_companies(company_id),
    user_id text NOT NULL CHECK (length(user_id) > 0),
    parent_session_id text NOT NULL CHECK (length(parent_session_id) > 0),
    child_session_id text NOT NULL CHECK (length(child_session_id) > 0),
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL CHECK (updated_at >= created_at),
    PRIMARY KEY (company_id, user_id),
    UNIQUE (user_id, parent_session_id),
    UNIQUE (user_id, child_session_id)
);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_files (
    file_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    company_id uuid REFERENCES "{{schema}}".samurai_companies(company_id),
    created_by text NOT NULL,
    state text NOT NULL CHECK (state IN ('quarantined', 'ready', 'rejected', 'deleted')),
    display_name text NOT NULL,
    media_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size BETWEEN 0 AND 10485760),
    content_sha256 char(64) NOT NULL CHECK (length(content_sha256) = 64),
    storage_key text NOT NULL,
    rejection_code text,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    deleted_at bigint
);
CREATE INDEX IF NOT EXISTS idx_samurai_files_workspace_state
    ON "{{schema}}".samurai_files(workspace_id, state);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_file_deletion_receipts (
    receipt_id uuid PRIMARY KEY,
    file_id uuid NOT NULL REFERENCES "{{schema}}".samurai_files(file_id),
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    content_sha256 char(64) NOT NULL,
    deleted_by text NOT NULL,
    deleted_at bigint NOT NULL,
    purge_after bigint NOT NULL,
    retain_until bigint NOT NULL CHECK (retain_until >= purge_after)
);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_knowledge_chunks (
    chunk_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    company_id uuid REFERENCES "{{schema}}".samurai_companies(company_id),
    file_id uuid REFERENCES "{{schema}}".samurai_files(file_id),
    artifact_id uuid,
    source_revision bigint NOT NULL CHECK (source_revision >= 0),
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    created_at bigint NOT NULL,
    UNIQUE (workspace_id, content_sha256, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_samurai_knowledge_scope
    ON "{{schema}}".samurai_knowledge_chunks(workspace_id, company_id);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_learning_records (
    learning_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    user_id text NOT NULL,
    company_id uuid REFERENCES "{{schema}}".samurai_companies(company_id),
    kind text NOT NULL CHECK (kind IN ('preference', 'correction')),
    source_revision bigint NOT NULL CHECK (source_revision >= 0),
    founder_text text NOT NULL,
    created_by text NOT NULL,
    audit_sha256 char(64) NOT NULL,
    superseded_by uuid REFERENCES "{{schema}}".samurai_learning_records(learning_id),
    active boolean NOT NULL DEFAULT true,
    created_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samurai_learning_active
    ON "{{schema}}".samurai_learning_records(workspace_id, user_id, company_id) WHERE active;

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_schedules (
    schedule_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    company_id uuid NOT NULL REFERENCES "{{schema}}".samurai_companies(company_id),
    created_by text NOT NULL,
    creator_authorization_epoch bigint NOT NULL CHECK (creator_authorization_epoch >= 1),
    cadence text NOT NULL CHECK (cadence IN ('once', 'daily', 'weekly')),
    timezone text NOT NULL,
    action_kind text NOT NULL,
    payload jsonb NOT NULL,
    pinned_revision bigint NOT NULL CHECK (pinned_revision >= 0),
    enabled boolean NOT NULL DEFAULT true,
    next_run_at bigint NOT NULL,
    last_run_at bigint,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samurai_schedules_due
    ON "{{schema}}".samurai_schedules(next_run_at) WHERE enabled;

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_schedule_runs (
    schedule_id uuid NOT NULL REFERENCES "{{schema}}".samurai_schedules(schedule_id),
    scheduled_for bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('claimed', 'completed', 'failed', 'skipped')),
    result jsonb,
    error_code text,
    claimed_at bigint NOT NULL,
    completed_at bigint,
    PRIMARY KEY (schedule_id, scheduled_for)
);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_scenarios (
    scenario_id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES "{{schema}}".samurai_workspaces(workspace_id),
    company_id uuid NOT NULL REFERENCES "{{schema}}".samurai_companies(company_id),
    created_by text NOT NULL,
    company_revision bigint NOT NULL CHECK (company_revision >= 0),
    input_sha256 char(64) NOT NULL,
    inputs jsonb NOT NULL,
    created_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samurai_scenarios_company
    ON "{{schema}}".samurai_scenarios(company_id, company_revision);

CREATE TABLE IF NOT EXISTS "{{schema}}".samurai_scenario_runs (
    run_id uuid PRIMARY KEY,
    scenario_id uuid NOT NULL REFERENCES "{{schema}}".samurai_scenarios(scenario_id),
    label text NOT NULL CHECK (label IN ('low', 'base', 'high')),
    result jsonb NOT NULL,
    result_sha256 char(64) NOT NULL,
    provenance text NOT NULL DEFAULT 'synthetic_scenario_not_validation'
        CHECK (provenance = 'synthetic_scenario_not_validation'),
    created_at bigint NOT NULL,
    UNIQUE (scenario_id, label)
);

CREATE OR REPLACE FUNCTION "{{schema}}".samurai_mirror_company_to_legacy_session()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    matched integer;
BEGIN
    IF NEW.legacy_session_id IS NULL THEN
        RETURN NEW;
    END IF;
    UPDATE "{{schema}}".agno_sessions
    SET session_data = jsonb_set(
        jsonb_set(
            COALESCE(session_data, '{}'::jsonb),
            '{session_state}',
            COALESCE(session_data -> 'session_state', '{}'::jsonb),
            true
        ),
        '{session_state,company}',
        NEW.canonical_state,
        true
    )
    WHERE session_id = NEW.legacy_session_id
      AND user_id = NEW.legacy_owner_id;
    GET DIAGNOSTICS matched = ROW_COUNT;
    IF matched <> 1 THEN
        RAISE EXCEPTION 'legacy compatibility session is missing';
    END IF;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS samurai_company_legacy_mirror ON "{{schema}}".samurai_companies;
CREATE TRIGGER samurai_company_legacy_mirror
AFTER UPDATE OF canonical_state ON "{{schema}}".samurai_companies
FOR EACH ROW
WHEN (OLD.canonical_state IS DISTINCT FROM NEW.canonical_state)
EXECUTE FUNCTION "{{schema}}".samurai_mirror_company_to_legacy_session();
