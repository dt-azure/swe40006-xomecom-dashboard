"""Filters and metric definitions shared across reports."""
from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .provider import Snapshot

PERIODS = {"Daily": "D", "Weekly": "W-MON", "Monthly": "MS", "Quarterly": "QS"}
DAYPARTS = ["Morning", "Midday", "Evening", "Night"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SLA_STATUSES = ["Early", "On time", "Delayed"]


@dataclass(frozen=True)
class DateScope:
    start: date
    end: date
    comparison: str = "Previous year"

    def prior(self, minimum: date) -> "DateScope | None":
        if self.comparison == "Previous year":
            start = (pd.Timestamp(self.start) - pd.DateOffset(years=1)).date()
            end = (pd.Timestamp(self.end) - pd.DateOffset(years=1)).date()
        elif self.comparison == "Previous period":
            duration = self.end - self.start + timedelta(days=1)
            start, end = self.start - duration, self.end - duration
        else:
            return None
        return replace(self, start=start, end=end) if start >= minimum else None


def in_scope(frame: pd.DataFrame, scope: DateScope, column: str = "date") -> pd.DataFrame:
    start = pd.Timestamp(scope.start)
    stop = pd.Timestamp(scope.end + timedelta(days=1))
    return frame.loc[frame[column].ge(start) & frame[column].lt(stop)]


def search_rows(frame: pd.DataFrame, query: str, columns: list[str]) -> pd.DataFrame:
    """Case-insensitive literal search supports accents and common report IDs."""
    import unicodedata

    def normalize(value: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        )

    query = normalize(query.strip())
    if not query:
        return frame
    match = pd.Series(False, index=frame.index)
    for name in columns:
        match |= frame[name].astype(str).map(normalize).str.contains(query, regex=False)
    return frame.loc[match]


def paid_orders(orders: pd.DataFrame) -> pd.DataFrame:
    return orders.loc[orders["status"].ne("Cancelled")]


def purchased_lines(snapshot: Snapshot, orders: pd.DataFrame) -> pd.DataFrame:
    return snapshot.items.merge(paid_orders(orders)[["order_id", "date"]], on="order_id", validate="many_to_one")


def divide(numerator, denominator):
    """Return an undefined value for a missing denominator."""
    if isinstance(denominator, pd.Series):
        return numerator / denominator.where(denominator.ne(0))
    return numerator / denominator if denominator else np.nan


def order_metrics(orders: pd.DataFrame) -> dict:
    paid = paid_orders(orders)
    revenue = paid["revenue_cents"].sum()
    return {
        "revenue": revenue,
        "orders": len(paid),
        "customers": paid["customer_id"].nunique(),
        "aov": divide(revenue, len(paid)),
    }


def percent_change(current, previous) -> float:
    return 100 * (divide(current, previous) - 1)


def conversion_rate(data: pd.DataFrame) -> float:
    return 100 * divide(data["conversions"].sum(), data["sessions"].sum())


def traffic_metrics(data: pd.DataFrame, dimension: str) -> pd.DataFrame:
    totals = data.groupby(dimension, as_index=False)[["conversions", "sessions"]].sum()
    totals["conversion"] = 100 * divide(totals["conversions"], totals["sessions"])
    return totals


def period_trend(
    orders: pd.DataFrame, scope: DateScope, granularity: str, traffic: pd.DataFrame | None = None,
) -> pd.DataFrame:
    paid = paid_orders(orders)
    index = pd.date_range(scope.start, scope.end, freq="D")
    trend = paid.groupby("date").agg(revenue_cents=("revenue_cents", "sum"), orders=("order_id", "size"))
    trend = trend.reindex(index, fill_value=0)
    if traffic is not None:
        trend = trend.join(traffic.groupby("date")[["conversions", "sessions"]].sum()).fillna(0)
    trend = trend.resample(PERIODS[granularity], label="left", closed="left").sum()
    if traffic is not None:
        trend["conversion"] = 100 * divide(trend["conversions"], trend["sessions"])
    return trend.rename_axis("date").reset_index()


def daily_sales(orders: pd.DataFrame, scope: DateScope) -> pd.DataFrame:
    daily = period_trend(orders, scope, "Daily").set_index("date")
    daily["cancelled"] = orders.loc[orders["status"].eq("Cancelled")].groupby("date").size()
    daily["cancelled"] = daily["cancelled"].fillna(0).astype(int)
    delivered = orders.loc[orders["status"].eq("Delivered")].groupby("date").size()
    daily["fulfilment"] = 100 * divide(delivered.reindex(daily.index, fill_value=0), daily["orders"])
    daily["aov_cents"] = divide(daily["revenue_cents"], daily["orders"])
    median = daily.loc[daily["orders"].gt(0), "orders"].median()
    daily["velocity"] = np.select(
        [daily["orders"].eq(0), daily["orders"].gt(1.25 * median), daily["orders"].lt(.75 * median)],
        ["No sales", "Surging", "Quiet"],
        default="Normal",
    )
    return daily.sort_index(ascending=False).reset_index()


def daypart_velocity(orders: pd.DataFrame, scope: DateScope) -> pd.DataFrame:
    paid = paid_orders(orders)
    hours = paid["ordered_at"].dt.hour
    dayparts = np.select(
        [hours.between(6, 10), hours.between(11, 15), hours.between(16, 20)],
        DAYPARTS[:3], default="Night"
    )
    count = pd.crosstab(paid["date"].dt.dayofweek, dayparts).reindex(
        index=range(7), columns=DAYPARTS, fill_value=0
    )
    dates = pd.date_range(scope.start, scope.end)
    days_per_weekday = pd.Series(dates.dayofweek).value_counts().reindex(range(7), fill_value=0)
    return count.div(days_per_weekday.replace(0, np.nan), axis=0).set_axis(WEEKDAYS)


def catalog_breakdown(lines: pd.DataFrame) -> pd.DataFrame:
    result = lines.groupby(["department", "category"], as_index=False).agg(
        revenue_cents=("revenue_cents", "sum"), orders=("order_id", "nunique"),
        units=("quantity", "sum"), active_skus=("sku", "nunique"),
    )
    result["share"] = 100 * divide(result["revenue_cents"], result["revenue_cents"].sum())
    result["basket_depth"] = divide(result["units"], result["orders"])
    return result.sort_values("revenue_cents", ascending=False)


def shipments(orders: pd.DataFrame) -> pd.DataFrame:
    result = orders.loc[orders["delivered_at"].notna()].copy()
    hours = result["delivered_at"] - result["estimated_at"]
    result["variance_hours"] = hours.dt.total_seconds() / 3600
    result["transit_days"] = (result["delivered_at"] - result["dispatched_at"]).dt.total_seconds() / 86400
    result["sla_status"] = np.select(
        [result["variance_hours"].gt(0), result["variance_hours"].lt(-12)],
        ["Delayed", "Early"], default="On time"
    )
    return result


def on_time_rate(deliveries: pd.DataFrame) -> float:
    return 100 * divide(deliveries["variance_hours"].le(0).sum(), len(deliveries))


def geography_breakdown(orders: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    paid = paid_orders(orders).copy()
    paid["delivery_late"] = (paid["delivered_at"] > paid["estimated_at"]).astype(float)
    paid.loc[paid["delivered_at"].isna(), "delivery_late"] = np.nan
    result = paid.groupby(by, as_index=False).agg(
        customers=("customer_id", "nunique"), orders=("order_id", "size"),
        revenue_cents=("revenue_cents", "sum"), ship_cost_cents=("shipping_cents", "mean"),
        late_rate=("delivery_late", "mean"),
    )
    result["share"] = 100 * divide(result["revenue_cents"], result["revenue_cents"].sum())
    result["aov_cents"] = divide(result["revenue_cents"], result["orders"])
    result["on_time_rate"] = 100 * (1 - result.pop("late_rate"))
    return result.sort_values("revenue_cents", ascending=False)


def pipeline_metrics(runs: pd.DataFrame, end: date) -> dict:
    last_day = runs.loc[runs["started_at"].dt.date.eq(end)]
    return {
        "success_rate": 100 * divide(runs["status"].eq("Success").sum(), len(runs)),
        "rows_last_day": last_day["rows"].sum(),
        "run_count_last_day": len(last_day),
        "average_duration": runs["duration_seconds"].mean(),
        "p95_duration": runs["duration_seconds"].quantile(.95),
        "exceptions": runs["status"].ne("Success").sum(),
    }


def currency_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Export currency in BRL while retaining exact cents during aggregation."""
    money = [column for column in frame if column.endswith("_cents")]
    result = frame.copy()
    result[money] = result[money].div(100).round(2)
    return result.rename(columns={column: column.removesuffix("_cents") + "_brl" for column in money})
