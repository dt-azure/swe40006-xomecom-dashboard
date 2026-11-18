from datetime import date

import pandas as pd
import pytest

from dashboard.data.analytics import (
    DateScope, catalog_breakdown, conversion_rate, currency_columns, daily_sales, daypart_velocity,
    geography_breakdown, in_scope, on_time_rate, order_metrics, pipeline_metrics, purchased_lines,
    search_rows, shipments,
)
from dashboard.data.mock_generator import generate_snapshot
from dashboard.data.mock_provider import MockProvider
from dashboard.data.postgres_provider import PostgresProvider
from dashboard.data.provider import ARCHITECTURE, DataSourceError, select_provider


@pytest.fixture(scope="module")
def snapshot():
    return generate_snapshot()


def test_demo_is_deterministic(snapshot):
    again = generate_snapshot()
    for name in ("orders", "items", "traffic", "product_traffic", "runs", "stages"):
        pd.testing.assert_frame_equal(getattr(snapshot, name), getattr(again, name))
    assert snapshot.orders["order_id"].is_unique
    assert snapshot.items["item_id"].is_unique


def test_revenue_and_orders_reconcile_across_pages(snapshot):
    scope = DateScope(date(2024, 6, 1), date(2024, 8, 15))
    orders = in_scope(snapshot.orders, scope)
    overview = order_metrics(orders)
    days = daily_sales(orders, scope)
    catalog = catalog_breakdown(purchased_lines(snapshot, orders))
    regions = geography_breakdown(orders, ["region", "state", "city"])

    assert overview["revenue"] == days["revenue_cents"].sum() == catalog["revenue_cents"].sum()
    assert overview["revenue"] == regions["revenue_cents"].sum()
    assert overview["orders"] == days["orders"].sum() == regions["orders"].sum()
    assert overview["aov"] == pytest.approx(overview["revenue"] / overview["orders"])
    assert catalog["share"].sum() == pytest.approx(100)
    assert (orders["revenue_cents"] + orders["shipping_cents"]).equals(orders["payment_cents"])
    assert currency_columns(days)["revenue_brl"].sum() == pytest.approx(overview["revenue"] / 100)


def test_inclusive_dates_comparisons_and_literal_search(snapshot):
    day = date(2024, 8, 15)
    scope = DateScope(day, day, "Previous period")
    selection = in_scope(snapshot.orders, scope)
    assert not selection.empty
    assert selection["ordered_at"].dt.date.eq(day).all()
    assert in_scope(snapshot.runs, scope, "started_at")["started_at"].dt.date.eq(day).all()
    assert scope.prior(snapshot.min_date).end == date(2024, 8, 14)
    assert DateScope(date(2024, 2, 29), date(2024, 3, 2)).prior(snapshot.min_date).start == date(2023, 2, 28)
    assert DateScope(snapshot.min_date, snapshot.min_date).prior(snapshot.min_date) is None
    assert search_rows(selection, "sao paulo", ["city"])["city"].eq("São Paulo").all()
    assert search_rows(selection, "[", ["city"]).empty

    matrix = daypart_velocity(selection, scope)
    assert matrix.loc["Thu"].sum() == order_metrics(selection)["orders"]
    assert matrix.drop(index="Thu").isna().all().all()


def test_delivery_chronology_and_kpis(snapshot):
    deliveries = shipments(snapshot.orders)
    actual = deliveries["delivered_at"]
    assert actual.gt(deliveries["dispatched_at"]).all()
    assert deliveries["dispatched_at"].gt(deliveries["ordered_at"]).all()
    reviewed = deliveries.loc[deliveries["reviewed_at"].notna()]
    assert reviewed["reviewed_at"].gt(reviewed["delivered_at"]).all()
    assert reviewed["review_score"].between(1, 5).all()
    assert reviewed["reviewed_at"].dt.date.le(snapshot.as_of).all()
    assert deliveries["variance_hours"].gt(0).equals(deliveries["sla_status"].eq("Delayed"))
    assert on_time_rate(deliveries) == pytest.approx(
        100 * (1 - deliveries["sla_status"].eq("Delayed").mean())
    )
    assert snapshot.traffic["conversions"].sum() == len(snapshot.orders)
    assert 0 < conversion_rate(snapshot.traffic) < 100


def test_pipeline_run_status_and_stages(snapshot):
    runs = snapshot.runs.set_index("run_id")
    stats = pipeline_metrics(snapshot.runs, snapshot.as_of)
    assert stats["success_rate"] == pytest.approx(100 * runs["status"].eq("Success").mean())
    assert stats["exceptions"] == runs["status"].isin(["Warning", "Failed"]).sum()
    assert stats["rows_last_day"] == runs.loc[runs["started_at"].dt.date.eq(snapshot.as_of), "rows"].sum()
    assert set(runs["status"]) == {"Success", "Warning", "Failed"}
    assert snapshot.stages.groupby("run_id").size().eq(len(ARCHITECTURE)).all()
    assert snapshot.stages.groupby("run_id")["duration_seconds"].sum().equals(runs["duration_seconds"].sort_index())
    for run_id, stages in snapshot.stages.groupby("run_id", sort=False):
        status = list(stages["status"])
        expected = "Failed" if "Failed" in status else "Warning" if "Warning" in status else "Success"
        assert runs.at[run_id, "status"] == expected
        if expected == "Failed":
            assert set(status[status.index("Failed") + 1:]) <= {"Skipped"}


def test_empty_metrics_are_defined(snapshot):
    scope = DateScope(date(2022, 1, 1), date(2022, 1, 2))
    orders = in_scope(snapshot.orders, scope)
    assert orders.empty
    metrics = order_metrics(orders)
    assert metrics["revenue"] == 0 and metrics["orders"] == 0 and pd.isna(metrics["aov"])
    assert catalog_breakdown(purchased_lines(snapshot, orders)).empty
    assert geography_breakdown(orders, ["state"]).empty
    assert pd.isna(on_time_rate(shipments(orders)))
    empty_stats = pipeline_metrics(in_scope(snapshot.runs, scope, "started_at"), scope.end)
    assert pd.isna(empty_stats["success_rate"]) and empty_stats["exceptions"] == 0


def test_provider_selection_and_configuration(monkeypatch):
    monkeypatch.delenv("DASHBOARD_DATA_SOURCE", raising=False)
    assert isinstance(select_provider(), MockProvider)
    monkeypatch.setenv("DASHBOARD_DATA_SOURCE", "postgres")
    monkeypatch.delenv("DASHBOARD_DATABASE_URL", raising=False)
    provider = select_provider()
    assert isinstance(provider, PostgresProvider)
    with pytest.raises(DataSourceError, match="DASHBOARD_DATABASE_URL"):
        provider.load()
    with pytest.raises(DataSourceError, match="mart mappings"):
        PostgresProvider("postgresql+psycopg2://localhost/example").load()
    with pytest.raises(DataSourceError, match="valid SQLAlchemy URL"):
        PostgresProvider("invalid-url").load()
    with pytest.raises(DataSourceError, match="mock or postgres"):
        select_provider("unavailable")
