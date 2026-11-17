# CommercePulse deployment handoff

The dashboard reads PostgreSQL Gold. The supplied snapshot contains nine tables and 105,673 rows, including 51,290 sales lines for 25,728 orders from January 1, 2020 through December 31, 2023. The snapshot reconciles to $6,517,674.00 gross sales, $5,565,259.31 net sales and $1,065,413.58 profit. Currency is shown as USD per Gold, pending data-owner confirmation.

The work is on branch `dashboard`. The dashboard and the supplied snapshot loader have separate responsibilities. The dashboard runs read-only queries. The loader seeds a standalone development database and replaces its `gold` schema, so the deployment image excludes the loader, snapshot CSVs and customer dimension records.

See the [technical dashboard handover](../dashboard/README.md) for current verification, the five-page navigation and the DevOps integration checklist. The production role, network path, and operations feed remain rollout dependencies.

## Build and run

The dashboard image uses the repository's Python 3.12 target and runs as the non-root `commercepulse` user.

```bash
docker build -f deploy/dashboard.Dockerfile -t commercepulse-dashboard .
docker run --rm --name commercepulse-dashboard \
  -p 127.0.0.1:8501:8501 \
  --env DASHBOARD_DATABASE_URL \
  commercepulse-dashboard
```

Export a URL reachable from the container before running the command. A container's `127.0.0.1` refers to that container. For a local PostgreSQL container, attach the two services to a shared Docker network and use PostgreSQL's service name and internal port in the URL. Deploy the image with the warehouse hostname and database access injected as a secret.

| Item | Deployment contract |
| --- | --- |
| Connection | `DASHBOARD_DATABASE_URL=postgresql://…` or `postgresql+psycopg2://…`. Apply the warehouse's TLS settings via the connection URL and mount the CA if required. |
| Privileges | Connect to the warehouse, use schema `gold` and read the nine relations listed below. The dashboard uses a repeatable-read, read-only transaction. |
| Port and ingress | HTTP on `8501`. Forward WebSocket upgrades and apply the team's normal access control for internal analytics. |
| Health | `GET /_stcore/health` checks Streamlit liveness. Verify Overview loads against the deployment URL to check database readiness. |
| Refresh | Successful Gold reads are cached in memory for 30 seconds. A subsequent dashboard interaction or reload reads again after expiry. The header displays data coverage, and Pipeline Health shows the time of the warehouse read. |
| Scale | The app reads the current Gold sales-line fact into memory and filters locally, verified at the supplied snapshot size. Push date filters and aggregations into PostgreSQL if fact volume grows materially. |

PostgreSQL relation contract:

- `gold.fct_sales_lines` provides dates, keys, amounts, units, currency, provenance and ingestion timestamps.
- `gold.dim_customer`, `gold.dim_product`, and `gold.dim_region` supply joined dimension keys and labels. The app does not fetch customer names or demographic attributes.
- `gold.dim_date` supplies the date bounds, including days without sales.
- `gold.mart_segment_pnl`, `gold.mart_customer_retention`, `gold.mart_discount_impact`, and `gold.mart_market_growth` supply their published quarterly, cohort, monthly and annual views.

Before rollout, confirm the Gold contract against [schema.sql](../dashboard_serve/schema.sql), provision the database role and network path, and smoke test the deployed URL with that role. For operational alerts and run history, they need to supply the `ops.pipeline_runs` schema, success definition and quiet-period staleness policy. The dashboard shows Gold availability and read metadata until those feeds are connected.

## Repository structure

The tree lists source files and the supplied snapshot. It excludes local environments, bytecode, caches and Git metadata. The two files under `deploy/` are the dashboard deployment artifacts.

```text
.
├── .dockerignore
├── .gitattributes
├── .gitignore
├── .python-version
├── .streamlit/
│   └── config.toml
├── api/
│   └── __init__.py
├── dashboard/
│   ├── __init__.py
│   ├── app.py
│   ├── README.md
│   ├── GOLD_DATA_AUDIT.md
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── components/
│   │   ├── __init__.py
│   │   ├── charts.py
│   │   ├── filters.py
│   │   ├── formatting.py
│   │   ├── layout.py
│   │   ├── navigation.py
│   │   ├── report.py
│   │   ├── tables.py
│   │   └── velocity.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── analytics.py
│   │   ├── postgres_provider.py
│   │   └── provider.py
│   ├── static/fonts/
│   │   ├── inter.ttf
│   │   ├── inter-OFL.txt
│   │   ├── plus-jakarta-sans.ttf
│   │   └── plus-jakarta-sans-OFL.txt
│   ├── styles/
│   │   └── theme.css
│   ├── tests/
│   │   ├── test_app.py
│   │   └── test_data.py
│   └── views/
│       ├── __init__.py
│       ├── overview.py
│       ├── sales.py
│       ├── categories.py
│       ├── geography.py
│       └── pipeline_health.py
├── dashboard_serve/
│   ├── README.md
│   ├── requirements.txt
│   ├── schema.sql
│   ├── export_gold.py
│   ├── load_gold.py
│   └── data/
│       ├── manifest.json
│       ├── dim_customer.csv
│       ├── dim_date.csv
│       ├── dim_product.csv
│       ├── dim_region.csv
│       ├── fct_sales_lines.csv
│       ├── mart_customer_retention.csv
│       ├── mart_discount_impact.csv
│       ├── mart_market_growth.csv
│       └── mart_segment_pnl.csv
├── data/
│   └── .gitkeep
├── deploy/
│   ├── .gitkeep
│   ├── DASHBOARD_HANDOFF.md
│   └── dashboard.Dockerfile
├── pipeline/
│   └── __init__.py
├── pyproject.toml
├── references/
│   └── layout.html
├── requirements-dev.txt
├── requirements.txt
├── scripts/
│   └── .gitkeep
├── sql/
│   ├── marts/.gitkeep
│   ├── raw/.gitkeep
│   └── staging/.gitkeep
└── tests/
    ├── __init__.py
    ├── api/__init__.py
    ├── dashboard/__init__.py
    └── pipeline/__init__.py
```
