-- Warehouse schemas owned by Python: bronze (records as received) and ops (pipeline bookkeeping).
-- Silver and gold are built by dbt, not here. Every statement is idempotent.
--
-- Bronze is append-only: never UPDATE, DELETE or TRUNCATE it. The only writer is the bronze
-- consumer (src/ingestion/), which reads Kafka; the CI fixture loader
-- (scripts/seed_ci_bronze.py) writes the same shape into a throwaway *_ci database only.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS ops;

-- One row per record version received. Envelope fields are stored as sent; `payload` is the
-- source row, untouched. A repeated message (Kafka at-least-once, poller re-send) hits the
-- unique key and is ignored: INSERT ... ON CONFLICT ON CONSTRAINT uq_raw_records_version
-- DO NOTHING. `source_version` (the source's change_seq) is in the key, so a record that changes
-- A -> B -> A keeps its third version; NULLS NOT DISTINCT keeps a version-less re-send a duplicate.
CREATE TABLE IF NOT EXISTS bronze.raw_records (
    id               bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source           text         NOT NULL,
    entity           text         NOT NULL,
    record_id        text         NOT NULL,
    event_at         timestamptz,
    collected_at     timestamptz  NOT NULL,
    is_sample        boolean      NOT NULL,
    source_version   bigint,                 -- the source's version of the row, if it has one
    payload          jsonb        NOT NULL,
    payload_hash     text         NOT NULL,  -- sha256 of the canonical payload JSON
    ingested_at      timestamptz  NOT NULL DEFAULT now(),
    kafka_partition  integer,
    kafka_offset     bigint,
    CONSTRAINT uq_raw_records_version
        UNIQUE NULLS NOT DISTINCT (source, entity, record_id, source_version, payload_hash)
);

-- Upgrade a bronze table created before source_version existed (adds a column and swaps the
-- unique key; no row is changed).
ALTER TABLE bronze.raw_records ADD COLUMN IF NOT EXISTS source_version bigint;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_raw_records_version'
          AND conrelid = 'bronze.raw_records'::regclass
          AND pg_get_constraintdef(oid) LIKE '%source_version%'
    ) THEN
        ALTER TABLE bronze.raw_records DROP CONSTRAINT IF EXISTS uq_raw_records_version;
        ALTER TABLE bronze.raw_records ADD CONSTRAINT uq_raw_records_version
            UNIQUE NULLS NOT DISTINCT (source, entity, record_id, source_version, payload_hash);
    END IF;
END
$$;

-- dbt's incremental models read one entity at a time, newest rows first.
CREATE INDEX IF NOT EXISTS ix_raw_records_entity_ingested
    ON bronze.raw_records (entity, ingested_at);
-- GET /api/v1/records pages through one source and entity.
CREATE INDEX IF NOT EXISTS ix_raw_records_source_entity_id
    ON bronze.raw_records (source, entity, id);

-- Messages that could not be parsed or failed envelope validation, with the reason.
CREATE TABLE IF NOT EXISTS bronze.rejected_records (
    id               bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_value        text,         -- the Kafka message value as received (may not be JSON)
    reason           text         NOT NULL,
    kafka_partition  integer,
    kafka_offset     bigint,
    ingested_at      timestamptz  NOT NULL DEFAULT now()
);

-- One row per ingest flush window (consumer) or transform cycle (runner).
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id          bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage           text         NOT NULL CHECK (stage IN ('ingest', 'transform')),
    status          text         NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    started_at      timestamptz  NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    rows_loaded     integer,
    rows_rejected   integer,
    watermark       timestamptz,  -- transform: max bronze ingested_at this run covered
    message         text
);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_stage_status
    ON ops.pipeline_runs (stage, status, finished_at DESC);

-- The source poller's high-water mark per source table (xom_source change_seq).
CREATE TABLE IF NOT EXISTS ops.source_offsets (
    source           text         NOT NULL,
    entity           text         NOT NULL,
    last_change_seq  bigint       NOT NULL,
    updated_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (source, entity)
);
