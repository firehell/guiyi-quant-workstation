-- Install explicitly in the isolated Simulation Center rehearsal database.
-- This journal has no relationships to SimNow accounts, readbacks, or fills.
BEGIN;
CREATE TABLE guiyi_simulation.execution_runs (
    run_id text PRIMARY KEY CHECK (run_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    genesis text NOT NULL,
    binding_hash text,
    projection text NOT NULL,
    sequence bigint NOT NULL DEFAULT 0 CHECK (sequence >= 0)
);
CREATE TABLE guiyi_simulation.execution_steps (
    run_id text NOT NULL REFERENCES guiyi_simulation.execution_runs,
    sequence bigint NOT NULL CHECK (sequence > 0),
    command_id text NOT NULL,
    command jsonb NOT NULL,
    command_hash text NOT NULL,
    state_hash text NOT NULL,
    effects jsonb NOT NULL CHECK (jsonb_typeof(effects) = 'array'),
    evidence jsonb,
    evidence_hash text,
    PRIMARY KEY (run_id, sequence),
    UNIQUE (run_id, command_id),
    CHECK ((evidence IS NULL) = (evidence_hash IS NULL))
);
CREATE TABLE guiyi_simulation.execution_claims (
    run_id text NOT NULL,
    order_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('SUBMIT', 'CANCEL')),
    effect_sequence bigint NOT NULL,
    claimed_sequence bigint NOT NULL CHECK (claimed_sequence >= effect_sequence),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object' AND payload ? 'order_id'
                                  AND jsonb_typeof(payload->'order_id') = 'string'
                                  AND payload->>'order_id' = order_id),
    payload_hash text NOT NULL,
    PRIMARY KEY (run_id, order_id, kind),
    FOREIGN KEY (run_id, effect_sequence) REFERENCES guiyi_simulation.execution_steps,
    FOREIGN KEY (run_id, claimed_sequence) REFERENCES guiyi_simulation.execution_steps
);
CREATE UNIQUE INDEX execution_submit_native_identity
    ON guiyi_simulation.execution_claims (run_id, (payload->>'native_id')) WHERE kind = 'SUBMIT';

CREATE FUNCTION guiyi_simulation.execution_refuse_rewrite() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'offline execution journal is append-only';
END;
$$;
CREATE TRIGGER execution_steps_immutable BEFORE UPDATE OR DELETE ON guiyi_simulation.execution_steps
    FOR EACH ROW EXECUTE FUNCTION guiyi_simulation.execution_refuse_rewrite();
CREATE TRIGGER execution_claims_immutable BEFORE UPDATE OR DELETE ON guiyi_simulation.execution_claims
    FOR EACH ROW EXECUTE FUNCTION guiyi_simulation.execution_refuse_rewrite();
CREATE TRIGGER execution_genesis_immutable BEFORE UPDATE OF run_id, genesis, binding_hash ON guiyi_simulation.execution_runs
    FOR EACH ROW EXECUTE FUNCTION guiyi_simulation.execution_refuse_rewrite();
COMMIT;
