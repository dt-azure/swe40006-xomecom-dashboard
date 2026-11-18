from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from dashboard.components.tables import csv_text
from dashboard.data.analytics import (
    DateScope, breakdown, daily_sales, in_scope, mart_in_scope, period_trend,
    sample_scope, search_rows, totals,
)
from dashboard.data.postgres_provider import PostgresProvider, normalize_lines
from dashboard.data.provider import DataSourceError


def gold_line(key, order, day, amount, *, market="Europe", customer="u-1", sample=False):
    return {
        "sales_line_key": key, "source": "xom", "order_id": order, "date": day,
        "customer_key": customer, "sku": "sku-1", "product": "Face cream",
        "category": "Face care", "market": market,
        "quantity": 1, "sales": Decimal(amount), "net_sales": Decimal(amount),
        "profit": Decimal("1.25"), "discount_amount": Decimal("0"), "is_sample": sample,
        "currency": "USD",
    }


@pytest.fixture
def lines():
    raw = pd.DataFrame([
        gold_line("1", "o-1", "2023-12-30", "10.25"),
        gold_line("2", "o-1", "2023-12-30", "12.25", market="LATAM"),
        gold_line("3", "o-2", "2023-12-31", "7.25", customer=None),
        gold_line("4", "o-1", "2026-08-02", "50", sample=True),
    ])
    return normalize_lines(raw)[0]


def test_real_metrics_reconcile_at_the_sales_line_grain(lines):
    data = sample_scope(lines, "Historical only")
    current = totals(data)
    assert current["net_sales_cents"] == 2975
    assert current["orders"] == 2
    assert current["customers"] == 1
    assert current["aov_cents"] == 1487.5
    assert current["margin"] == pytest.approx(375 / 2975 * 100)

    geography = breakdown(data, ["market"])
    catalog = breakdown(data, ["category"])
    daily = daily_sales(data, DateScope(date(2023, 12, 30), date(2023, 12, 31)))
    assert geography["orders"].sum() == 3  # One order spans two markets.
    for view in (geography, catalog, daily):
        assert view["net_sales_cents"].sum() == current["net_sales_cents"]


def test_dates_sample_separation_and_discontinuous_trends(lines):
    scope = DateScope(date(2023, 12, 30), date(2026, 8, 2))
    assert len(in_scope(lines, scope)) == 4
    assert totals(sample_scope(lines, "Include sample rows"))["orders"] == 3
    assert totals(sample_scope(lines, "Sample only"))["net_sales_cents"] == 5000
    monthly = period_trend(lines, scope, "Monthly").set_index("date")
    assert pd.isna(monthly.loc["2024-01-01", "net_sales_cents"])
    assert pd.isna(monthly.loc["2024-01-01", "orders"])
    assert monthly.loc["2026-08-01", "net_sales_cents"] == 5000
    same_day = DateScope(date(2023, 12, 30), date(2023, 12, 30), "Previous period")
    assert same_day.prior(date(2020, 1, 1)).end == date(2023, 12, 29)
    empty = daily_sales(lines.iloc[:0], same_day)
    assert empty.empty and "orders" in empty


def test_mart_filters_keep_whole_coverage_intervals():
    frame = pd.DataFrame({
        "first_order_date": [date(2023, 1, 1), date(2023, 3, 1), date(2023, 2, 1)],
        "last_order_date": [date(2023, 1, 31), date(2023, 3, 31), date(2023, 4, 1)],
        "is_sample": [False, True, False],
    })
    scope = DateScope(date(2023, 1, 1), date(2023, 3, 31))
    assert mart_in_scope(frame, scope).index.tolist() == [0, 1]
    assert mart_in_scope(sample_scope(frame, "Historical only"), scope).index.tolist() == [0]


def test_search_and_currency_exports():
    frame = pd.DataFrame({"city": ["São Paulo", "=12+1"], "net_sales_cents": [1050, -500]})
    assert search_rows(frame, "sao paulo", ["city"]).index.tolist() == [0]
    assert search_rows(frame, "[", ["city"]).empty
    csv = csv_text(frame, "USD")
    assert "net_sales_usd" in csv
    assert "'=12+1,-5.0" in csv


@pytest.mark.parametrize("url, message", [
    (None, "DASHBOARD_DATABASE_URL"),
    ("bad url", "valid PostgreSQL URL"),
    ("sqlite:///tmp/db", "postgresql://"),
])
def test_configuration_errors(url, message):
    with pytest.raises(DataSourceError, match=message):
        PostgresProvider(url).load()


def test_invalid_mixed_currency_or_duplicate_keys_fail():
    first = gold_line("1", "o-1", "2023-12-30", "10.25")
    other_currency = gold_line("2", "o-2", "2023-12-30", "10.25") | {"currency": "EUR"}
    with pytest.raises(DataSourceError, match="multiple currencies"):
        normalize_lines(pd.DataFrame([first, other_currency]))
    with pytest.raises(DataSourceError, match="unique keys"):
        normalize_lines(pd.DataFrame([first, first]))


def test_velocity_counts_distinct_orders_and_splits_sales_by_selected_dates(lines):
    from dashboard.components.velocity import _share_bar
    from dashboard.data.analytics import weekday_sales_split, weekday_velocity

    extra = normalize_lines(pd.DataFrame([gold_line("5", "o-3", "2023-12-29", "20.25")]))[0]
    extra["order_key"] = 5
    data = pd.concat([lines, extra])
    scope = DateScope(date(2023, 12, 29), date(2023, 12, 31))
    scoped = in_scope(data, scope)
    weekdays = weekday_velocity(scoped)
    assert weekdays.index.tolist() == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert weekdays["orders"].tolist() == [0, 0, 0, 0, 1, 1, 1]
    assert weekdays["share"].sum() == pytest.approx(100)
    assert weekday_sales_split(scoped) == (2025, 2975)
    bar = _share_bar(*weekday_sales_split(scoped), "USD")
    assert "Mon–Fri: 40.5%" in bar and "Sat–Sun: 59.5%" in bar

    empty = scoped.iloc[:0]
    assert weekday_velocity(empty)["share"].isna().all()
    assert weekday_sales_split(empty) == (0, 0)
    assert "Share unavailable" in _share_bar(0, 0, "USD")
    assert "Share unavailable" in _share_bar(-500, 1500, "USD")


def test_sales_composition_matches_positive_sales_and_handles_signed_or_empty_values():
    from dashboard.components.charts import sales_composition

    labels = pd.Series(["Category A", "Category B", "Zero"])
    cents = pd.Series([1600, 2400, 0])
    for tree in (False, True):
        fig = sales_composition(labels, cents, "USD", treemap=tree)
        trace = fig.data[0]
        assert trace.type == ("treemap" if tree else "pie")
        assert trace.values == (16, 24)
        assert sum(trace.customdata) == pytest.approx(100)
        assert "%{value:,.2f}" in trace.hovertemplate
        assert sales_composition(labels, cents * 0, "USD", treemap=tree) is None
        assert sales_composition(labels, cents.where(cents.lt(0)), "USD", treemap=tree) is None
        assert sales_composition(labels, -cents, "USD", treemap=tree).data[0].type == "bar"


def test_discount_and_loss_order_metrics_use_the_correct_grain(lines):
    from dashboard.data.analytics import discount_performance, segment_performance, top_profitable_products

    data = lines.iloc[:3].assign(segment="Consumer", discount=[.1, .2, 0],
                                 discount_band=["low", "low", "none"], profit_cents=[-300, 400, -200])
    bands = discount_performance(data).set_index("discount_band")
    assert bands.loc["low", "avg_discount_pct"] == pytest.approx(15)
    assert bands.loc["low", "orders"] == 1
    segment = segment_performance(data).iloc[0]
    assert segment["loss_orders"] == 1
    assert segment["profit_cents"] == -100
    assert top_profitable_products(data).empty


def test_retention_and_cross_region_use_known_customer_and_distinct_keys():
    from dashboard.data.analytics import (
        cross_region_customers, customer_activity, observed_customer_value, retention_by_segment, rfm_segments,
    )

    data = normalize_lines(pd.DataFrame([
        gold_line("1", "o-1", "2023-12-30", "10"),
        gold_line("2", "o-1", "2023-12-30", "15", market="LATAM"),
        gold_line("3", "o-2", "2023-12-31", "20", customer=None),
        gold_line("4", "o-3", "2023-12-31", "25"),
    ]))[0].assign(segment="Consumer", region="West")
    activity = customer_activity(data)
    assert len(activity) == 1
    assert activity.loc["u-1", "orders"] == 2
    assert retention_by_segment(data).iloc[0]["repeat_rate_pct"] == 100
    assert rfm_segments(activity).iloc[0]["frequency"] == "Repeat"
    assert cross_region_customers(data) == 1  # Same named region in distinct markets.
    assert observed_customer_value(data, activity.index, pd.Timestamp("2023-12-30")) == 2500
    assert observed_customer_value(data, activity.index, pd.Timestamp("2023-12-31")) == 5000


def test_monthly_growth_uses_pre_window_history_and_does_not_bridge_missing_months():
    from dashboard.data.analytics import monthly_growth

    data = normalize_lines(pd.DataFrame([
        gold_line("1", "o-1", "2022-12-05", "10"),
        gold_line("2", "o-2", "2023-10-05", "20"),
        gold_line("3", "o-3", "2023-12-05", "30"),
        gold_line("4", "o-4", "2024-01-05", "40"),
    ]))[0]
    result = monthly_growth(data, DateScope(date(2023, 12, 1), date(2024, 1, 30)))
    assert result["date"].dt.strftime("%Y-%m").tolist() == ["2023-12"]
    assert result["yoy_growth_pct"].iloc[0] == pytest.approx(200)
    assert pd.isna(result["growth"].iloc[0])
