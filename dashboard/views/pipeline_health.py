from html import escape

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import number, percent
from dashboard.components.layout import KPI, icon, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.data.analytics import in_scope, pipeline_metrics, search_rows
from dashboard.data.provider import ARCHITECTURE


def render(report: Report) -> pd.DataFrame:
    page_heading("Data Pipeline Health & Ingestion Telemetry",
                 "Simulated telemetry for the planned pipeline. Timestamps are UTC.")
    status_slot, trigger_slot = st.columns([2, 1], vertical_alignment="center")
    with status_slot:
        st.html(f'<div class="cp-demo-tag">{icon("science")}<strong>SIMULATED TELEMETRY</strong></div>')
    with trigger_slot:
        st.button("Ingestion unavailable", disabled=True, icon=":material/play_arrow:", width="stretch")

    runs = in_scope(report.snapshot.runs, report.scope, "started_at").sort_values("started_at", ascending=False)
    metrics = pipeline_metrics(runs, report.scope.end)
    kpis(
        KPI("Ingestion success rate", percent(metrics["success_rate"]), "verified", f"{len(runs)} runs in scope"),
        KPI("Rows ingested on final day", number(metrics["rows_last_day"]), "database",
            f"{report.scope.end:%b %d} UTC · {metrics['run_count_last_day']} runs"),
        KPI("Average execution time", number(metrics["average_duration"], 0, " s"), "timer",
            f"P95: {number(metrics['p95_duration'], 0, ' s')}"),
        KPI("Runs with exceptions", number(metrics["exceptions"]), "warning",
            f"{runs['status'].eq('Warning').sum()} warnings · {runs['status'].eq('Failed').sum()} failures",
            "negative" if metrics["exceptions"] else "neutral"),
    )
    if runs.empty:
        st.info("No simulated ETL runs are available for this date range.")
        return runs

    volume, topology = st.columns([7, 5])
    with volume, panel("pipeline_volume", "Ingestion Volume & Duration", "Rows written to Raw and mean execution time"):
        window = st.segmented_control("Telemetry time grain", ["Latest day", "Daily"], default="Latest day",
                                      selection_mode="single", label_visibility="collapsed")
        latest = runs.iloc[0]
        if window == "Daily":
            grouped = runs.groupby(runs["started_at"].dt.normalize()).agg(
                rows=("rows", "sum"), duration=("duration_seconds", "mean"),
            )
        else:
            grouped = runs.loc[runs["started_at"].dt.date.eq(latest["started_at"].date())].set_index(
                "started_at"
            )[["rows", "duration_seconds"]].rename(columns={"duration_seconds": "duration"}).sort_index()
        fig = charts.dual_axis(
            grouped.index, grouped["rows"], grouped["duration"], primary_name="Rows written",
            secondary_name="Execution duration", left_prefix="", right_suffix=" s", bars=True,
        )
        if window != "Daily":
            fig.update_xaxes(tickformat="%H:%M", dtick=4 * 60 * 60 * 1000)
        charts.plot(fig, "pipeline_volume", 285)
        if window != "Daily":
            st.caption(f"Latest run day in scope · {latest['started_at']:%b %d, %Y} UTC")

    with topology, panel("pipeline_topology", "Stage Health & Topology Graph", f"Latest run · {latest['run_id']}"):
        stage_rows(report.snapshot.stages.loc[report.snapshot.stages["run_id"].eq(latest["run_id"])])

    with panel("pipeline_history", "ETL Run Telemetry & Execution Log",
               "Inspect historical runs and their simulated diagnostics."):
        search, status_slot = st.columns([2, 1])
        with search:
            query = st.text_input("Search by run ID", placeholder="e.g. run_20240815")
        with status_slot:
            status = st.selectbox("Run status", ["All statuses", "Success", "Warning", "Failed"])
        display = search_rows(runs, query, ["run_id"])
        if status != "All statuses":
            display = display.loc[display["status"].eq(status)]
        download(display, "pipeline-health")
        table(display, height=290)
        if not display.empty:
            run_id = st.selectbox("Inspect run diagnostics", display["run_id"], index=None,
                                  placeholder="Select a run ID")
            if run_id:
                run = display.set_index("run_id").loc[run_id]
                st.code(f"{run['started_at']:%Y-%m-%d %H:%M} UTC | {run_id} | {run['status'].upper()}\n"
                        f"{run['diagnostic']}\n"
                        f"Rows written to Raw: {run['rows']:,} | Runtime: {run['duration_seconds']} s",
                        language="text")
                stage_rows(report.snapshot.stages.loc[report.snapshot.stages["run_id"].eq(run_id)])
    return display


def stage_rows(stages: pd.DataFrame) -> None:
    cards = []
    results = stages.set_index("stage")
    for stage, detail, symbol in ARCHITECTURE:
        row = results.loc[stage] if stage in results.index else None
        status = row["status"] if row is not None else "Unknown"
        duration = f" · {row['duration_seconds']} s" if status not in {"Skipped", "Unknown"} else ""
        cards.append(
            f'<div class="cp-stage">{icon(symbol)}<div><strong>{escape(stage)}</strong>'
            f'<small>{escape(detail)}</small></div><span class="cp-stage-state {escape(status.lower())}">'
            f'{escape(status + duration)}</span></div>'
        )
    connector = '<div class="cp-stage-arrow" aria-hidden="true">↓</div>'
    st.html(connector.join(cards))


if __name__ == "__main__":
    run_view(render, "pipeline-health")
