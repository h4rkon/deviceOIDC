-- #########################################################
-- # Data Platform Init Script
-- # Context: create dedicated schema + table + publication
-- # for "Status Abfrage" in existing Keycloak Postgres DB
-- #########################################################


-- 1) Create schema for data platform
CREATE SCHEMA IF NOT EXISTS dataplatform;

-- 2) Create extension for UUID generation (if not exists)
--    You may adjust based on your Postgres setup.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 3) Create status_abfrage table
--    This table logs status queries (insert-only use case)
CREATE TABLE IF NOT EXISTS dataplatform.status_abfrage (
    unique_identifier    UUID PRIMARY KEY,
    status_ts            timestamptz NOT NULL DEFAULT now(),
    veranstalter_id      UUID,
    betriebsstaette_id   UUID,
    geraete_id           UUID,
    vorname              TEXT,
    nachname             TEXT,
    geburtsdatum         DATE
);

-- 4) Prepare CDC (Logical Replication)
--    Enable logical WAL level if not already set (may require superuser and config reload)
--    If this fails due to permission, database operator must set this in postgres.conf
ALTER SYSTEM SET wal_level = logical;
SELECT pg_reload_conf();

-- 5) Create a Publication for the status_abfrage table
--    Debezium will use this for CDC
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication WHERE pubname = 'dp_status_pub'
    ) THEN
        CREATE PUBLICATION dp_status_pub
             FOR TABLE dataplatform.status_abfrage;
    END IF;
END
$$;

-- 6) Grant replication login to user (if needed)
--    Adjust user name if not "keycloak" or if a dedicated replication user exists
ALTER ROLE keycloak WITH REPLICATION LOGIN;

-- #########################################################
-- # Verification Queries (optional)
-- #########################################################

-- Check that the schema exists
-- SELECT nspname FROM pg_namespace WHERE nspname = 'dataplatform';

-- Check that the table exists
-- SELECT table_schema, table_name
--   FROM information_schema.tables
--  WHERE table_schema='dataplatform' AND table_name='status_abfrage';

-- Check that the publication exists
-- SELECT * FROM pg_publication WHERE pubname = 'dp_status_pub';

-- #########################################################
-- # End of Script
-- #########################################################