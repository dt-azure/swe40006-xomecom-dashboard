"""Metrics at the Gold sales-line grain and filters for the pre-aggregated marts."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
import unicodedata

import numpy as np
import pandas as pd

PERIODS = {"Daily": "D", "Weekly": "W-MON", "Monthly": "MS", "Quarterly": "QS"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DATA_SCOPES = ("Historical only", "Include sample rows", "Sample only")


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
    start, end = pd.Timestamp(scope.start), pd.Timestamp(scope.end + timedelta(days=1))
    return frame.loc[frame[column].ge(start) & frame[column].lt(end)]


def sample_scope(frame: pd.DataFrame, selection: str) -> pd.DataFrame:
    if selection == "Include sample rows":
        return frame
    return frame.loc[frame["is_sample"].eq(selection == "Sample only")]


def mart_in_scope(frame: pd.DataFrame, scope: DateScope) -> pd.DataFrame:
    """Select rows whose reported order-date coverage is fully within the filter."""
    start, end = pd.Timestamp(scope.start), pd.Timestamp(scope.end)
    first, last = pd.to_datetime(frame["first_order_date"]), pd.to_datetime(frame["last_order_date"])
    return frame.loc[first.ge(start) & last.le(end)]


def search_rows(frame: pd.DataFrame, query: str, columns: list[str]) -> pd.DataFrame:
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


def divide(numerator, denominator):
    if isinstance(denominator, pd.Series):
        return numerator / denominator.where(denominator.ne(0))
    return numerator / denominator if denominator else np.nan


def percent_change(current, previous):
    return 100 * (divide(current, previous) - 1)


def totals(lines: pd.DataFrame) -> dict:
    orders = lines["order_key"].nunique()
    net_sales = lines["net_sales_cents"].sum()
    profit = lines["profit_cents"].sum()
    return {
        "sales_cents": lines["sales_cents"].sum(),
        "net_sales_cents": net_sales,
        "profit_cents": profit,
        "orders": orders,
        "customers": lines["customer_key"].nunique(),
        "aov_cents": divide(net_sales, orders),
        "margin": 100 * divide(profit, net_sales),
    }


def breakdown(lines: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    result = lines.groupby(by, as_index=False, dropna=False).agg(
        sales_cents=("sales_cents", "sum"), net_sales_cents=("net_sales_cents", "sum"),
        profit_cents=("profit_cents", "sum"), discount_amount_cents=("discount_amount_cents", "sum"),
        orders=("order_key", "nunique"), customers=("customer_key", "nunique"),
        units=("quantity", "sum"), active_skus=("sku", "nunique"),
    )
    result["share"] = 100 * divide(result["net_sales_cents"], result["net_sales_cents"].sum())
    result["basket_depth"] = divide(result["units"], result["orders"])
    result["aov_cents"] = divide(result["net_sales_cents"], result["orders"])
    result["margin"] = 100 * divide(result["profit_cents"], result["net_sales_cents"])
    return result.sort_values("net_sales_cents", ascending=False)


def period_trend(lines: pd.DataFrame, scope: DateScope, granularity: str) -> pd.DataFrame:
    freq = PERIODS[granularity]
    amounts = ["sales_cents", "net_sales_cents", "profit_cents", "discount_amount_cents", "quantity"]
    periods = lines.groupby(pd.Grouper(key="date", freq=freq, label="left", closed="left"))
    trend = periods[amounts].sum(min_count=1)
    trend["orders"] = periods["order_key"].nunique().where(trend["net_sales_cents"].notna())
    # Resampling supplies the enclosing bucket on both sides of partial periods.
    days = pd.date_range(scope.start, scope.end, freq="D")
    buckets = pd.Series(0, index=days).resample(freq, label="left", closed="left").size().index
    trend = trend.reindex(buckets).rename_axis("date")
    trend["aov_cents"] = divide(trend["net_sales_cents"], trend["orders"])
    trend["margin"] = 100 * divide(trend["profit_cents"], trend["net_sales_cents"])
    return trend.reset_index()


def daily_sales(lines: pd.DataFrame, scope: DateScope) -> pd.DataFrame:
    daily = period_trend(lines, scope, "Daily").dropna(subset=["orders"]).copy()
    median = daily["orders"].median()
    daily["velocity"] = np.select(
        [daily["orders"].gt(1.25 * median), daily["orders"].lt(.75 * median)],
        ["Surging", "Quiet"], default="Normal",
    )
    return daily.sort_values("date", ascending=False)


def weekday_velocity(lines: pd.DataFrame) -> pd.DataFrame:
    """Attribute distinct orders to their earliest order date in the selected lines."""
    orders = lines.groupby("order_key")["date"].min()
    counts = orders.dt.dayofweek.value_counts().reindex(range(7), fill_value=0)
    return pd.DataFrame({"orders": counts, "share": 100 * divide(counts, len(orders))}).set_axis(WEEKDAYS)


def weekday_sales_split(lines: pd.DataFrame) -> tuple[int, int]:
    weekend = lines["date"].dt.dayofweek.ge(5)
    return int(lines.loc[~weekend, "net_sales_cents"].sum()), int(lines.loc[weekend, "net_sales_cents"].sum())


def currency_columns(frame: pd.DataFrame, currency: str = "USD") -> pd.DataFrame:
    money = [column for column in frame if column.endswith("_cents")]
    result = frame.copy()
    result[money] = result[money].div(100).round(2)
    return result.rename(columns={column: column.removesuffix("_cents") + f"_{currency.lower()}" for column in money})


def discount_performance(lines: pd.DataFrame) -> pd.DataFrame:
    """Observed discount behavior by category and Gold discount band."""
    result = breakdown(lines, ["category", "discount_band"])
    mean_discount = lines.groupby(["category", "discount_band"], as_index=False)["discount"].mean()
    mean_discount["avg_discount_pct"] = mean_discount.pop("discount") * 100
    return result.merge(mean_discount, on=["category", "discount_band"], validate="one_to_one")


def top_profitable_products(lines: pd.DataFrame) -> pd.DataFrame:
    products = breakdown(lines.dropna(subset=["sku"]), ["category", "sku", "product"])
    ranked = products.loc[products["profit_cents"].gt(0)].sort_values(
        ["category", "profit_cents", "sku"], ascending=[True, False, True],
    )
    return ranked.groupby("category", sort=False).head(3)


def segment_performance(lines: pd.DataFrame) -> pd.DataFrame:
    result = breakdown(lines, ["segment"])
    result["gross_share_pct"] = 100 * divide(result["sales_cents"], result["sales_cents"].sum())
    order_profit = lines.groupby(["segment", "order_key"])["profit_cents"].sum()
    losses = order_profit.lt(0).groupby(level="segment").sum()
    result["loss_orders"] = result["segment"].map(losses)
    return result


def customer_activity(lines: pd.DataFrame) -> pd.DataFrame:
    known = lines.dropna(subset=["customer_key"])
    result = known.groupby("customer_key").agg(
        last_order=("date", "max"), orders=("order_key", "nunique"),
        net_sales_cents=("net_sales_cents", "sum"),
    )
    result["recency_days"] = (lines["date"].max() - result["last_order"]).dt.days
    return result


def observed_customer_value(history: pd.DataFrame, customers: pd.Index, through: pd.Timestamp) -> float:
    """Mean recorded net sales through the observation date for the selected customers."""
    selected = history["customer_key"].isin(customers) & history["date"].le(through)
    return divide(history.loc[selected, "net_sales_cents"].sum(), len(customers))


def retention_by_segment(lines: pd.DataFrame) -> pd.DataFrame:
    known = lines.dropna(subset=["customer_key"])
    orders = known.groupby(["segment", "customer_key"])["order_key"].nunique()
    rates = orders.gt(1).groupby(level="segment").agg(customers="size", repeat_customers="sum").reset_index()
    rates["repeat_rate_pct"] = 100 * divide(rates["repeat_customers"], rates["customers"])
    return rates


def rfm_segments(activity: pd.DataFrame) -> pd.DataFrame:
    classified = activity.assign(
        recency=pd.cut(activity["recency_days"], [-1, 90, 180, np.inf],
                       labels=["0–90 days", "91–180 days", "181+ days"]),
        frequency=np.where(activity["orders"].ge(2), "Repeat", "One order"),
        value=np.where(activity["net_sales_cents"].ge(activity["net_sales_cents"].quantile(.75)),
                       "Upper quartile", "Below upper quartile"),
    )
    return classified.groupby(["recency", "frequency", "value"], observed=True, as_index=False).agg(
        customers=("orders", "size"), net_sales_cents=("net_sales_cents", "sum"),
    )


def cross_region_customers(lines: pd.DataFrame) -> int:
    known = lines.loc[lines["market"].ne("Unknown") & lines["region"].ne("Unknown")]
    locations = known[["customer_key", "market", "region"]].drop_duplicates()
    return int(locations.groupby("customer_key").size().gt(1).sum())


def monthly_growth(lines: pd.DataFrame, scope: DateScope) -> pd.DataFrame:
    start = pd.Timestamp(scope.start).replace(day=1)
    history = replace(scope, start=(start - pd.DateOffset(years=1)).date())
    monthly = period_trend(in_scope(lines, history), history, "Monthly")
    monthly["prior_net_sales_cents"] = monthly["net_sales_cents"].shift()
    monthly["growth"] = percent_change(monthly["net_sales_cents"], monthly["prior_net_sales_cents"])
    monthly["yoy_growth_pct"] = percent_change(monthly["net_sales_cents"], monthly["net_sales_cents"].shift(12))
    ends = monthly["date"] + pd.offsets.MonthEnd()
    complete = monthly["date"].ge(pd.Timestamp(scope.start)) & ends.le(pd.Timestamp(scope.end))
    return monthly.loc[complete].dropna(subset=["net_sales_cents"])
