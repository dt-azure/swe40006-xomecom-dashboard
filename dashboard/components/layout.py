from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

THEME = Path(__file__).resolve().parents[1] / "styles" / "theme.css"


@dataclass(frozen=True)
class KPI:
    label: str
    value: str
    icon: str
    note: str = ""
    tone: str = "neutral"


def icon(name: str) -> str:
    return f'<span class="cp-icon" aria-hidden="true">{escape(name)}</span>'


def load_theme() -> None:
    st.html(THEME)


def page_heading(title: str, description: str) -> None:
    with st.container(key="cp_heading"):
        st.title(title, anchor=False)
        st.caption(description)


def kpis(*metrics: KPI) -> None:
    cards = "".join(
        f'<article class="cp-kpi"><div class="cp-kpi-label">{escape(metric.label)}'
        f'{icon(metric.icon)}</div><div class="cp-kpi-value">{escape(metric.value)}</div>'
        f'<div class="cp-kpi-note {escape(metric.tone)}">{escape(metric.note)}</div></article>'
        for metric in metrics
    )
    st.html(f'<div class="cp-kpis">{cards}</div>')


def delta(current: float, previous: float, comparison: str, points: bool = False) -> tuple[str, str]:
    from dashboard.data.analytics import percent_change

    change = current - previous if points else percent_change(current, previous)
    if pd.isna(change):
        return "", "neutral"
    suffix = " pp" if points else "%"
    tone = "positive" if change > 0 else "negative" if change < 0 else "neutral"
    return f"{change:+.1f}{suffix} vs {comparison.lower()}", tone


@contextmanager
def panel(key: str, title: str, description: str = ""):
    with st.container(key=f"cp_panel_{key}", border=True):
        st.markdown(f"### {title}")
        if description:
            st.caption(description)
        yield
