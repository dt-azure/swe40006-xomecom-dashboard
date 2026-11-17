"""Read the dashboard's Gold contract in a consistent, read-only transaction."""
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, OperationalError, ProgrammingError, SQLAlchemyError

from .provider import DataSourceError, Snapshot

DIMENSIONS = ("dim_customer", "dim_date", "dim_product", "dim_region")
MARTS = ("mart_segment_pnl", "mart_customer_retention", "mart_discount_impact", "mart_market_growth")
FACT_QUERY = """
SELECT f.sales_line_key, f.source, f.order_id, f.order_date AS date,
       CASE WHEN c.is_unknown IS FALSE THEN c.customer_key END AS customer_key,
       CASE WHEN p.is_unknown IS FALSE THEN p.product_key END AS sku,
       COALESCE(p.product_name, 'Unknown') AS product,
       COALESCE(p.category, 'Unknown') AS category,
       COALESCE(p.subcategory, 'Unknown') AS subcategory,
       COALESCE(r.region, 'Unknown') AS region, COALESCE(r.market, 'Unknown') AS market,
       COALESCE(r.country, 'Unknown') AS country, COALESCE(r.state, 'Unknown') AS state,
       COALESCE(r.city, 'Unknown') AS city, COALESCE(f.segment, 'Unknown') AS segment,
       f.quantity, f.sales, f.net_sales, f.profit, f.discount_amount,
       f.discount::double precision AS discount, f.discount_band,
       f.currency, f.is_sample, f.ingested_at
FROM gold.fct_sales_lines f
LEFT JOIN gold.dim_customer c USING (customer_key)
LEFT JOIN gold.dim_product p USING (product_key)
LEFT JOIN gold.dim_region r USING (region_key)
"""
AMOUNTS = ("sales", "net_sales", "profit", "discount_amount")


def normalize_lines(lines: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    lines = lines.copy()
    if lines["sales_line_key"].isna().any() or not lines["sales_line_key"].is_unique:
        raise DataSourceError("Gold sales lines must have unique keys after joining dimensions.")
    keys = ["source", "order_id", "date", "is_sample", "currency"]
    if lines[keys].isna().any().any():
        raise DataSourceError("Gold sales lines are missing order keys, dates, sample flags or currency.")
    currencies = lines["currency"].unique()
    if len(currencies) > 1:
        raise DataSourceError("Gold contains multiple currencies. Supply a single reporting currency before aggregating.")
    currency = str(currencies[0]) if len(currencies) else "USD"
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
        raise DataSourceError("Gold sales lines must use a three-letter currency code.")
    for column in AMOUNTS:
        cents = lines.pop(column) * 100
        if cents.isna().any() or not cents.map(lambda amount: amount == int(amount)).all():
            raise DataSourceError("Gold sales amounts must be present and recorded to whole cents.")
        lines[f"{column}_cents"] = cents.astype("int64")
    lines["date"] = pd.to_datetime(lines["date"])
    lines["order_key"] = lines.groupby(["source", "is_sample", "order_id"], sort=False).ngroup()
    return lines, currency


@dataclass(frozen=True)
class PostgresProvider:
    database_url: str | None

    def load(self) -> Snapshot:
        if not self.database_url:
            raise DataSourceError("Set DASHBOARD_DATABASE_URL to the PostgreSQL database containing the Gold schema.")
        try:
            url = make_url(self.database_url)
        except (ArgumentError, ValueError):
            raise DataSourceError("DASHBOARD_DATABASE_URL is not a valid PostgreSQL URL.") from None
        if url.drivername not in {"postgresql", "postgresql+psycopg2"} or not url.database:
            raise DataSourceError("Use a postgresql:// URL that includes the database name.")

        engine = create_engine(
            url.set(drivername="postgresql+psycopg2"),
            isolation_level="REPEATABLE READ",
            connect_args={"connect_timeout": 5},
        )
        try:
            with engine.connect() as conn, conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = '20s'"))
                conn.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                lines, currency = normalize_lines(pd.read_sql(text(FACT_QUERY), conn, coerce_float=False))
                minimum, calendar_end = conn.execute(
                    text("SELECT MIN(date_day), MAX(date_day) FROM gold.dim_date")
                ).one()
                marts = {name: pd.read_sql(text(f"SELECT * FROM gold.{name}"), conn) for name in MARTS}
                counts = {
                    name: conn.execute(text(f"SELECT COUNT(*) FROM gold.{name}")).scalar_one()
                    for name in DIMENSIONS
                }
        except ProgrammingError:
            raise DataSourceError("Check that the Gold tables are loaded and the database role has SELECT access.") from None
        except OperationalError:
            raise DataSourceError("Could not read PostgreSQL. Check the connection URL, credentials, TLS and server availability.") from None
        except SQLAlchemyError:
            raise DataSourceError("The Gold query failed. Check that the database matches dashboard_serve/schema.sql.") from None
        finally:
            engine.dispose()
        if not lines.empty:
            minimum = min(filter(None, (minimum, lines["date"].min().date())))
            calendar_end = max(filter(None, (calendar_end, lines["date"].max().date())))
        if minimum is None or calendar_end is None:
            raise DataSourceError("Gold has no calendar dates. Load the Gold snapshot and try again.")
        counts["fct_sales_lines"] = len(lines)
        counts.update({name: len(frame) for name, frame in marts.items()})
        inventory = pd.DataFrame({"table": counts.keys(), "rows": counts.values()})
        return Snapshot(minimum, calendar_end, currency, lines, marts, inventory, datetime.now(timezone.utc))
