# xom-ecom: E-Commerce Data Pipeline and Analytics Dashboard

SWE40006 project. Xóm E-Com is a multi-region online retailer (see [data_context.md](data_context.md)).
This repository streams its order data into a Postgres warehouse and builds the analytics tables a
Streamlit dashboard reads in near real time.

This README is the source of truth for scope. [CLAUDE.md](CLAUDE.md) holds the detailed rules for the
data pipeline workstream.

## Scope

**In scope**

- A simulated source system (`xom_source`) seeded with Xóm E-Com's order history, and a mock
  generator that inserts new demo orders into it.
- A streaming ingest path: source poller -> raw data API (Flask) -> Kafka -> bronze consumer ->
  bronze (Postgres). It runs continuously; there are no scheduled batch runs.
- dbt transforms from bronze to silver to gold every 30 seconds, ending in a sales star schema and
  marts for the business questions in `data_context.md`:
  - discount impact on profit
  - profit and loss by segment
  - growth by market
  - customer retention
- A Streamlit dashboard (owned by the dashboard team) that reads `gold` and `ops.pipeline_runs`, and
  flags the data as stale after 2 minutes without a successful transform.

**Out of scope**

- Stream-processing frameworks (Flink, Faust, ksqlDB).
- Orchestrators (Airflow).
- Kafka Connect and Schema Registry.
- Raw snapshots to S3.
- Currency conversion.
- More than one data source.

## Architecture

```text
data/xomdata/*.csv --seed--> xom_source <--INSERT-- mock generator (demo)
                                 |
                                 | source poller (all history first, then new rows)
                                 v
                  raw data API (Flask) --> Kafka: raw.ecom_records --> bronze consumer
                                                                            |
                                                                            v
                  Streamlit <-- gold <-- silver <-- dbt every 30 s <-- bronze (append-only)
```

| Layer | Contents |
|---|---|
| `xom_source` | Simulated operational database: `sales_line`, `customer`, `product`, `region` |
| `bronze` | Every record version received, as `jsonb`, plus envelope fields and Kafka position |
| `silver` | Latest version of each record, typed, with derived fields and data-quality flags |
| `gold` | `dim_customer`, `dim_product`, `dim_region`, `dim_date`, `fct_sales_lines`, and the marts `mart_discount_impact`, `mart_segment_pnl`, `mart_market_growth`, `mart_customer_retention` |
| `ops` | `pipeline_runs` (ingest and transform history, freshness), `source_offsets` (poller position) |

## Data

The upstream dataset is the `e_commerce` schema of the xomdata SQL Server, extracted to
`data/xomdata/`:

| Table | Rows |
|---|---|
| sales lines | 51,290 (25,728 orders, order dates 2020-01-01 to 2023-12-31) |
| customers | 17,415 |
| products | 28,356 |
| regions | 3,828 |

Amounts are treated as USD; the source doesn't state a currency. `sales` is the amount before discount and `profit` is after it, as the data shows (to be confirmed with the data owner); gold adds `net_sales` = sales x (1 - discount). Mock orders are labeled
`is_sample`, dated when they are generated, and appear in every gold table with that label. The
data differs from `data_context.md` in places (segments, markets, categories), and it has a few
quirks, such as dates inside `order_id` that run 8 years behind `order_date`. Both are listed in
CLAUDE.md under "Known source quirks".

## Decisions

Settled on 2026-11-16:

| Topic | Decision |
|---|---|
| Real-time dashboard | Kafka streams into bronze continuously; dbt micro-batches every 30 s; no stream-processing framework |
| Data source | One source (`xom_ecom`) in a simulated source database, `xom_source`, read by a source poller |
| Historical data | Goes through the same path as new data (poller -> API -> Kafka -> bronze); no direct backfill |
| Demo data | A mock generator inserts orders into `xom_source`, before the API |
| Domain | Sales lines with a star schema and pain-point marts (replaces the earlier fashion price-observation design) |
| Categories | Kept as the source has them; no mapping, since there is one source |
| Currency | Treated as USD, unconverted; to be confirmed with the data owner |
| Mock data in gold | Always included, labeled `is_sample` |
| Freshness | 30 s transform interval; stale after 2 minutes |
| CI | None yet; checks run locally |
| Raw snapshots | Bronze `jsonb` only; no S3 |
| Interim `raw` schema and `/api/v1/tables` | Retired (done in step 2) |

Still open:
- The dashboard owner has to confirm the new gold contract.
- The data owner has to confirm the currency.
- `data_context.md` is either corrected to match the data or kept as the business brief.
- A CI workflow can be added later.

## Status and roadmap

**Built so far**
- **Extract tool:** `src/extract/` dumps the upstream SQL Server dataset to `data/xomdata/`.
- **Local Postgres:** runs under Docker Compose and holds both the warehouse (`xom`) and the source
  system (`xom_source`).
- **Groundwork (step 1):**
  - Leftover scripts removed.
  - `confluent-kafka` 2.16.1, `dbt-core` 1.12.7 and `dbt-postgres` 1.11.0 pinned.
  - Project `.venv` on Python 3.13.
  - First commit made.
- **Source system (step 2):**
  - `sql/source_schema.sql` defines `xom_source`: the four tables in schema `e_commerce`
    (`sales_line` is upstream's `ecom_sales`), each with `is_sample` and `change_seq`. One
    shared sequence sets `change_seq` on insert, and a trigger bumps it on update.
  - `python -m src.source.seed` creates the database, loads the CSVs once and checks the counts
    against `manifest.csv`. Re-running only verifies.
  - The interim `raw` schema, its loader (`src/load/`) and `/api/v1/tables` are retired. The API
    serves only `/health` until step 4.

- **Warehouse schemas (step 3):** `sql/schema.sql` defines `bronze.raw_records`,
  `bronze.rejected_records`, `ops.pipeline_runs` and `ops.source_offsets`.
- **dbt models (step 7, first half):** `dbt/` builds silver (5 models) and gold (4 dimensions,
  `fct_sales_lines`, 4 marts) with 82 tests. Verified against `xom_ci`, a throwaway database
  that `scripts/seed_ci_bronze.py` fills with every `xom_source` row in envelope shape:
  - every test passes, and gold reconciles with the source (51,290 lines; 2023 sales $2.19M);
  - edge cases pass: newest version wins, re-sent duplicate ignored, sample order labelled,
    late customer re-linked on the next build;
  - a steady-state cycle takes about 5 s, a full burst about 12 s (limit: 30 s).
  The dev warehouse builds too, but stays empty until the streaming path fills bronze.
- **Transform runner (step 7, second half):** `python -m src.pipeline.transform_runner` (also the
  `transform-runner` compose service) runs `dbt build` when bronze has rows newer than the last
  successful build, at most every 30 s, and records each run in `ops.pipeline_runs`. Verified on
  `xom_ci` with real dbt: history, new rows, a late customer, an idle tick, a failing test (gold
  kept, retried next tick) and a clean stop on SIGTERM. In dev it idles until bronze has rows.

- **Kafka and the write API (step 4):** one KRaft broker (`apache/kafka:4.1.0`) in Compose,
  host access on `127.0.0.1:9092` only; `kafka-init` creates `raw.ecom_records` (3 partitions,
  auto-create off). `POST /api/v1/records` (202, or 503 when Kafka does not acknowledge),
  `GET /api/v1/records` (paged bronze) and `GET /api/v1/sources`.
- **Bronze consumer (step 5):** `python -m src.ingestion.consumer` (compose service `consumer`)
  writes micro-batches to bronze, database first, then Kafka offsets. Invalid messages go to
  `bronze.rejected_records`. The envelope carries `source_version` (the source's `change_seq`),
  which is part of bronze's uniqueness key.
- **Source poller (step 6):** `python -m src.source.poller` (compose service `poller`). Its first
  run sent all 100,889 history records in about 4 s; bronze matches `manifest.csv`, and the
  runner's first dev builds reconcile gold with `xom_source`. Restarts resume from
  `ops.source_offsets`.

- **Gold snapshot (`dashboard_serve/`):** CSVs of every gold table, `schema.sql`, and
  `load_gold.py` to recreate `gold` in any Postgres, so the dashboard can be built before the
  stack runs on the dashboard owner's machine. See [dashboard_serve/README.md](dashboard_serve/README.md).

**Next**
8. **Mock generator and live demo:** done when generated orders appear in bronze and gold within about a minute.

## Run it (current setup)

```bash
cp .env.example .env               # then fill in the MSSQL_* values if you need to re-extract
python3.13 -m venv .venv && source .venv/bin/activate   # project venv, same Python as the image
pip install -r requirements-dev.txt

docker compose up -d postgres      # Postgres 17 on localhost:$POSTGRES_PORT (5434)
python -m src.source.seed          # creates xom_source and loads data/xomdata/*.csv (safe to re-run)

docker compose up -d --build       # kafka, api, consumer, poller, transform-runner
                                   # the poller's first run streams all history into bronze

docker compose exec -T postgres psql -U xom -d xom -v ON_ERROR_STOP=1 < sql/schema.sql   # bronze, ops

# dbt against the throwaway CI database, filled with fixture bronze rows
python scripts/seed_ci_bronze.py --reset --edge-cases
cd dbt && set -a && source ../.env && set +a
DBT_TARGET=ci dbt build            # silver + gold + 82 tests in about 10 s
cd ..

pytest -q                          # the seed tests use a throwaway database, never xom_source
E2E=1 pytest tests/e2e -v          # availability checks against the running stack
ruff check . && ruff format --check .
```

`API_PORT` defaults to 5000. On macOS, AirPlay Receiver usually holds port 5000, so
`.env.example` uses 5001.

To look at the source system: `docker compose exec postgres psql -U xom -d xom_source`, then
for example `SELECT count(*) FROM e_commerce.sales_line;`.

The commands for the target pipeline are in [CLAUDE.md](CLAUDE.md) under "Commands".

## Re-extracting from SQL Server

You need unixODBC and Microsoft's "ODBC Driver 18 for SQL Server" on the machine
(`brew install unixodbc`, then `brew install msodbcsql18` from the `microsoft/mssql-release` tap).
Then run:

```bash
pip install -r requirements-extract.txt
python -m src.extract.export_sqlserver --schema e_commerce
```

If connecting fails with `OpenSSL library could not be loaded`, the driver found OpenSSL 4 at
`/opt/homebrew/opt/openssl`; it supports only OpenSSL 1.0, 1.1 and 3.x. Point that link at
OpenSSL 3 with `ln -sfn ../Cellar/openssl@3/<version> /opt/homebrew/opt/openssl`. A `brew upgrade`
can undo this.
