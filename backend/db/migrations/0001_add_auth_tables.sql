CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email CITEXT NOT NULL UNIQUE,
    display_name VARCHAR(120),
    password_hash TEXT,
    auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',
    provider_subject VARCHAR(255),
    role VARCHAR(30) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_email_verified BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT app_users_auth_provider_check CHECK (auth_provider IN ('local', 'oidc'))
);

CREATE TABLE IF NOT EXISTS auth_whitelist (
    email CITEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO auth_whitelist (email, enabled, note)
VALUES
  ('aah5sgh@bosch.com', TRUE, 'initial whitelist'),
  ('uay4sgh@bosch.com', TRUE, 'initial whitelist')
ON CONFLICT (email) DO UPDATE SET enabled = EXCLUDED.enabled;

CREATE TABLE IF NOT EXISTS auth_audit_log (
    id BIGSERIAL PRIMARY KEY,
    email CITEXT,
    event_type VARCHAR(40) NOT NULL,
    success BOOLEAN NOT NULL,
    reason VARCHAR(120),
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_email_created ON auth_audit_log(email, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_oidc_subject
ON app_users(auth_provider, provider_subject)
WHERE provider_subject IS NOT NULL;
