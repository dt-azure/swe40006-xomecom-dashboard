"""Streamlit entry point for CommercePulse."""

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.components.filters import comparison_control, date_controls, preserve_widget
from dashboard.components.layout import load_theme
from dashboard.components.navigation import brand, sidebar
from dashboard.components.report import Report, active_report
from dashboard.data.analytics import DateScope, sample_scope
from dashboard.data.postgres_provider import PostgresProvider
from dashboard.data.provider import DataSourceError, Snapshot

# Streamlit adds this script's directory to sys.path. Also expose the package root.
ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VIEWS = (
    ("overview", "Overview", "dashboard"),
    ("sales", "Sales Trend", "trending_up"),
    ("categories", "Categories", "folder_open"),
    ("geography", "Geography", "public"),
    ("pipeline_health", "Pipeline Health", "monitor_heart"),
)


@st.cache_data(ttl=30, max_entries=2, show_spinner="Reading PostgreSQL Gold…")
def gold_snapshot(database_url: str | None) -> Snapshot:
    return PostgresProvider(database_url).load()


def main() -> None:
    st.set_page_config(
        page_title="CommercePulse", page_icon=":material/monitoring:", layout="wide", initial_sidebar_state="auto"
    )
    load_theme()
    pages = [
        st.Page(
            f"views/{filename}.py",
            title=title,
            icon=f":material/{symbol}:",
            default=filename == "overview",
            url_path=title.lower().replace(" & ", "-").replace(" ", "-"),
        )
        for filename, title, symbol in VIEWS
    ]
    selected = st.navigation(pages, position="hidden")
    selection = sidebar(pages, selected)
    for key in ("catalog_category", "geo_market", "geo_country"):
        preserve_widget(key)

    try:
        snapshot = gold_snapshot(os.getenv("DASHBOARD_DATABASE_URL"))
    except DataSourceError as error:
        with st.container(key="cp_toolbar"):
            brand()
        st.error(str(error))
        return

    with st.container(key="cp_toolbar"):
        logo, calendar, compare, freshness, export = st.columns(
            [1.35, 1.55, 1.15, 1.1, 1.1], gap="small", vertical_alignment="center"
        )
        with logo:
            brand()
        with calendar:
            dates = date_controls(snapshot, selection)
        with compare:
            comparison = comparison_control()
        with freshness:
            latest = sample_scope(snapshot.lines, selection)["date"].max()
            coverage = f"Orders through {latest:%b %d, %Y}" if pd.notna(latest) else "No orders in source selection"
            st.html(f'<div class="cp-freshness">{coverage}</div>')
        export_slot = export.empty()

    if dates is None:
        st.info("Choose an end date to apply the date range.")
        return
    scope = DateScope(*dates, comparison)
    report = Report(snapshot, scope, scope.prior(snapshot.min_date), selection)
    token = active_report.set((report, export_slot))
    try:
        selected.run()
    finally:
        active_report.reset(token)


if __name__ == "__main__":
    main()
