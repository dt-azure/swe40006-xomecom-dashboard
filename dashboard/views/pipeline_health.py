import pandas as pd
import streamlit as st

from dashboard.components.formatting import number
from dashboard.components.layout import KPI, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.data.analytics import sample_scope


def render(report: Report) -> pd.DataFrame:
    snapshot = report.snapshot
    all_lines = snapshot.lines
    selected = sample_scope(all_lines, report.selection)
    page_heading("Data Pipeline Health & Gold Availability", "Verified warehouse reads and reporting coverage.")
    kpis(
        KPI("Readable Gold tables", number(len(snapshot.table_counts)), "table_chart"),
        KPI("Gold sales lines", number(len(all_lines)), "database", "All dates and sample flags"),
        KPI("Sales lines in view", number(len(report.lines())), "filter_alt", "Selected dates and data scope"),
        KPI("Warehouse checked", f"{snapshot.read_at:%H:%M:%S} UTC", "schedule", f"{snapshot.read_at:%Y-%m-%d}"),
    )
    metadata, inventory = st.columns([4, 7])
    with metadata, panel("pipeline_coverage", "Sales Data Coverage"):
        if not selected.empty:
            st.write(f"Order dates: {selected['date'].min():%Y-%m-%d} to {selected['date'].max():%Y-%m-%d}")
        last_ingestion = pd.to_datetime(selected["ingested_at"], utc=True).max()
        if pd.notna(last_ingestion):
            st.write(f"Latest sales-line ingestion: {last_ingestion:%Y-%m-%d %H:%M:%S} UTC")
        st.caption("Ingestion timestamps describe sales records. Transform status requires pipeline telemetry.")
        st.info("ETL run history and staleness alerts require a confirmed ops.pipeline_runs contract.")
    with (
        inventory,
        panel(
            "pipeline_inventory", "Gold Table Inventory", "Whole-table row counts at the time of the warehouse check"
        ),
    ):
        display = snapshot.table_counts.sort_values("table").reset_index(drop=True)
        table(display, height=344)
        download(display, "gold-inventory")
    return display


if __name__ == "__main__":
    run_view(render, "gold-inventory")
