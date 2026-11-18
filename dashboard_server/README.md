# Gold snapshot for dashboard development

This folder holds a copy of the pipeline's **gold** schema: every table the dashboard will read,
with all rows, as of **2026-11-17** (`data/manifest.json` gives the exact time). Use it to design
and build the dashboard now, without running Kafka, the API or dbt.

The live warehouse has the same table names, column names and types. If you build against
Postgres, switching to the live pipeline later only means changing the connection URL.

## Contents

| File | What it is |
|---|---|
| `schema.sql` | `CREATE TABLE` for every gold table, with column types and descriptions (as `COMMENT ON`) |
| `data/<table>.csv` | Every row of each table. UTF-8 CSV with a header; NULL is an empty field, an empty string is `""` |
| `data/manifest.json` | Row counts, checksums and column types per table, and when the snapshot was taken |
| `load_gold.py` | Recreates `gold` with all rows in a Postgres database you choose |
| `requirements.txt` | What `load_gold.py` needs (only `psycopg`) |
| `export_gold.py` | Used by the pipeline side to refresh this folder. You don't need it |

## Load it into Postgres (recommended)

```bash
# 1. Any Postgres 15+ works. With Docker:
docker run -d --name xom-gold -e POSTGRES_USER=xom -e POSTGRES_PASSWORD=xom \
  -p 5440:5432 postgres:17-alpine

# 2. Install the one dependency, then load (the database is created if missing)
pip install -r dashboard_serve/requirements.txt
python dashboard_serve/load_gold.py --url postgresql://xom:xom@localhost:5440/xom_gold

# Check that a database still matches the files
python dashboard_serve/load_gold.py --check --url postgresql://xom:xom@localhost:5440/xom_gold
```

The loader runs in one transaction. It replaces only the `gold` schema, verifies the CSV
checksums and row counts, and can be re-run at any time. It refuses any database that has
`bronze` or `silver` schemas, so it can't overwrite a real pipeline warehouse.

Then query the tables as `gold.<table>`, for example `SELECT * FROM gold.mart_segment_pnl`.

To use the CSVs without Postgres (for example `pandas.read_csv`), read the empty fields as
missing values. The column types are listed in `data/manifest.json`.

## Tables

| Table | Rows | One row per |
|---|---:|---|
| `dim_customer` | 17,416 | customer (`customer_key`), plus one "unknown" row |
| `dim_product` | 28,357 | product (`product_key`), plus one "unknown" row |
| `dim_region` | 3,829 | city-level region (`region_key`), plus one "unknown" row |
| `dim_date` | 2,513 | calendar day, 2020-01-01 to the export date |
| `fct_sales_lines` | 51,290 | sales line (`sales_line_key`) |
| `mart_discount_impact` | 960 | month x category x discount band x `is_sample` |
| `mart_segment_pnl` | 48 | quarter x segment x `is_sample` |
| `mart_market_growth` | 93 | year x market x region x `is_sample`, with year-on-year change |
| `mart_customer_retention` | 1,167 | first-order cohort month x months since first order x `is_sample` |

Joins: `fct_sales_lines.customer_key`, `product_key` and `region_key` join to the matching
dimension. `fct_sales_lines.order_date` joins to `dim_date.date_day`. The marts are already
aggregated and need no joins.

Every column with a description in the pipeline has it in `schema.sql`. In Postgres, `\d+ gold.<table>` shows them.

## Things to know about the data

- **Demo rows (`is_sample`).** Every table has an `is_sample` column. In this snapshot it's
  always `false`. Later, a demo generator will add orders dated "today" with
  `is_sample = true`. Each mart keeps them in separate rows, so you can show, badge or filter
  them. Please design for that now.
- **Date gap.** Real orders run from 2020-01-01 to 2023-12-31. Demo orders will be dated at the
  time they're generated, so trend charts will have an empty stretch from 2024 onward. Show it as
  a gap; don't interpolate. `dim_date` covers the gap with days that have no sales.
- **Unknown members.** 2 sales lines point to a product missing from the source, and 2 to a
  missing region. Each maps to that dimension's "unknown" row (`is_unknown = true`, attributes
  NULL), so totals still add up.
- **Amounts.** `sales` is before discount. `net_sales = sales x (1 - discount)`, and `profit` is
  after discount. Margins are `profit / net_sales`. Amounts are treated as USD (`currency`); the
  data owner hasn't confirmed that yet.
- **Values as they appear in the data:** segments are Consumer, Corporate and Self-Employed.
  Markets are Africa, Asia Pacific, Europe, LATAM and USCA. The categories are Body care,
  Face care, Hair care, Make up, and Home and Accessories. Discount bands are `none` (0), `low` (up to 0.20),
  `medium` (up to 0.40) and `high` (above 0.40). Some of these differ from `data_context.md`.
  The data is right.
- **Use `order_date`.** The date inside `order_id` is 8 years off; treat `order_id` as just an ID.
- **Missing stays missing.** For example, 124 customers have no `gender`. NULL means unknown; it
  doesn't mean zero or an empty string.
- The marts include medians next to averages, and `first_order_date` / `last_order_date` for the
  range each row covers.

## Not in this snapshot

- **`ops.pipeline_runs`.** In production the dashboard reads it to show when data was last
  refreshed, and flags the data as stale when the last successful transform is more than
  2 minutes old. A snapshot is never fresh, so it isn't included. How staleness should work
  during quiet periods is still being decided with you.
- Live updates. In production, gold is rebuilt about every 30 seconds while new orders arrive.

## The contract

These table and column names are the interface between the pipeline and the dashboard. **They
aren't final until you confirm them**, so this is the time to ask for changes: a column you
need, a different grain, a renamed field. After that, renaming or removing a column or changing
a grain is a breaking change agreed between both sides. New columns can be added at any time.
