# CommercePulse dashboard handover

CommercePulse is the Streamlit and Plotly analytics application for the SWE40006 Xóm E-Com project. It turns PostgreSQL Gold sales data into reports for finance, growth, and retention. It offers exactly five pages in this order: **Overview → Sales Trend → Categories → Geography → Pipeline Health**.

Gold is the reporting contract. CommercePulse reads its published facts, dimensions, and marts without writing to the warehouse. Pipeline & Database owns ingestion, ETL, and the Gold schema. DevOps owns infrastructure, deployment, and operations. The dashboard workstream supplies the application, tests, documentation, and a runnable container definition.

## Architecture

```mermaid
flowchart LR
    G[PostgreSQL Gold] --> P[PostgreSQL data provider]
    P --> S[Normalized snapshot]
    S --> A[Scoped analytics]
    A --> V[Five Streamlit views]
    V --> U[Plotly charts, tables, and CSV exports]
```

| Path | Responsibility |
| --- | --- |
| `dashboard/app.py` | Streamlit entry point. Starts the session heartbeat, registers the five views, renders the shared navigation and date toolbar, caches Gold reads, and passes the snapshot and filters to the active view. |
| `dashboard/components/` | Shared navigation, filters, layout, number formatting, charts, velocity card, tables, CSV exports, and the per-view report context. |
| `dashboard/data/provider.py` | Defines the provider protocol, normalized snapshot, and errors that the UI can display. |
| `dashboard/data/postgres_provider.py` | Connects through SQLAlchemy and psycopg2, reads Gold in one repeatable-read transaction, validates types and keys, normalizes money to integer cents, and returns table counts and a read timestamp. |
| `dashboard/data/analytics.py` | Applies the selected date range and Gold sample scope and computes sales, profitability, growth, velocity, and retention metrics. |
| `dashboard/views/` | Builds and exports the five reports using the same snapshot and shared components. |
| `dashboard/styles/` and `dashboard/static/fonts/` | CommercePulse styles and bundled fonts. Streamlit static serving is enabled in `.streamlit/config.toml`. |
| `tests/dashboard/` | Unit and Streamlit AppTest checks, plus a PostgreSQL integration test against the supplied snapshot. |

The provider reads the current fact and marts into memory. Normal interactions apply filters in the dashboard rather than issuing per-widget SQL queries. The current design was verified at the supplied snapshot size. Assess memory and query latency against production volume. If needed, move limiting and aggregation into the provider as a separate change.

## Repository structure

The tree shows files relevant to dashboard development and deployment. Package initializers and individual fonts and snapshot CSVs are grouped for readability.

```text
.
├── .python-version                         # Python 3.13
├── pyproject.toml                          # Python constraint and pytest settings
├── .dockerignore                           # Docker build context exclusions
├── .streamlit/config.toml                  # Runtime theme and static serving
├── dashboard/
│   ├── app.py                              # Runtime entry point
│   ├── requirements.txt                    # Runtime dependencies
│   ├── requirements-dev.txt                # Runtime dependencies plus pytest
│   ├── README.md                           # Technical handover
│   ├── GOLD_DATA_AUDIT.md                   # Gold contract and B1–B4 coverage
│   ├── components/
│   │   ├── charts.py, filters.py, formatting.py, layout.py
│   │   ├── navigation.py, report.py, tables.py, velocity.py
│   │   └── session_heartbeat.py, session_registry.py
│   ├── data/
│   │   └── analytics.py, postgres_provider.py, provider.py
│   ├── views/
│   │   └── overview.py, sales.py, categories.py, geography.py, pipeline_health.py
│   ├── static/fonts/
│   └── styles/theme.css
├── tests/dashboard/
│   ├── test_app.py, test_data.py
│   └── test_session_heartbeat.py, test_session_registry.py
├── dashboard_server/
│   ├── README.md                           # Development snapshot setup
│   ├── schema.sql                          # Gold contract reference
│   ├── requirements.txt                    # Separate loader/export dependencies
│   ├── load_gold.py                        # Seeds or verifies an isolated development DB
│   ├── export_gold.py                      # Pipeline-side snapshot export utility
│   └── data/                               # Manifest and nine development CSVs
├── deploy/
│   ├── dashboard.Dockerfile                 # Dashboard container build
│   └── DASHBOARD_HANDOFF.md                 # Deployment quick reference
└── references/layout.html                  # Original design reference
```

The runtime is `dashboard/app.py` plus its Python packages and static assets. The test files and `dashboard_server/` tooling are for development. Production data comes from PostgreSQL. The supplied Dockerfile packages dashboard runtime files and Streamlit configuration, and excludes the loader, tests, snapshot CSVs, and customer dimension records.

## Dashboard features

All business pages use an inclusive order-date range and the Gold data selector. The default is **Historical only**. Users can include or isolate Gold rows marked `is_sample`; this switches the date selection to the latest available 90-day window for that scope. The comparison selector supports previous year, the immediately preceding period of equal length, or no comparison. A prior window needs to fall within the calendar bounds. Charts, ledgers, and report exports reflect their applicable filters. Table sorting happens in the browser. CSVs use the report's default row ordering.

| Page | KPIs and visuals | Page controls and sources | Business requirements |
| --- | --- | --- | --- |
| **Overview** | Net sales, orders, known customers, average order value, profit, net sales and profit trend, top products, segment and market snapshots, profit by category, segment P&L, and a retention cohort heatmap. The customer activity section shows repeat purchases, observed lifetime sales, recency/frequency/monetary groups, and high-value inactivity when enough history is selected. | Daily, weekly or monthly trend; customer activity segment. Uses the sales fact, customer/product/region dimensions, quarterly segment P&L and customer retention marts. | B2 and B4. Also shows B1 loss-making orders by segment and B3 market context. |
| **Sales Trend** | Period net sales, orders, peak day, sales per order, net sales and order count trend, distinct orders by weekday, weekday/weekend net sales share and a daily ledger. Periods without sales are gaps. | Daily, weekly, monthly or quarterly trend. Date/weekday search and velocity status filter apply to the ledger and its CSV. Uses the sales fact and its `order_date`. | Shared sales context for B1–B4. |
| **Categories** | Active categories, top category by net sales, order volume and growth leader. Includes the net sales pie, volume versus net sales bubble chart, average line discount by category, profit and margin by discount band, and up to three profitable products per category. | Category selection and catalog search. Uses the fact, product dimension, and monthly discount mart at its published grain. Product-level searches hide the mart section. | B1, using observed transactions to compare discount and profitability. |
| **Geography** | Top country, highest country AOV, customer growth leader, country coverage, market net sales treemap, top cities and a regional ledger. Detail reports include profitability, cross-region customers, and month-over-month and year-over-year growth. | Market and country filters, distribution metric, ledger search, profitability grouping and region for monthly growth. Uses the fact, region and customer dimensions, and the annual market growth mart. The market treemap is shown in the all-market net sales view. | B3. |
| **Pipeline Health** | Readable Gold tables, total sales lines, sales lines in view, last successful dashboard read, order coverage, latest sales-line ingestion time, and a downloadable inventory. | Date range and sample scope affect the in-view count. Coverage and latest ingestion reflect the selected Gold data scope. Inventory counts are warehouse-wide. Uses the loaded snapshot and relation counts. | Operational context for B1–B4. |

Gross sales are the Gold `sales` amount before discounts. Net sales, discounts and profit use their corresponding Gold amounts. Average order value divides net sales by distinct orders, and margin divides profit by net sales. Orders are distinct by `(source, is_sample, order_id)`. Known customer counts use distinct customer keys. Orders or customers can appear in multiple dimension groups, so grouped counts are not additive.

The marts keep their published grain and sample flag. The dashboard shows pre-aggregated rows only when their full recorded order-date coverage fits the selected window. Fact-based reports support partial date windows. Monthly geographic growth displays complete selected months and uses the same market, country, region, and sample scope for prior-period baselines.

## Database contract

Use a PostgreSQL database exposing the relations defined in [`dashboard_server/schema.sql`](../dashboard_server/schema.sql). All nine are read when the snapshot loads.

| Required relation | Purpose and essential dependencies |
| --- | --- |
| `gold.fct_sales_lines` | Sales line fact. Unique text `sales_line_key`; text `source`, `order_id` and dimension keys; `order_date` as date; segment and discount-band labels; integer quantity; numeric sales, net sales, profit, discount amount and discount rate; Boolean `is_sample`; currency code; and `ingested_at` as a time zone-aware timestamp. |
| `gold.dim_customer` | Joins `customer_key` and `is_unknown` for known-customer counts and retention. The app reads the key and flag and counts rows. Customer names and demographic attributes are outside the app query. |
| `gold.dim_product` | Joins `product_key`, product name, category, subcategory and `is_unknown` for merchandising. |
| `gold.dim_region` | Joins `region_key` to market, region, country, state and city for geography. |
| `gold.dim_date` | Supplies minimum and maximum `date_day` for selectable dates. The calendar may extend past the latest sales line. |
| `gold.mart_segment_pnl` | Published quarterly segment metrics. Quarter, segment, sample flag, counts, gross/net sales, discounts, profit, margin, loss-order counts, median order value and order coverage dates. |
| `gold.mart_customer_retention` | Cohort month, elapsed months, sample flag, cohort and active customer counts, retention ratio, order count, sales, profit and order coverage dates. |
| `gold.mart_discount_impact` | Monthly category and discount-band metrics. Sample flag, counts, average discount, gross/net sales, discounts, profit, margin, loss share and order coverage dates. |
| `gold.mart_market_growth` | Annual market and region metrics. Sample flag, customer/order counts, net sales, previous year net sales, YoY change, profit, margin and order coverage dates. |

The normalized fact requires non-null order keys, dates, sample flags, and currency. It expects a single uppercase three-letter currency code and non-null monetary values representable in whole cents. Unknown product and location labels are handled without dropping the associated amounts. Duplicate sales-line keys after the dimension joins are rejected.

Provision the application role with **CONNECT** on the target database, **USAGE** on `gold`, and **SELECT** on the nine relations. The dashboard currently reads all columns from the four marts. Pipeline & Database and DevOps should make sure permissions survive any relation rebuilds. The runtime role needs no database or schema creation privileges and no data modification grants.

Each load opens one **REPEATABLE READ, READ ONLY** transaction. It reads the fact and joins, date bounds, marts and table counts under a consistent snapshot. It sets the transaction time zone to UTC and an SQL statement timeout of 20 seconds. The connection timeout defaults to five seconds. The provider closes the connection and disposes its engine after the load. See [Data refresh and dynamic updates](#data-refresh-and-dynamic-updates) for when it reads again.

## Data validation and reconciliation

The 2026-11-17 development snapshot provides a reproducible historical baseline:

| Check | Verified value |
| --- | ---: |
| Gold relations | 9 |
| Rows across all relations | 105,673 |
| Sales lines | 51,290 |
| Distinct orders | 25,728 |
| Order-date coverage | January 1, 2020 through December 31, 2023 |
| Gross sales | $6,517,674.00 |
| Net sales | $5,565,259.31 |
| Profit | $1,065,413.58 |

These are integration test expectations for that snapshot only. Runtime figures come from Gold and change as the warehouse changes. The snapshot labels the currency USD and the dashboard displays it accordingly. Confirmation from the data owner is pending. See the [full data audit](GOLD_DATA_AUDIT.md) for column types, null rates, joins and mart reconciliation.

## Local development setup

Use **Python 3.13** for the dashboard. The repository's `.python-version`, `pyproject.toml` constraint (`>=3.13,<3.14`), and Docker image use this version. The Project Brief §3.1 specifies Python 3.11.

1. Use the supplied handover checkout or clone the shared `dashboard` branch once the handover changes are available there.

   ```bash
   git clone --branch dashboard --single-branch https://github.com/dt-azure/swe40006-xomecom-dashboard.git
   cd swe40006-xomecom-dashboard
   ```

2. From the repository root, create and activate the virtual environment. Use a Python 3.13 distribution that provides `venv` and pip.

   ```bash
   python3.13 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r dashboard/requirements.txt
   ```

3. Use an existing Gold database or follow the [development snapshot setup](../dashboard_server/README.md) to load one into a separate local database. The loader has its own requirements and replaces the target `gold` schema. Use the dashboard's read-only connection for app verification. Replace the placeholders below with credentials valid for the target database.

   ```bash
   export DASHBOARD_DATABASE_URL='postgresql://dashboard_reader:URL_ENCODED_PASSWORD@127.0.0.1:5440/xom_gold'
   ```

4. Start Streamlit from the repository root and open [http://localhost:8501](http://localhost:8501). A populated Overview confirms that the app can query Gold.

   ```bash
   streamlit run dashboard/app.py
   ```

5. Stop Streamlit with **Ctrl+C** in its terminal. Run `deactivate` when finished with the virtual environment.

## Environment variables and secrets

`DASHBOARD_DATABASE_URL` is the runtime connection setting. It accepts `postgresql://` and `postgresql+psycopg2://` URLs with a database name. The provider uses psycopg2 for both formats. Percent-encode reserved characters in credentials. Supply the URL via a shell environment variable for development or inject it into the running container from the team's secret store. Keep actual credentials out of Git, Compose files, images, logs and shared terminal transcripts.

| Where the app runs | PostgreSQL hostname and port |
| --- | --- |
| Host terminal, with the snapshot published locally | `127.0.0.1:5440` when configured as in the development setup. |
| Docker Desktop, with a reachable snapshot exposed on the host | `host.docker.internal:5440` for the verified local setup. |
| Dashboard and PostgreSQL containers sharing a Docker network | PostgreSQL service name and its internal port, usually `5432`. A dashboard container's loopback addresses the dashboard container itself. |
| Test or production container connecting to managed PostgreSQL | Warehouse DNS name and configured port, reachable from the container's network. |

Follow the warehouse's TLS policy for deployment. When certificate and hostname verification is required, use `sslmode=verify-full` and set `sslrootcert` to the CA file path inside the container. Mount the CA at that path. For example, append `?sslmode=verify-full&sslrootcert=/run/certs/warehouse-ca.pem` to the connection URL when that path is configured by DevOps.

## Docker build and local verification

Run the build from the repository root so `.` is the build context. The [Dockerfile](../deploy/dashboard.Dockerfile) uses `python:3.13-slim` and starts Streamlit as `commercepulse` (UID 10001) on container port `8501`.

```bash
docker build -f deploy/dashboard.Dockerfile -t commercepulse-dashboard .
```

Export `DASHBOARD_DATABASE_URL` with a hostname reachable from the container. If PostgreSQL is on the Docker daemon's default network or is reachable outside Docker, use the appropriate network endpoint. If using a user-defined shared network, attach the app with `--network NETWORK_NAME` and use the database service name in the URL.

```bash
docker run -d --rm --name commercepulse-dashboard \
  -p 127.0.0.1:8501:8501 \
  --env DASHBOARD_DATABASE_URL \
  commercepulse-dashboard

docker logs --follow commercepulse-dashboard
```

The host binding above is for local verification. Open [http://localhost:8501](http://localhost:8501), verify that Overview renders data, and check Pipeline Health for populated Gold inventory rows. Use **Ctrl+C** to leave the log stream and stop the container with:

```bash
docker stop commercepulse-dashboard
```

The build copies only dashboard runtime files and `.streamlit/config.toml`. Snapshot loading, Docker Compose wiring and publishing to a registry belong outside this image. The [deployment quick reference](../deploy/DASHBOARD_HANDOFF.md) summarizes the container contract.

## Health checks

| Check | What it verifies | How to check |
| --- | --- | --- |
| Streamlit liveness | The app server answers HTTP. The Dockerfile checks this every 30 seconds after a startup grace period. | `curl --fail http://127.0.0.1:8501/_stcore/health` |
| Database readiness | The deployed app can authenticate and read the Gold relations as its runtime role. | Open the deployed dashboard in a browser and verify that Overview shows data and Pipeline Health lists all required relations. This exercises the Streamlit session and WebSocket path. |

HTTP 200 from `/_stcore/health` can occur even when database connectivity fails. Application readiness is verified through the dashboard. The service has no separate `/health` or `/version` endpoints.

## Testing

Run tests from the repository root with the development requirements installed. The root pytest configuration marks the live PostgreSQL test as `integration`.

```bash
python -m pip install -r dashboard/requirements-dev.txt
python -m pytest -q -m 'not integration' tests/dashboard
```

To include the integration test, point it at an isolated PostgreSQL database seeded with the supplied 2026-11-17 fixture. Use separate production smoke tests to verify connectivity and report behavior against changing production data.

```bash
DASHBOARD_TEST_DATABASE_URL="$DASHBOARD_DATABASE_URL" python -m pytest -q tests/dashboard
```

Without `DASHBOARD_TEST_DATABASE_URL`, the integration test skips. Unit and configuration tests cover formulas, scope changes, empty data, signed or zero chart inputs, navigation order, and currency and CSV handling. The integration test checks the full historical reconciliation, renders all five views in Streamlit AppTest, and verifies the category pie, market treemap, weekday split, filters and exports.

## Recently Active Streamlit Sessions

The heartbeat estimates how many Streamlit sessions have been active recently, including passive readers. The shared dashboard shell records the first heartbeat immediately and uses [Streamlit's timed fragment](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment) to refresh it about every **30 seconds** while the session remains connected. The fragment runs on all five pages and accesses only session state and the in-memory registry.

- Each Streamlit session receives one random UUID. Navigation and filter changes reuse that ID. A second tab starts a separate session, and reloading can start another. One person can therefore contribute multiple sessions.
- A session counts while its last successful heartbeat is **less than 90 seconds old**, measured with a monotonic clock. After a disconnect, future heartbeats stop. An expired entry is excluded as soon as the count is queried, even if bounded cleanup has yet to delete it.
- Tab visibility is outside the metric. Streamlit supports custom browser components, but browser timer throttling and connection changes can delay visibility or heartbeat updates. Connected hidden tabs may still count, and the metric cannot establish whether a person is reading.
- The registry stores only random session IDs and their last monotonic heartbeat times. Memory is local to each Streamlit process. Restarting the container clears the registry, and each replica sees only the sessions that heartbeat to it. An idle process can retain expired entries until the next write or count query.

`dashboard.components.session_heartbeat.get_session_metrics()` is the internal Python interface. It returns the current process's count, the interval, the timeout, and registry availability. A failed read returns an unavailable status and a count of `None`. CommercePulse has no authenticated administrator surface for displaying this metric, so it stays internal.

The Dashboard team owns the registry and metric definition. DevOps owns CloudWatch RUM and any future export of the aggregate count. In-memory session metrics are local to the app unless a controlled publisher reads the internal interface in each process and sends the count to a CloudWatch custom metric. DevOps would need to define the publishing cadence, IAM permissions, and aggregation across replicas. Publish aggregate counts only.

Run the heartbeat tests with `python -m pytest -q tests/dashboard/test_session_registry.py tests/dashboard/test_session_heartbeat.py`. Registry tests use a fake monotonic clock. AppTest renders all five reports with a synthetic snapshot and checks session identity across pages and filters. To verify browser scheduling, open a local dashboard tab, leave it idle for more than 90 seconds, and observe calls to `SessionRegistry.heartbeat` with local instrumentation. Expect the same UUID about every 30 seconds with no additional shell runs, Gold loads, or chart renders.

## Data refresh and dynamic updates

- Successful reads are cached in memory by connection URL for **30 seconds**, with up to two cached entries per app process. Within that window, interactions reuse the snapshot.
- Gold data refreshes when a dashboard interaction or browser reload triggers a full run after cache expiry. If new orders fall outside the current date filter or Gold data scope, adjust both to see them. A Gold data load under the same contract requires no dashboard code redeployment.
- **Orders through** in the header is the latest order date for the selected Gold data scope, independent of the date range. **Latest sales-line ingestion** on Pipeline Health is the maximum Gold `ingested_at` for that scope.
- **Warehouse checked** is the UTC time when the dashboard completed its successful Gold read. It can remain unchanged while that result is cached. It does not identify when the warehouse finished an ETL run.
- The dashboard does not read `ops.pipeline_runs`. Pipeline run history, transform status, and operational staleness alerts need an agreed telemetry contract and a separate implementation.

## DevOps Integration Checklist

**Provided by Dashboard:** the five-page application, read-only provider, runtime dependencies, Dockerfile, liveness check, dashboard-specific tests and snapshot reconciliation, plus this runbook.

**Receiving DevOps teammate:**

- [ ] Build the dashboard image from the repository root with `deploy/dashboard.Dockerfile`. Integrate the build, versioning and registry publishing into the existing CI/CD workflow.
- [ ] Add the image or build definition to the team's Docker Compose configuration. Connect the service to the network that reaches PostgreSQL and configure its DNS name, port, routes and access rules.
- [ ] Inject `DASHBOARD_DATABASE_URL` at runtime from the secret store. Coordinate a SELECT-only role with Pipeline & Database and mount the required TLS assets.
- [ ] Route the configured hostname and application ingress to container port `8501`, forward WebSocket upgrades and apply the team's access control and TLS policy.
- [ ] Deploy to the test environment first. Check liveness, open Overview, navigate all five pages, change date and scope filters, and download a CSV. Confirm chart values reconcile to the test data.
- [ ] Check database readiness with the deployed role. Verify the role's grants and confirm that the dashboard starts its read-only transaction. Inspect grants without attempting writes to the warehouse.
- [ ] Confirm the intended audience can reach and use the app over the deployed ingress.
- [ ] Monitor container liveness, app errors, database connectivity and latency. Coordinate warehouse run and freshness monitoring with Pipeline & Database once the telemetry contract is available.
- [ ] Promote through the existing production approval workflow and preserve the team's tested rollback procedure and previous image version.

## Known limitations and dependencies

- The supplied data is historical through **December 31, 2023**. New records depend on the pipeline publishing to Gold. The data owner still needs to confirm the USD designation.
- Gold provides order dates and warehouse ingestion timestamps. Sales Trend uses a weekday distribution and weekday/weekend net sales split. Hourly transaction analysis requires an order-time field.
- Shipment and review analytics are outside the current dashboard scope, and Gold has no source records for either.
- Discount analysis describes observed transactions. Causal discount impact requires a comparison design and additional data. Customer analysis shows observed lifetime sales, retention and inactivity. It has no predictive churn or lifetime-value model.
- Pipeline Health reports data coverage and read metadata. Warehouse execution history and staleness monitoring need the operations feed and an agreed freshness policy.
- Python 3.13 is the implemented runtime. The team needs to resolve its difference with the Project Brief's Python 3.11 target.
- Production readiness depends on a working network path, TLS settings, and read-only access to all nine Gold relations.

## Ownership and workstream boundaries

| Dashboard | Pipeline & Database | DevOps |
| --- | --- | --- |
| Streamlit app, styling, charts, reports and CSVs | Gold schema, source ingestion and ETL transformations | CI/CD workflows, deployment automation and Docker Compose integration |
| Read-only provider, metric definitions and dashboard reconciliation tests | Source data quality, warehouse reconciliation and Gold availability | EC2/RDS infrastructure, network rules, ingress, TLS and secrets |
| Dashboard tests, documentation and container handoff artifact | Pipeline run logs, freshness contract and dynamic data loading | Operational monitoring, alerts, production approvals, releases and rollback |

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| App requests `DASHBOARD_DATABASE_URL` | Export it in the shell launching Streamlit or inject it into the running container. Restart after changing the runtime environment. |
| PostgreSQL connection is refused | Confirm the server is running and listening on the configured IP and port. For the local fixture, check the Docker port mapping and use `5440` from the host when that is the published port. |
| Postgres works on the host but fails from Docker | Compare the configured host with the container's network. Use the PostgreSQL service name and internal port on a shared network, or the reachable warehouse DNS name for a remote service. |
| Gold relation is missing | Check the database name and use the [schema reference](../dashboard_server/schema.sql) to verify all nine relations. Seed an isolated development database if needed. Ask Pipeline & Database to publish production relations. |
| Insufficient PostgreSQL permissions | Verify CONNECT, schema USAGE and SELECT on each relation using the actual runtime role. Check grants again after marts are rebuilt. |
| Charts or marts are empty | Select historical rows for the supplied snapshot and choose dates in 2020–2023. Clear narrower page filters. For pre-aggregated marts, choose a range covering the complete order-date interval of the rows. |
| New Gold rows are not visible | Wait for the 30-second cache to expire, then refresh or interact with the app. Check **Warehouse checked** and **Orders through**, and widen the current date range or change the sample scope as needed. |
| Container is healthy but reports fail | Liveness only confirms HTTP. Check `docker logs commercepulse-dashboard`, run a Gold SELECT with the deployment role from the app's network, and verify secrets, TLS and the ingress WebSocket route. |

## Final handover status

The five-page dashboard, Gold integration, analytics, tests, deployment Dockerfile and documentation are ready for DevOps integration. Local verification covers Postgres-backed reconciliation, navigation, the retained visualizations and the container entry point. DevOps owns integration and promotion through test and production. Pipeline & Database owns warehouse availability and the remaining operational telemetry contract. Production deployment has not been verified.
