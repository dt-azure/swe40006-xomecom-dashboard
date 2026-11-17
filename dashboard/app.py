"""Streamlit entry point for CommercePulse."""
import os
import sys
from pathlib import Path

import streamlit as st

# Streamlit adds this script's directory to sys.path. Also expose the package root.
ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dashboard.components.filters import comparison_control, date_controls, preserve_widget
from dashboard.components.layout import load_theme
from dashboard.components.navigation import brand, sidebar
from dashboard.components.report import Report, active_report
from dashboard.data.analytics import DateScope
from dashboard.data.provider import DataSourceError, Snapshot, select_provider

VIEWS = (
    ("overview", "Overview", "dashboard"),
    ("sales", "Sales Trend", "trending_up"),
    ("categories", "Categories", "folder_open"),
    ("geography", "Geography", "public"),
    ("delivery", "Delivery & Reviews", "local_shipping"),
    ("pipeline_health", "Pipeline Health", "monitor_heart"),
)


@st.cache_resource(show_spinner=False)
def demo_snapshot() -> Snapshot:
    return select_provider("mock").load()


def main() -> None:
    st.set_page_config(page_title="CommercePulse", page_icon=":material/monitoring:",
                       layout="wide", initial_sidebar_state="auto")
    load_theme()
    pages = [
        st.Page(
            f"views/{filename}.py", title=title, icon=f":material/{symbol}:",
            default=filename == "overview", url_path=title.lower().replace(" & ", "-").replace(" ", "-"),
        )
        for filename, title, symbol in VIEWS
    ]
    selected = st.navigation(pages, position="hidden")
    source = os.getenv("DASHBOARD_DATA_SOURCE", "mock").strip().lower()
    sidebar(pages, selected, demo=source == "mock")
    for key in ("catalog_department", "geo_region", "geo_state", "delivery_carrier"):
        preserve_widget(key)

    try:
        snapshot = demo_snapshot() if source == "mock" else select_provider(source).load()
    except DataSourceError as error:
        with st.container(key="cp_toolbar"):
            brand()
        st.error(str(error))
        return

    with st.container(key="cp_toolbar"):
        logo, calendar, compare, freshness, export = st.columns([1.35, 1.55, 1.15, 1.1, 1.1],
                                                               gap="small", vertical_alignment="center")
        with logo:
            brand()
        with calendar:
            dates = date_controls(snapshot)
        with compare:
            comparison = comparison_control()
        with freshness:
            st.html(f'<div class="cp-freshness">Demo through {snapshot.as_of:%b %d, %Y}</div>')
        export_slot = export.empty()

    if dates is None:
        st.info("Choose an end date to apply the date range.")
        return
    scope = DateScope(*dates, comparison)
    report = Report(snapshot, scope, scope.prior(snapshot.min_date))
    token = active_report.set((report, export_slot))
    try:
        selected.run()
    finally:
        active_report.reset(token)


if __name__ == "__main__":
    main()
