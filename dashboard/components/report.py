from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable

import pandas as pd
import streamlit as st

from dashboard.data.analytics import DateScope, in_scope
from dashboard.data.provider import Snapshot

from .tables import download


@dataclass(frozen=True)
class Report:
    snapshot: Snapshot
    scope: DateScope
    prior: DateScope | None

    def orders(self, *, previous: bool = False) -> pd.DataFrame:
        scope = self.prior if previous else self.scope
        return in_scope(self.snapshot.orders, scope) if scope else self.snapshot.orders.iloc[:0]

    def traffic(self, *, previous: bool = False) -> pd.DataFrame:
        scope = self.prior if previous else self.scope
        return in_scope(self.snapshot.traffic, scope) if scope else self.snapshot.traffic.iloc[:0]


active_report: ContextVar[tuple[Report, st.delta_generator.DeltaGenerator]] = ContextVar("active_report")


def run_view(render: Callable[[Report], pd.DataFrame], name: str) -> None:
    report, export_slot = active_report.get()
    data = render(report)
    with export_slot:
        download(data, name, "Export Report")
