from datetime import date, timedelta

import streamlit as st

from dashboard.data.analytics import DATA_SCOPES, sample_scope
from dashboard.data.provider import Snapshot

COMPARISONS = ["Previous year", "Previous period", "No comparison"]


def data_scope_control() -> str:
    def reset_dates():
        st.session_state.pop("global_dates", None)

    return st.selectbox(
        "Gold data", DATA_SCOPES, key="gold_scope", on_change=reset_dates,
        help="History is shown by default. Generated warehouse rows are identified by the Gold sample flag.",
    )


def date_controls(snapshot: Snapshot, selection: str) -> tuple[date, date] | None:
    available = sample_scope(snapshot.lines, selection)["date"]
    latest = available.max().date() if not available.empty else snapshot.calendar_end
    saved = st.session_state.get("global_dates")
    if saved and any(not snapshot.min_date <= day <= snapshot.calendar_end for day in saved):
        st.session_state.pop("global_dates")

    dates = st.date_input(
        "Date range", value=(max(snapshot.min_date, latest - timedelta(days=89)), latest),
        min_value=snapshot.min_date, max_value=snapshot.calendar_end,
        key="global_dates", label_visibility="collapsed",
        help="Filter by order date. Both selected dates are included.",
        format="YYYY/MM/DD",
    )
    return dates if len(dates) == 2 else None


def comparison_control() -> str:
    return st.selectbox(
        "Comparison period", COMPARISONS, key="global_comparison", label_visibility="collapsed",
        help="Compare business metrics to the previous calendar year or previous equally long period.",
    )


def preserve_widget(key: str) -> None:
    """Retain a page-specific widget value while its page is off screen."""
    if key in st.session_state:
        st.session_state[key] = st.session_state[key]
