-- Monetag Proxy System — run this in Supabase SQL Editor.

-- ══════════════════════════════════════════════════════════════
-- 1. proxy_results — the proxy pool
--    The rotator queries rows where monetag_ok = true (premium tier),
--    sorted by latency_ms, and DELETEs dead rows via the service key.
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS proxy_results (
  id BIGSERIAL PRIMARY KEY,
  ip TEXT NOT NULL,
  port INTEGER NOT NULL,
  proto TEXT DEFAULT 'http',
  country TEXT,
  latency_ms INTEGER DEFAULT 9999,
  monetag_ok BOOLEAN NOT NULL DEFAULT false,
  e2_ok BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ip, port)
);

-- Self-heal: if proxy_results already existed without these columns, add them.
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS proto TEXT DEFAULT 'http';
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS country TEXT;
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS latency_ms INTEGER DEFAULT 9999;
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS monetag_ok BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS e2_ok BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE proxy_results ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_proxy_results_lookup
  ON proxy_results (monetag_ok, latency_ms);

-- RLS policies for proxy_results
ALTER TABLE proxy_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_proxy_results" ON proxy_results;
CREATE POLICY "service_role_all_proxy_results"
  ON proxy_results FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "anon_read_proxy_results" ON proxy_results;
CREATE POLICY "anon_read_proxy_results"
  ON proxy_results FOR SELECT
  TO anon
  USING (true);

-- ══════════════════════════════════════════════════════════════
-- 2. monetag_proxy_state — shared blacklist for used/dead proxies
-- ══════════════════════════════════════════════════════════════

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

-- ══════════════════════════════════════════════════════════════
-- 3. How to fill the pool — insert your proxy list here:
-- ══════════════════════════════════════════════════════════════

-- INSERT INTO proxy_results (ip, port, proto, country, latency_ms, monetag_ok, e2_ok) VALUES
--   ('1.2.3.4', 8080, 'http', 'US', 150, true, true),
--   ('5.6.7.8', 3128, 'http', 'DE', 200, true, false);

-- Set a row's premium flag (or set e2_ok=true for the normal tier):
-- UPDATE proxy_results SET monetag_ok = true WHERE ip = '1.2.3.4' AND port = 8080;
