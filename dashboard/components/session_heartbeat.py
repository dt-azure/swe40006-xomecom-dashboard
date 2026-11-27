"""Streamlit session tracking and its internal reporting interface."""

from dataclasses import dataclass
from uuid import uuid4

import streamlit as st

from dashboard.components.session_registry import INACTIVITY_TIMEOUT_SECONDS, SessionRegistry

HEARTBEAT_INTERVAL_SECONDS = 30
SESSION_ID_KEY = "_commercepulse_heartbeat_session_id"


@dataclass(frozen=True)
class SessionMetrics:
    active_count: int | None
    registry_available: bool
    heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS
    inactivity_timeout_seconds: int = INACTIVITY_TIMEOUT_SECONDS


@st.cache_resource(show_spinner=False)
def _registry() -> SessionRegistry:
    return SessionRegistry()


def get_session_metrics() -> SessionMetrics:
    """Read Recently Active Streamlit Sessions from this dashboard process."""
    try:
        return SessionMetrics(active_count=_registry().active_count(), registry_available=True)
    except Exception:
        return SessionMetrics(active_count=None, registry_available=False)


@st.fragment(run_every=HEARTBEAT_INTERVAL_SECONDS)
def refresh_session_heartbeat() -> None:
    try:
        if SESSION_ID_KEY not in st.session_state:
            st.session_state[SESSION_ID_KEY] = str(uuid4())
        _registry().heartbeat(st.session_state[SESSION_ID_KEY])
    except Exception:
        # Telemetry is best-effort. Try again on the next fragment run.
        return
