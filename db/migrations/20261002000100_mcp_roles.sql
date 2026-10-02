-- migrate:up
-- MCP servers (plan Phase 4): each server has its own role, holding only what it needs.
--
--   role    | used by               | rights
--   mcp_ro  | spatial-db MCP server | SELECT on pub (views, functions) and src_* (via src_reader). Nothing in app.
--             Every transaction is read-only, statements time out after 15 s, at most 5 connections.
--
-- The password comes from MCP_DB_PASSWORD (.env) via db/roles/set-passwords.sql; while it is empty the role
-- has no password and cannot log in.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_ro') THEN
    CREATE ROLE mcp_ro LOGIN CONNECTION LIMIT 5;
  END IF;
END
$$;

GRANT src_reader TO mcp_ro;
GRANT USAGE ON SCHEMA pub TO mcp_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA pub TO mcp_ro;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pub TO mcp_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA pub GRANT SELECT ON TABLES TO mcp_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA pub GRANT EXECUTE ON FUNCTIONS TO mcp_ro;

ALTER ROLE mcp_ro SET default_transaction_read_only = on;
ALTER ROLE mcp_ro SET statement_timeout = '15s';
ALTER ROLE mcp_ro SET idle_in_transaction_session_timeout = '30s';

-- migrate:down
ALTER DEFAULT PRIVILEGES IN SCHEMA pub REVOKE EXECUTE ON FUNCTIONS FROM mcp_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA pub REVOKE SELECT ON TABLES FROM mcp_ro;
DROP OWNED BY mcp_ro;
DROP ROLE IF EXISTS mcp_ro;
