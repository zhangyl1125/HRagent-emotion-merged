ALTER TABLE auth_whitelist ADD COLUMN IF NOT EXISTS created_by CITEXT;
ALTER TABLE auth_whitelist ADD COLUMN IF NOT EXISTS updated_by CITEXT;
ALTER TABLE auth_whitelist ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS llm_usage_events (
    id BIGSERIAL PRIMARY KEY,
    call_id UUID NOT NULL UNIQUE,
    trace_id UUID,
    user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    email_snapshot CITEXT,
    business_session_id TEXT,
    task_name TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    is_streaming BOOLEAN NOT NULL DEFAULT FALSE,
    input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
    reasoning_tokens BIGINT CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
    cached_tokens BIGINT CHECK (cached_tokens IS NULL OR cached_tokens >= 0),
    total_tokens BIGINT CHECK (total_tokens IS NULL OR total_tokens >= 0),
    usage_source TEXT NOT NULL CHECK (usage_source IN ('provider','estimated','unavailable')),
    status TEXT NOT NULL CHECK (status IN ('success','error','cancelled')),
    http_status INTEGER,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0,
    provider_request_id TEXT,
    error_code TEXT,
    usage_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created ON llm_usage_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_email_created ON llm_usage_events(email_snapshot, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model_created ON llm_usage_events(model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_task_created ON llm_usage_events(task_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_status_created ON llm_usage_events(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_session_created ON llm_usage_events(business_session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS api_request_events (
    id BIGSERIAL PRIMARY KEY, trace_id UUID, user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    email_snapshot CITEXT, method TEXT NOT NULL, route_template TEXT NOT NULL,
    status_code INTEGER NOT NULL, duration_ms INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_request_created ON api_request_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_request_user_created ON api_request_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_request_route_created ON api_request_events(route_template, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_request_status_created ON api_request_events(status_code, created_at DESC);

CREATE TABLE IF NOT EXISTS admin_action_audit_log (
    id BIGSERIAL PRIMARY KEY, trace_id UUID, actor_user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    actor_email CITEXT, action TEXT NOT NULL, target_email CITEXT, before_state JSONB,
    after_state JSONB, success BOOLEAN NOT NULL, reason TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_action_created ON admin_action_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_action_actor_created ON admin_action_audit_log(actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_action_target_created ON admin_action_audit_log(target_email, created_at DESC);
