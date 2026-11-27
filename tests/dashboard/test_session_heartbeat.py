from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import UUID

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.components import session_heartbeat
from dashboard.components.session_registry import SessionRegistry
from dashboard.data.postgres_provider import PostgresProvider, normalize_lines
from dashboard.data.provider import Snapshot
from tests.dashboard.test_app import VIEWS
from tests.dashboard.test_data import gold_line


def report_snapshot() -> Snapshot:
    lines, currency = normalize_lines(
        pd.DataFrame(
            [
                gold_line("1", "o-1", "2023-12-30", "10", market="Europe"),
                gold_line("2", "o-2", "2023-12-31", "20", market="LATAM"),
            ]
        ).assign(
            subcategory="Cream",
            region=["Western Europe", "South America"],
            country=["France", "Brazil"],
            state=["Île-de-France", "São Paulo"],
            city=["Paris", "São Paulo"],
            segment=["Consumer", "Corporate"],
            discount=0.0,
            discount_band="none",
            ingested_at=pd.Timestamp("2024-01-01", tz="UTC"),
        )
    )
    empty_mart = pd.DataFrame(
        columns=(
            "is_sample first_order_date last_order_date order_quarter segment order_count customer_count "
            "gross_sales net_sales discount_amount profit profit_margin median_order_value loss_order_count "
            "cohort_month months_since_first_order cohort_customers active_customers retention_rate "
            "order_month category discount_band avg_discount loss_line_share order_year market region "
            "prev_year_net_sales net_sales_yoy_change"
        ).split()
    )
    return Snapshot(
        min_date=date(2023, 12, 30),
        calendar_end=date(2023, 12, 31),
        currency=currency,
        lines=lines,
        marts={
            name: empty_mart
            for name in ("mart_segment_pnl", "mart_customer_retention", "mart_discount_impact", "mart_market_growth")
        },
        table_counts=pd.DataFrame({"table": ["fct_sales_lines"], "rows": [2]}),
        read_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def fake_gold(monkeypatch):
    snapshot = report_snapshot()
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "postgresql://heartbeat-test/dashboard")
    monkeypatch.setattr(PostgresProvider, "load", lambda self: snapshot)
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def test_shared_shell_tracks_one_session_across_reports_and_filter_changes(dashboard_app_path, fake_gold, monkeypatch):
    registry = SessionRegistry()
    monkeypatch.setattr(session_heartbeat, "_registry", lambda: registry)
    app = AppTest.from_file(dashboard_app_path).run()
    session_id = app.session_state[session_heartbeat.SESSION_ID_KEY]
    assert UUID(session_id).version == 4
    assert session_heartbeat.get_session_metrics() == session_heartbeat.SessionMetrics(1, True, 30, 90)
    cards = [item.proto.body for item in app.get("html") if 'class="cp-kpis"' in item.proto.body]
    assert "Net sales" in cards[0] and 'class="cp-kpi-value">$30</div>' in cards[0]

    for name, title, charts in VIEWS:
        if name != "overview":
            app.switch_page(f"views/{name}.py").run()
        assert not app.exception and not app.error
        assert app.title[0].value == title
        # The short test history has no retention heatmap.
        assert len(app.get("plotly_chart")) == charts - (name == "overview")
        assert app.get("download_button")
        assert app.session_state[session_heartbeat.SESSION_ID_KEY] == session_id

    app.switch_page("views/categories.py").run()
    app.selectbox(key="catalog_category").select("Face care").run()
    assert not app.exception
    assert app.session_state[session_heartbeat.SESSION_ID_KEY] == session_id
    assert registry.active_count() == 1

    second_tab = AppTest.from_file(dashboard_app_path).run()
    assert second_tab.session_state[session_heartbeat.SESSION_ID_KEY] != session_id
    assert registry.active_count() == 2


def test_registry_failure_and_replacement_leave_dashboard_usable(dashboard_app_path, fake_gold, monkeypatch):
    cached_registry = session_heartbeat._registry

    def unavailable():
        raise RuntimeError("registry unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(session_heartbeat, "_registry", unavailable)
        app = AppTest.from_file(dashboard_app_path).run()
        assert not app.exception and not app.error
        assert app.title[0].value == "Executive Overview"
        assert session_heartbeat.get_session_metrics() == session_heartbeat.SessionMetrics(None, False)
    session_id = app.session_state[session_heartbeat.SESSION_ID_KEY]

    cached_registry.clear()
    try:
        app.run()
        assert session_heartbeat.get_session_metrics().active_count == 1
        cached_registry.clear()  # Simulate the loss of process-local state.
        assert session_heartbeat.get_session_metrics().active_count == 0
        app.run()
        assert session_heartbeat.get_session_metrics().active_count == 1
        assert app.session_state[session_heartbeat.SESSION_ID_KEY] == session_id
        assert not app.exception and not app.error
    finally:
        cached_registry.clear()


def test_heartbeat_work_is_independent_of_the_gold_provider(monkeypatch):
    now = 0
    registry = SessionRegistry(lambda: now)
    monkeypatch.setattr(session_heartbeat, "_registry", lambda: registry)
    load = Mock(side_effect=AssertionError("Heartbeat must never load Gold"))
    monkeypatch.setattr(PostgresProvider, "load", load)
    app = AppTest.from_string(
        "from dashboard.components.session_heartbeat import refresh_session_heartbeat\nrefresh_session_heartbeat()"
    ).run()
    session_id = app.session_state[session_heartbeat.SESSION_ID_KEY]
    for tick in (30, 60, 90, 120):
        now = tick
        app.run()
        assert not app.exception
        assert app.session_state[session_heartbeat.SESSION_ID_KEY] == session_id
    now = 209
    assert registry.active_count() == 1
    now = 210
    assert registry.active_count() == 0
    load.assert_not_called()
