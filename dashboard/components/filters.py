from datetime import date, timedelta

import streamlit as st

from dashboard.data.provider import Snapshot

COMPARISONS = ["Previous year", "Previous period", "No comparison"]


def date_controls(snapshot: Snapshot) -> tuple[date, date] | None:
    dates = st.date_input(
        "Date range", value=(max(snapshot.min_date, snapshot.as_of - timedelta(days=89)), snapshot.as_of),
        min_value=snapshot.min_date, max_value=snapshot.as_of,
        key="global_dates", label_visibility="collapsed",
        help="Filter all pages by an inclusive date range.",
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
