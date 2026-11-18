# CLAUDE.md — Data Pipeline Workstream

Project: E-Commerce Data Pipeline and Analytics Dashboard (SWE40006). The data is Xóm E-Com's order history: sales lines of beauty and home products, with customers, products and regions (see `data_context.md` for the business questions, and "Known source quirks" below for where the data differs from that narrative).
The root `README.md` is the source of truth for overall scope. This file covers the **data pipeline workstream** only.

## What I own

1. **Source simulation** (`src/source/`, `scripts/generate_burst.py`): the `xom_source` database that plays Xóm E-Com's operational system, its seed loader, the **source poller** that sends new source rows to the API, and the **mock generator** that inserts demo orders into the source.
2. **Raw data API** (`src/api/`): a Flask service that receives raw records, publishes them to Kafka, and serves raw records from bronze for inspection.
3. **Kafka** (single broker) and the **bronze consumer** (`src/ingestion/`): a long-running process that streams records from the topic into PostgreSQL.
4. **Transform runner** (`src/pipeline/`): a small loop that runs dbt when new bronze rows have arrived.
5. **dbt project** (`dbt/`): silver and gold models plus data tests, ending in the tables the dashboard reads.
6. The pipeline services in `docker-compose.yml`, and the pipeline's checks (pytest, ruff, dbt), run locally for now; there is no CI workflow yet.
7. **Extract tool** (`src/extract/`): a one-off dump of the upstream SQL Server dataset to `data/xomdata/*.csv`, which seeds `xom_source`. Not part of the running pipeline.
8. **Gold snapshot for the dashboard owner** (`dashboard_serve/`): `export_gold.py` writes every gold table to CSV with a generated `schema.sql` and `manifest.json`; `load_gold.py` (standalone, psycopg only) recreates `gold` from them in another database and refuses a database with `bronze`/`silver`. Refresh it with the export after a gold change; a column change there is a contract change.

Not mine, so do not modify without being asked: `dashboard/` (Streamlit), `deploy.yml`, `scripts/deploy.sh`, AWS infrastructure, CloudWatch setup. The dashboard team's only interface to my work is the **gold schema** (see "Dashboard contract").

## Data flow

```text
data/xomdata/*.csv --seed (once)--> xom_source  (Postgres database: simulated Xóm E-Com operational system)
                                        ^    |
     Mock generator (demo) --INSERT-----+    |  Source poller: reads rows past its high-water mark
                                             |  (all history on its first run, then only new rows)
                                             |  POST
                                             v
                              Raw data API (Flask) --publish--> Kafka topic: raw.ecom_records
                                                                       |
                                                                       v
                                                Bronze consumer (always running, micro-batches)
                                                                       |
                                                                       v
                                                bronze (Postgres, append-only)
                                                                       |
                             Transform runner: every 30 s, if new bronze rows -> dbt build
                                                                       |
                                                                       v
                                                silver -> gold  ->  Streamlit (polls on a timer)
```

Two parts with different shapes:

- **Stream (source -> poller -> API -> Kafka -> bronze)** is a straight line and always on. It is not orchestrated; it is kept alive by the container restart policy.
- **Transform (bronze -> silver -> gold)** is a DAG, and dbt owns it through `ref()` and `source()`. Never hand-code model ordering.

"Real time" for the dashboard means this design: Kafka streams records into bronze continuously, and dbt rebuilds gold in micro-batches every 30 seconds. There is no stream-processing framework and no metric computed outside dbt.

There is no Airflow. Do not add it or any other orchestrator. Python owns everything up to and including bronze; dbt owns everything after it.

**History goes through the same path.** The existing dataset reaches bronze only by the poller's first run sending every source row through the API and Kafka. There is no direct backfill into bronze; a rebuild means replaying from `xom_source` (or `dbt build --full-refresh` from bronze), never inserting into bronze by hand.

## Source system (`xom_source`, `src/source/`)

- `xom_source` is a separate database in the same Postgres container as the warehouse. It holds the four e_commerce tables in schema `e_commerce` (`sales_line`, `customer`, `product`, `region`; `sales_line` is upstream's `ecom_sales`, renamed to match the entity) with the source's own column names and types and no foreign keys, plus two technical columns: `is_sample boolean NOT NULL DEFAULT false` and `change_seq bigint`, set from one shared sequence (`e_commerce.change_seq`) on insert and bumped by a trigger on update. DDL lives in `sql/source_schema.sql`.
- `python -m src.source.seed` creates `xom_source` and loads `data/xomdata/*.csv` once, checking row counts (non-sample rows) against `data/xomdata/manifest.csv`. A re-run only verifies; it never truncates or reloads. It never touches the warehouse, and refuses to run if `SOURCE_DATABASE_URL` and `DATABASE_URL` name the same database.
- Only the seed and the mock generator write to `xom_source`. The pipeline reads it.
- **Poller** (`src/source/poller.py`): every `POLLER_INTERVAL_SECONDS`, for each table (reference tables before `sales_line`), reads up to `POLLER_BATCH_SIZE` rows with `change_seq` above its high-water mark, wraps each row in the envelope, and POSTs the batch to the API. It advances the mark in `ops.source_offsets` only after the API returns `202`. A crash between the two re-sends the batch; bronze idempotency absorbs it.
- **Mock generator** (`scripts/generate_burst.py`): inserts new orders into `xom_source` at a given rate. New sales lines reuse existing products and regions, mostly existing customers with some new ones, take unit prices and discounts from each product's history, continue `row_id` past the current maximum, carry `order_date` = the current date, and set `is_sample = true`. It never POSTs to the API itself.

## Record envelope

Every record the poller sends, the API accepts and Kafka carries has this shape:

| Field | Meaning |
|---|---|
| `source` | `xom_ecom` (the only source; the field stays so a feed can be added without a schema change) |
| `entity` | `sales_line`, `customer`, `product` or `region` |
| `record_id` | the source key as text: `row_id`, `customer_id`, `product_code` or `region_code` |
| `event_at` | business time when the record has one (`order_date` for sales lines), else `null` |
| `collected_at` | when the poller read the row from the source |
| `is_sample` | `true` for mock-generator rows, copied from the source row |
| `source_version` | the source's version of the row (`change_seq` in `xom_source`), or `null` for a source without one |
| `payload` | the source row as JSON, exactly as stored, without the technical columns |

## Layers

| Layer | Postgres schema | Built by | Contents |
|---|---|---|---|
| Bronze | `bronze` | Consumer | `raw_records`: one row per received record version: the envelope fields (including `source_version`), `payload` as `jsonb`, `payload_hash`, `ingested_at`, Kafka `partition` and `offset`. `rejected_records`: messages that failed validation, with the reason |
| Silver | `silver` | dbt | `stg_sales_lines`, `stg_customers`, `stg_products`, `stg_regions`: the latest version of each record, typed columns, trimmed text, derived sales-line fields (`unit_price`, `pre_discount_amount`, `discount_amount`, `net_sales`, `discount_band`, `is_loss`, `currency`) and row-level quality flags. `stg_sales_line_flags`: cross-record flags (unknown customer, region or product; multi-customer order) |
| Gold | `gold` | dbt | `dim_customer`, `dim_product`, `dim_region`, `dim_date`, `fct_sales_lines`, `mart_discount_impact`, `mart_segment_pnl`, `mart_market_growth`, `mart_customer_retention` |
| Ops | `ops` | Consumer, runner, poller | `pipeline_runs`: one row per ingest flush window or transform cycle (`stage` = `ingest` or `transform`), with status, started/finished, rows loaded/rejected, and the bronze watermark reached. `source_offsets`: the poller's high-water mark per source table |

Rules that apply to every layer:

- **Bronze is append-only.** Never `UPDATE`, `DELETE` or `TRUNCATE` it. A changed source row arrives as a new version; silver picks the latest.
- **Idempotent loads.** Insert with `ON CONFLICT DO NOTHING` on `(source, entity, record_id, source_version, payload_hash)` (constraint `uq_raw_records_version`, `NULLS NOT DISTINCT`). `source_version` in the key means a record that changes A -> B -> A keeps its last version. Kafka delivery is at-least-once and the poller can re-send, so a repeated message must not create a duplicate row.
- **Bronze stores what was sent.** No cleaning, renaming or type coercion before the row lands. Fixes belong in silver.
- **Missing is not zero.** A missing amount, quantity or attribute stays `NULL`. Never coalesce to `0` or an empty string.
- **Keys are source keys.** Dimensions are keyed on `(source, natural key)`. Do not merge customers or products by name similarity.
- **Absence is not an event.** A record that stops being sent has not been deleted, and a customer without recent orders has not "churned" unless a mart defines churn explicitly.
- **Sample rows are always included and always labeled.** `is_sample` is carried from the envelope into bronze, silver, `fct_sales_lines` and every mart's grain, so the dashboard can show, badge or hide demo data. Never drop or merge them silently.
- A failed transform must leave the previous gold tables intact.

## Known source quirks

Checked against the loaded data on 2026-11-16. Handle these in silver; do not "fix" them in the source or in bronze.

- **History** covers `order_date` 2020-01-01 to 2023-12-31: 51,290 sales lines in 25,728 orders, 17,415 customers, 28,356 products, 3,828 regions. Generated orders are dated "now", so trend marts show a gap from 2024 to the demo date. Do not fill or interpolate it.
- **`order_id` dates are off by 8 years.** The year and Excel serial date inside `order_id` sit exactly 8 years before `order_date` on every row (e.g. `MX-2015-SC2057582-42279` decodes to 2015-10-02; its `order_date` is 2023-10-02). Use `order_date`; treat `order_id` as an opaque identifier.
- **Orphan references:** 2 sales lines point to a `region_code` missing from `region`, and 2 to a `product_code` missing from `product`. They map to an "unknown" member in the dimension so totals still reconcile, and they are flagged in silver.
- **11 orders have more than one `customer_id`.** Flag them; do not reassign.
- **102 `(order_id, product_code)` pairs appear on more than one line.** The grain is `row_id`; do not deduplicate on order and product.
- **124 customers have no `gender`.** It stays `NULL`.
- **`sales` is before discount.** `sales / quantity` is the same for a product at every discount level (all 3,578 products sold, checked 2026-11-17), so `sales` = unit price x quantity, and profit is after discount (undiscounted lines average a 31.4% margin, discounted lines -2.7%). Silver keeps `sales` as is, sets `pre_discount_amount = sales`, and derives `discount_amount = sales x discount` and `net_sales = sales x (1 - discount)`. Margins use `profit / net_sales`. `TODO(source)`: confirm with the data owner.
- **No currency column.** Amounts are treated as USD: 2023 revenue is $2.19M, matching `data_context.md`'s "~$2.3M/year". Silver sets `currency = 'USD'` as a documented assumption. `TODO(source)`: confirm with the data owner. No conversion is done.
- **`data_context.md` differs from the data:** segments are Consumer, Corporate and Self-Employed (not Home Office); there are 5 markets (Africa, Asia Pacific, Europe, LATAM, USCA); the 5 categories are beauty and home (Body care, Face care, Hair care, Make up, Home and Accessories) across 17 subcategories. Use the data's values. Source categories are kept as they are; there is one source, so there is no category mapping.

## Raw data API (`src/api/`)

- Flask app factory in `src/api/app.py`; one blueprint per concern. All JSON, versioned under `/api/v1`.
- Endpoints:
  - `GET /health` returns `{"status": "ok", "version": "<commit sha>"}`. Used by deploy health checks, so keep it dependency-light (it must not fail because Kafka is slow).
  - `POST /api/v1/records` accepts one record or a list. It checks only the envelope (fields above: required, `entity` in the allowed set, `payload` an object, `is_sample` a boolean), publishes each record to Kafka, and returns `202` with the accepted count.
  - `GET /api/v1/sources` lists the known sources.
  - `GET /api/v1/records?source=<id>&entity=<name>&page=<n>&page_size=<n>` serves raw records read-only from bronze, with `page`, `page_size`, `total` and `next_page`. `page_size` defaults to 100 and is capped at 500.
- If the Kafka publish fails, return `503`. Never return success for a record that was not published.
- The API never writes to the warehouse. The only path into bronze is through Kafka and the consumer.
- Each source's raw payload shape is preserved. Do not unify field names in the API; that is silver's job.
- The API must not duplicate what Streamlit does (Streamlit reads gold directly from Postgres).
- The interim `raw` schema and `GET /api/v1/tables` endpoints (a direct CSV load built before this design) were retired with roadmap step 2. Do not bring them back.

## Kafka

- One broker in KRaft mode (no ZooKeeper), defined in `docker-compose.yml`. Keep it to one broker and one topic; no Schema Registry, Kafka Connect or stream-processing framework.
- Topic `raw.ecom_records`, created explicitly (auto-create off). Message key is `<source>:<entity>:<record_id>`, so versions of one record stay ordered. Value is the JSON envelope.
- Python client: `confluent-kafka`.
- Producer (in the API): `acks=all`, idempotence enabled, and flush before responding.
- Bronze `jsonb` is the raw record of what arrived. There is no S3 or other raw snapshot; `xom_source` and Kafka retention cover replays.

## Bronze consumer (`src/ingestion/consumer.py`)

- Consumer group `bronze-loader`, with `enable.auto.commit=false`.
- Loop: poll up to `CONSUMER_BATCH_SIZE` messages or `CONSUMER_FLUSH_SECONDS`, whichever comes first -> validate -> batch-insert into bronze in one transaction -> commit the database -> then commit Kafka offsets. This order is required: committing offsets first can lose records.
- A message that fails validation or cannot be parsed goes to `bronze.rejected_records` with the reason and is counted. It must never block the partition or crash the consumer.
- If Postgres is unavailable, do not commit offsets; back off and retry. The records stay in Kafka.
- Write an `ops.pipeline_runs` row (`stage = 'ingest'`) per flush window that had activity.
- Use `logging`, not `print`. Log batch size, rejected count, lag and duration.
- Handle `SIGTERM` cleanly: finish the current batch, commit, close the consumer.
- As built (2026-11-17):
  - It validates with the same `src.envelope.validate` as the API, which also catches what Postgres cannot store (NaN, NUL characters), so a valid message always inserts.
  - Bronze rows are written by `src.warehouse.insert_raw_records`, shared with `scripts/seed_ci_bronze.py`.
  - Postgres down (connection errors): no Kafka commit; it seeks back to the batch's first offsets and backs off up to 30 s. A row Postgres refuses for its data is retried alone and rejected, so the rest of the batch lands.
  - Measured on the full history: about 0.04 s per 1,000-record batch; 100,889 records in about 10 s.

## Transform runner (`src/pipeline/transform_runner.py`)

- Single process, single loop, every `TRANSFORM_INTERVAL_SECONDS` (default 30):
  1. Read the watermark (max `ingested_at` processed by the last successful transform) from `ops.pipeline_runs`.
  2. If bronze has no newer rows, sleep.
  3. Otherwise run `dbt build`, record the result as a `stage = 'transform'` row, and advance the watermark only on success.
- Trigger per time window, never per record. A burst of thousands of records should cause one or two dbt runs.
- Runs never overlap: the loop waits for `dbt build` to finish before the next tick. Do not add threads or a second runner.
- A failed run is retried on the next tick; this is safe because the models are incremental and bronze inserts are idempotent.
- A cycle (`dbt build` included) must finish well inside the 30 s interval. If it does not, fix the models (see dbt below) rather than raising the interval.
- As built (2026-11-17):
  - The new watermark is bronze's `max(ingested_at)` read before dbt starts, so rows that land during a build trigger the next cycle. This relies on the single consumer committing batches one after another; a second consumer would need a different watermark.
  - A cycle with nothing new writes no row. A run writes a `running` row first and finishes it as `success` (with `watermark` and `rows_loaded` = new bronze rows) or `failed` (no watermark, the dbt summary and failing tests in `message`). A `running` row found at the start of a cycle is closed as `failed` ("interrupted").
  - dbt runs as a subprocess (`dbt build --project-dir dbt --profiles-dir dbt`), with a 600 s timeout for a hung build. The runner sets `DBT_PG_*` from `DATABASE_URL`, so dbt always builds the database whose watermark it records.
  - It applies `sql/schema.sql` on start (`src/warehouse.apply_schema`, under an advisory lock).
  - SIGTERM or Ctrl+C: the current build finishes and is recorded, then the process exits. Compose gives it a 60 s grace period.
  - `--once` exits 0 when the cycle succeeded or had nothing to do, and 1 when it failed or the warehouse was unreachable.
  - Measured on `xom_ci`: about 11 s for a cycle while the full history is inside the 10-minute lookback, about 5 s in steady state.
- A failing dbt test stops every later cycle until the bad record is fixed in the source, and the dashboard then shows the data as stale. That is intended: gold never shows data that failed a test.

## dbt (`dbt/`)

- dbt Core v1 (`dbt-core` + `dbt-postgres`, pinned in `requirements.txt`). Profile is read from environment variables; `profiles.yml` contains no secrets.
- Do not switch to dbt v2 (the `dbt` PyPI package): as of 2026-11 it has no Postgres adapter. dbt Core v1 remains supported. dbt v1 prints a "dbt v2 is available" note; ignore it. To keep a later move cheap, write v2-clean v1 code: no deprecation warnings, `--select` (never `--models`/`-m`), no unknown YAML keys, and every `var()` given a default.
- Layout:
  ```text
  dbt/models/
    bronze/   _sources.yml only (declares bronze.raw_records, with freshness)
    silver/   stg_*.sql  + _silver.yml
    gold/     dim_*.sql, fct_*.sql, mart_*.sql  + _gold.yml
  dbt/macros/   generate_schema_name.sql, incremental.sql (lookback filter), safe_cast.sql
  dbt/tests/    singular tests; tests/generic/ holds unique_combination_of_columns (grain tests)
  dbt/profiles.yml  dev | ci | prod, from DBT_PG_* env vars; no packages are used
  ```
- `generate_schema_name` is overridden so models land in `silver` / `gold` exactly, not `<target_schema>_silver`. Keep that macro.
- Models read bronze only through `{{ source() }}` and each other only through `{{ ref() }}`. No hard-coded schema names.
- Gold models never read bronze directly; they go through silver.
- Materializations: the four entity `stg_*` models and `fct_sales_lines` are `incremental` with a `unique_key`, filtering on `ingested_at > max(ingested_at) - 10 minutes` (macro `ingested_since_last_run`, var `incremental_lookback_minutes`). The lookback catches a batch that committed late with an earlier `ingested_at`; the merge on `unique_key` makes the overlap harmless. `stg_sales_line_flags`, the dimensions and the marts are `table`.
- Latest version: silver ranks the versions of a record by `ingested_at`, then Kafka offset, then bronze `id`, newest first.
- Payload values are cast with the `safe_*` macros: a value that cannot be parsed becomes `NULL` and sets `has_invalid_value`, so one bad record never blocks every later transform.
- Cross-record flags live in `stg_sales_line_flags`, a table rebuilt every run, so a reference that arrives late clears its flag. `fct_sales_lines` re-reads, on every run, the lines that point at an unknown member, so they are re-linked once the reference arrives.
- Keys: dimension keys are `'<source>|<natural key>'`; the unknown member of each dimension is `'<source>|unknown'` (`is_unknown = true`, attributes `NULL`), one per source in var `known_sources`. `fct_sales_lines.sales_line_key` is `'<source>|<row_id>'`; `order_date` is the key to `dim_date.date_day`.
- `discount_band`: `none` (0), `low` (up to 0.20), `medium` (up to 0.40), `high` (above 0.40); `NULL` when discount is missing.
- `mart_customer_retention` computes each `is_sample` slice on its own (a customer's cohort is their first order within the slice), so hiding sample rows leaves the real figures untouched. `mart_market_growth` compares a year only with the calendar year before it, so the demo year's change is `NULL`.
- Measured on 2026-11-17 with the full history in the CI database: a steady-state cycle takes about 1.6 s in dbt (5 s with dbt's start-up); a cycle that re-reads a whole burst takes about 8.5 s.
- Because dbt runs every cycle, every model must stay cheap. If a cycle takes longer than the interval, fix the model (incremental filter, index) rather than shortening the work by skipping tests.
- One model per file, lowercase snake_case, CTEs over nested subqueries, explicit column lists (no `select *` in final selects).
- Every model has a description and tests in its layer's `.yml`. Minimum tests:
  - Primary keys: `unique` + `not_null`.
  - `accepted_values` on `source` (`xom_ecom`), `segment` (Consumer, Corporate, Self-Employed), `market` (Africa, Asia Pacific, Europe, LATAM, USCA), `currency` (USD) and `discount_band`.
  - `relationships` from `fct_sales_lines` to each dimension (orphans resolve to the unknown member, so these pass).
  - Singular tests: `sales >= 0` and `quantity > 0` when not null; `discount` between 0 and 1; `order_date` not after the current date; a reconciliation test that the line count and the sums of `sales` and `profit` in `fct_sales_lines` equal the latest sales-line versions in silver.
- Use `dbt build` (run + test together) rather than `dbt run`, so a failing test stops downstream models.

## Dashboard contract (gold schema)

The dashboard reads only `gold.*` and `ops.pipeline_runs`, and polls on a timer. It is near real time: gold lags bronze by at most the transform interval (30 s) plus the dbt run time. The dashboard shows the data as **stale when the last successful transform is more than 2 minutes old**.

- This contract replaces the earlier price-observation one (`dim_products`, `fct_price_observations`, price marts). The dashboard owner must confirm it before gold is built.
- Renaming or removing a gold column, or changing its grain, is a breaking change. Flag it to me before doing it so I can coordinate with the dashboard owner.
- Adding columns is fine.
- Grain:
  - `dim_customer`, `dim_product`, `dim_region`: one row per `(source, natural key)`, plus one "unknown" row each.
  - `dim_date`: one row per calendar day from the first `order_date` to the current date.
  - `fct_sales_lines`: one row per `(source, row_id)`, with keys to every dimension, the measures (`quantity`, `sales`, `discount`, `profit`, `unit_price`, pre-discount amount), `discount_band`, `is_loss`, `currency` and `is_sample`.
  - `mart_discount_impact`: one row per month / category / `discount_band` / `is_sample`.
  - `mart_segment_pnl`: one row per quarter / segment / `is_sample`.
  - `mart_market_growth`: one row per year / market / region / `is_sample`, with year-on-year change.
  - `mart_customer_retention`: one row per first-order cohort month / months since first order / `is_sample`.
- Marts expose medians and counts alongside averages, and always carry the `order_date` range they cover.
- Sample rows are in every gold table, labeled by `is_sample`. Showing, badging or hiding them is the dashboard's choice.

## Commands

```bash
# Local stack (project venv on Python 3.13, the same version as the Docker image)
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d postgres kafka kafka-init   # kafka-init creates the topic, then exits

# Source system: create xom_source and load data/xomdata/*.csv (once)
python -m src.source.seed

# Services (each is also a compose service: api, consumer, poller, transform-runner)
flask --app src.api.app run --port 5001             # 5000 is usually taken by macOS AirPlay
python -m src.ingestion.consumer
python -m src.source.poller                          # first run sends all history, then follows new rows
python -m src.pipeline.transform_runner
python -m src.pipeline.transform_runner --once       # one cycle, then exit

# Demo: insert mock orders into xom_source; the poller picks them up
python scripts/generate_burst.py --count 5000 --rate 500

# Warehouse schemas (bronze, ops); idempotent. The transform runner (and later the consumer) applies it on start.
docker compose exec -T postgres psql -U xom -d xom -v ON_ERROR_STOP=1 < sql/schema.sql

# dbt (run from dbt/; dbt does not read .env, so export it first)
set -a; source ../.env; set +a
dbt deps
dbt build                                       # all models + tests
dbt build --select silver                       # one layer
dbt build --select +mart_segment_pnl            # a model and its upstream
dbt build --full-refresh                        # rebuild incremental models from bronze
dbt source freshness

# dbt against the throwaway CI database (xom_ci), with fixture bronze rows from xom_source
python scripts/seed_ci_bronze.py --reset --edge-cases   # from the repo root
DBT_TARGET=ci dbt build                                  # from dbt/
python scripts/seed_ci_bronze.py --late-customer         # then build again: the line is re-linked

# Tests and lint
pytest tests/ -q
E2E=1 pytest tests/e2e -v                       # against the running compose stack
ruff check . && ruff format --check .

# Gold snapshot for the dashboard owner (one consistent read of gold -> dashboard_serve/)
python dashboard_serve/export_gold.py

# Re-extract the upstream dataset to data/xomdata/ (rarely; needs the SQL Server ODBC driver)
python -m src.extract.export_sqlserver --schema e_commerce
```

If one of these commands does not exist yet, create it to match this file rather than inventing a different interface.

## Configuration

- All configuration comes from environment variables; `.env.example` lists every one with a dummy value. Never commit `.env`, passwords, API keys or connection strings.
- Expected variables: `DATABASE_URL` (warehouse), `SOURCE_DATABASE_URL` (`xom_source`), `API_URL` (where the poller posts), `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC`, `CONSUMER_BATCH_SIZE`, `CONSUMER_FLUSH_SECONDS`, `POLLER_INTERVAL_SECONDS`, `POLLER_BATCH_SIZE`, `TRANSFORM_INTERVAL_SECONDS`, `DBT_TARGET` (`dev` | `ci` | `prod`), `DBT_PG_HOST`, `DBT_PG_PORT`, `DBT_PG_USER`, `DBT_PG_PASSWORD`, `DBT_PG_DBNAME`, `DBT_CI_DBNAME` (the dbt profile), `CI_DATABASE_URL` (the throwaway `*_ci` database for dbt tests), `APP_VERSION`; and `MSSQL_SERVER`, `MSSQL_DATABASE`, `MSSQL_USER`, `MSSQL_PASSWORD` for the extract tool only.
- Test and production use separate databases, separate Kafka brokers and separate credentials. Never point a local or test run at production.
- Database users: the generator writes `xom_source`; the poller reads `xom_source` and writes only `ops.source_offsets`; the consumer and runner write `bronze`/`silver`/`gold`/`ops`; the API is read-only on `bronze`; the dashboard is read-only on `gold` and `ops`.
- The Kafka broker port is not exposed publicly; only the API and consumer reach it (plus `127.0.0.1` on a developer machine).

## Testing

- `tests/source/`: the poller maps rows to envelopes (technical columns left out of `payload`), sends reference tables before sales lines, advances its high-water mark only after a `202`, and re-sends after a failure; the generator labels its rows `is_sample` and dates them today.
- `tests/api/`: Flask test client with a fake producer, covering accepted posts, bad envelopes, publish failure returning 503, pagination bounds, unknown source and health.
- `tests/ingestion/`: the consumer's batch logic against fake messages (no broker in unit tests), covering validation and rejection, the commit order, and an idempotency test that processes the same batch twice and asserts the row count is unchanged.
- `tests/pipeline/`: the runner skips when there are no new rows, advances the watermark only on success, and retries after a failure.
- dbt tests run locally (`DBT_TARGET=ci`) against a throwaway Postgres database (`xom_ci`) seeded with fixture bronze rows by `scripts/seed_ci_bronze.py`. That script refuses any database whose name does not end in `_ci`; it is the only writer of bronze outside the consumer, and never touches the dev or prod warehouse. There is no CI workflow yet.
- End-to-end availability tests (`tests/e2e/`, compose stack, skipped unless `E2E=1`): every service answers; the history reaches bronze (counts match `manifest.csv`, poller marks at the source head, consumer lag 0, no rejects); an identical re-send adds no row; gold reconciles with `xom_source`. Still to add with step 8: the generator inserts orders into `xom_source`, then assert they appear in bronze and in gold.
- A change is done when `pytest`, `ruff` and `dbt build` all pass locally.

## Working rules for Claude

- Keep it small. Kafka is the only streaming component. No Airflow, Spark, Flink, Faust, ksqlDB, Kafka Connect, Schema Registry or Kubernetes.
- Do not add a dependency without saying so, and pin it in `requirements.txt` (runtime, shared by every service image), `requirements-dev.txt` (tests and lint) or `requirements-extract.txt` (the SQL Server extract tool only). Install into the project's `.venv`, never a shared environment.
- Schema changes go through `sql/schema.sql` (bronze, ops), `sql/source_schema.sql` (`xom_source`) or dbt models (silver, gold), never ad-hoc DDL.
- When changing a model, update its `.yml` description and tests in the same change.
- Do not fabricate data sources, row counts or results. If something about a real source is unknown, leave a `TODO(source)` and tell me.
- Records from the mock generator must be labeled (`is_sample = true` in `xom_source`, in the envelope, and from there into bronze, silver and gold) so they are never mistaken for collected data.
- A code deploy must not replay or reload data, and restarting the consumer or poller must resume from its committed offset or high-water mark.

## Decisions

Settled on 2026-11-16:

- [x] **Scope: Kafka streaming for a real-time dashboard.** Kafka streams records into bronze continuously and dbt rebuilds gold in 30 s micro-batches; no stream-processing framework. The README is updated to match.
- [x] **Sources and how records reach the API:** one source, `xom_ecom` (the xomdata e_commerce dataset), held in the simulated source database `xom_source`. The source poller sends all history through API -> Kafka -> bronze on its first run, then new rows; the mock generator inserts demo orders into `xom_source` (before the API), never into the API directly.
- [x] **Domain:** the pipeline models sales lines (envelope with `entity` and `record_id`, topic `raw.ecom_records`, sales star schema and pain-point marts in gold), replacing the fashion price-observation design.
- [x] **Category normalization:** none. One source, so source categories are kept as they are.
- [x] **Currency:** amounts are stored as observed and treated as USD (documented assumption, `TODO(source)`); no conversion.
- [x] **Mock data:** always included in gold, labeled by `is_sample`, dated at generation time.
- [x] **Transform interval and staleness:** 30 s interval; the dashboard flags data as stale after 2 minutes without a successful transform.
- [x] **CI:** no `.github/workflows/data-pipeline.yml` for now; checks run locally.
- [x] **Raw snapshots:** bronze `jsonb` alone is the raw record; nothing is written to S3.
- [x] **Interim `raw` schema and `/api/v1/tables`:** retired (done in roadmap step 2, 2026-11-17).

Settled on 2026-11-17:

- [x] **Record versions in bronze:** the envelope carries `source_version` (the source's `change_seq`) and bronze's uniqueness key includes it, so A -> B -> A keeps its last version (decided before the consumer was built).
- [x] **`sales` semantics:** `sales` is the amount before discount and profit is after it (see "Known source quirks"); `TODO(source)` until the data owner confirms.
- [x] **Discount bands:** none / low (up to 0.20) / medium (up to 0.40) / high (above 0.40).
- [x] **Cross-record flags:** in `silver.stg_sales_line_flags`, a table rebuilt every run, not in the incremental models.
- [x] **Retention with sample data:** each `is_sample` slice is its own cohort analysis.

Still open:

- [ ] **Staleness while idle.** The runner writes no row when bronze has nothing new, so after 2 quiet minutes the dashboard's rule ("last successful transform older than 2 minutes") shows stale data that is in fact current. Options: (a) the runner records idle checks as `success` rows with `rows_loaded = 0`, which keeps the dashboard rule unchanged at about 2,900 rows a day; (b) a one-row `ops.transform_status` heartbeat, which changes the dashboard contract; (c) the dashboard compares the watermark with bronze. Needs a decision with the dashboard owner.

- [ ] Dashboard owner confirms the new gold contract (it replaces the price-observation tables). Gold was built on 2026-11-17 at the workstream owner's request, ahead of that confirmation; changes the dashboard owner asks for are still possible, but count as breaking once they use it.
- [ ] Data owner confirms the amounts are USD (`TODO(source)`).
- [ ] Whether `data_context.md` is corrected to match the data (segments, markets, categories), or kept as the business brief with the differences noted here.
- [ ] Add a CI workflow later (ruff, pytest, and dbt build against a Postgres service container).
