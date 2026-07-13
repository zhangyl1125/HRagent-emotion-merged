-- Bind workflow sessions to authenticated users for multi-user, multi-session isolation.
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES app_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated
  ON sessions(owner_user_id, updated_at DESC);
