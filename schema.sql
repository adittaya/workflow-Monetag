-- Monetag Proxy State — shared blacklist for used/dead proxies
-- Run this in Supabase SQL Editor to create the monetag_proxy_state table.

CREATE TABLE IF NOT EXISTS monetag_proxy_state (
  id BIGSERIAL PRIMARY KEY,
  ip TEXT NOT NULL,
  port INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('used', 'dead')),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_monetag_proxy_state_lookup
  ON monetag_proxy_state (ip, port, state, expires_at);
CREATE INDEX IF NOT EXISTS idx_monetag_proxy_state_cleanup
  ON monetag_proxy_state (expires_at);

-- Auto-cleanup function: delete expired rows
CREATE OR REPLACE FUNCTION cleanup_monetag_proxy_state()
RETURNS void AS $$
  DELETE FROM monetag_proxy_state WHERE expires_at < now();
$$ LANGUAGE sql;

-- Cleanup trigger: auto-clean on every INSERT
CREATE OR REPLACE FUNCTION trigger_cleanup_monetag_proxy_state()
RETURNS TRIGGER AS $$
BEGIN
  DELETE FROM monetag_proxy_state WHERE expires_at < now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS auto_cleanup_monetag_proxy_state ON monetag_proxy_state;
CREATE TRIGGER auto_cleanup_monetag_proxy_state
  AFTER INSERT ON monetag_proxy_state
  FOR EACH STATEMENT
  EXECUTE FUNCTION trigger_cleanup_monetag_proxy_state();

-- RLS policies
ALTER TABLE monetag_proxy_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_monetag_proxy_state" ON monetag_proxy_state;
CREATE POLICY "service_role_all_monetag_proxy_state"
  ON monetag_proxy_state FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "anon_read_monetag_proxy_state" ON monetag_proxy_state;
CREATE POLICY "anon_read_monetag_proxy_state"
  ON monetag_proxy_state FOR SELECT
  TO anon
  USING (true);

-- Ensure the proxy_results table has a monetag health-check column
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS monetag_ok BOOLEAN NOT NULL DEFAULT false;
