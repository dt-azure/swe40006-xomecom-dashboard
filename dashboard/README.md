# CommercePulse

CommercePulse is the Streamlit reporting workstream for the SWE40006 E-Commerce Data Pipeline. It implements the six layouts in [the CommercePulse reference](../references/layout.html) with native Streamlit controls, interactive Plotly charts and filtered CSV reports. The default provider runs entirely from a synthetic snapshot.

## Run locally

Run these commands from the repository root with Python 3.11–3.13. On Windows, activate the environment with `.venv\Scripts\Activate.ps1`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

Streamlit prints the local URL. Date and comparison settings carry between pages. The date range includes both dates. Business pages filter by order creation date, and Pipeline Health filters by execution start date in UTC. Previous period uses an equally long preceding window. Previous year shifts both endpoints back by one calendar year. Comparisons appear when the complete comparison window is available and the prior denominator is defined.

Every page offers an **Export Report** CSV in the masthead. On Overview it contains the daily revenue and synthetic conversion series, regardless of the chart's grouping. On the other views it contains the filtered ledger rows, also available from **Download CSV**. Tables support column-header sorting in the browser. Downloads preserve the report's default ordering with the current query and filters.

## Dashboard views

| View | What you can explore |
| --- | --- |
| Overview | Five KPIs, revenue and conversion by period, top products, attributed channels, regional revenue and device performance |
| Sales Trend | Daily through quarterly revenue and orders, weekday and weekend buying patterns, and a searchable daily ledger |
| Categories | Department and product filters, category share and volume rankings, and order and SKU metrics |
| Geography | Brazilian state tile map, metro rankings and a regional ledger with region and state filters |
| Delivery & Reviews | Carrier and rating filters, transit time and review scores, variance and SLA distribution, and a shipment ledger |
| Pipeline Health | Ingestion statistics, stage status, filtered run history and diagnostics for simulated success, warning and failure cases |

## Demo data and definitions

The mock provider generates its data once per Streamlit process and caches it. Seed `40006` generates orders and line items between January 2023 and August 15, 2024, plus 90 days of independent synthetic ETL runs. IDs, payment methods, locations, shipment dates and ratings are linked to the orders. The geography uses an Olist-inspired set of Brazilian cities, states and regions with synthetic demand. The state tile map is schematic. Currency is BRL, stored as integer cents and converted to decimal BRL for reporting. Bundled Inter and Plus Jakarta Sans fonts are distributed with their OFL notices under `static/fonts/`.

- **Gross revenue** is merchandise value on non-cancelled orders. Freight is reported separately, and the recorded payment is merchandise plus freight. Cancelled order lines remain in the source snapshot for reconciliation and are excluded from sales aggregates.
- **Orders and customers** count distinct order and customer IDs in the selected scope. A multi-category order contributes once per category it includes. Category revenue adds back to the overall total. Average order value divides merchandise value by non-cancelled orders.
- **Fulfilment rate** is delivered orders divided by non-cancelled orders for the order-date cohort, measured as of the demo snapshot. Recent cohorts can still have orders in transit.
- **Delivery duration** runs from dispatch to actual arrival. Variance is actual minus estimated arrival. Delayed means any positive variance. Early means more than 12 hours ahead of the estimate. The on-time KPI includes early deliveries. Unreviewed shipments contribute to delivery KPIs and are excluded from average review score.
- **Conversion and channel attribution are provisional.** Demo site conversion divides synthetic checkout completions, including subsequently cancelled orders, by synthetic sessions. Product conversion uses separate SKU-level sessions and includes one conversion per ordered SKU per order. Channel and device revenue assigns each order to one synthetic channel and device. Device conversion uses the synthetic session data.
- **Pipeline telemetry is simulated.** A run counts as successful only when its status is Success. Warning and Failed count as exceptions. Rows report writes to PostgreSQL Raw and can be nonzero after a downstream failure. The topology shows the latest run in scope and stage-level details for a selected run. Manual ingestion is disabled in demo.

Inventory and returns need their own upstream data and are outside the current catalog metrics. Commerce dates are demo local dates using Brazil's São Paulo reporting clock. Pipeline timestamps are UTC.

## PostgreSQL integration

`DASHBOARD_DATA_SOURCE` defaults to `mock`. To check the adapter's configuration path, set `DASHBOARD_DATA_SOURCE=postgres` and supply `DASHBOARD_DATABASE_URL` through your environment or deployment secret store. Use a SQLAlchemy `postgresql+psycopg2://` URL containing the database name. Omit credentials from source control.

The PostgreSQL adapter validates configuration and displays an actionable message until mart mappings are supplied. It currently performs no queries. The integration belongs in `data/postgres_provider.py`. The provider normalizes results to the `Snapshot` contract in `data/provider.py` so page code can continue to use the same analytics. Query the approved, read-only relations with bind parameters for filter values. Use bounded extracts or suitable aggregates as volume grows.

### Reporting contract and team handoff

The names below are data frames in the dashboard contract. Ask the Pipeline & Database team for the real schema and relation names, join keys, grain, column types, nullability and representative records for each available feed.

| Frame | Grain | Fields and conventions |
| --- | --- | --- |
| `orders` | One row per order | `order_id`, stable `customer_id`, `date`, `ordered_at`, normalized `status`, `city`, `state`, `region`, `revenue_cents`, `shipping_cents`, `payment_cents`, `payment_method`, `carrier`, `dispatched_at`, `estimated_at`, `delivered_at`, nullable `reviewed_at` and `review_score` (1–5), and publishable `review_note`. `channel` and `device` require tracking data. |
| `items` | One row per order item | Unique `item_id`, `order_id`, `sku`, `product`, `category`, `department`, integer `quantity`, `unit_price_cents` and `revenue_cents`. Non-cancelled lines must reconcile with order merchandise revenue. |
| `traffic` | One row per date, channel and device | `date`, `channel`, `device`, integer `sessions` and `conversions`. Requires a web analytics or attribution source. |
| `product_traffic` | One row per date and SKU | `date`, `sku`, integer `sessions` and `conversions`. Requires SKU-level tracking. |
| `runs` | One row per execution | `run_id`, UTC `started_at`, `target`, `status` (Success, Warning, Failed), `duration_seconds`, Raw rows written as `rows`, and publishable `diagnostic`. |
| `stages` | One row per run and stage | `run_id`, `stage`, `status` (Success, Warning, Failed, Skipped), and `duration_seconds`. Map source steps to the six stages in the planned topology. |

Also confirm the reporting time zone and revenue recognition rules, including discounts, refunds, cancellations, freight and currency. Confirm the customer deduplication rules, shipment and review grain for multi-shipment orders, and the report's coverage and freshness watermark. Identify which optional acquisition and telemetry feeds will be available. For deployment, provide the read-only role, secret name, permitted network path and TLS settings. Use typed empty frames for unavailable optional feeds and expose that availability in the UI when the real adapter is implemented.

## Tests and deployment

```bash
python -m pip install -r dashboard/requirements-dev.txt
python -m pytest -q dashboard/tests
```

The tests exercise data reproducibility, metric reconciliation, delivery chronology, ETL outcomes, navigation, filters, diagnostics and provider configuration. Streamlit AppTest renders each page and checks the report download controls.

For a container, copy `.streamlit/config.toml` and the `dashboard/` package, install its requirements and run the same entry point with `--server.address=0.0.0.0 --server.port=8501 --server.headless=true`. Route browser WebSocket upgrades alongside HTTP and use `/_stcore/health` for the container health check. Use the deployment's secret configuration for PostgreSQL connection settings. The runtime includes the fonts and uses no external analytics, maps, fonts or APIs in demo.
