-- Apply explicitly to the dedicated Simulation Center database.
BEGIN;
CREATE SCHEMA guiyi_simulation;
CREATE TABLE guiyi_simulation.accounts (
    alias text PRIMARY KEY,
    native_key text NOT NULL UNIQUE,
    deployment jsonb,
    status text NOT NULL DEFAULT 'STOPPED',
    status_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE guiyi_simulation.readbacks (
    alias text NOT NULL REFERENCES guiyi_simulation.accounts,
    observed_at timestamptz NOT NULL,
    facts jsonb NOT NULL,
    PRIMARY KEY (alias, observed_at)
);
CREATE TABLE guiyi_simulation.fills (
    alias text NOT NULL REFERENCES guiyi_simulation.accounts,
    native_id text COLLATE "C" NOT NULL,
    occurred_at timestamptz NOT NULL,
    facts jsonb NOT NULL,
    PRIMARY KEY (alias, native_id)
);
CREATE INDEX simulation_fills_time ON guiyi_simulation.fills (alias, occurred_at DESC, native_id DESC);
COMMIT;
