from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from dashboard.data.analytics import DateScope, in_scope, mart_in_scope, sample_scope
from dashboard.data.provider import Snapshot

from .tables import download


@dataclass(frozen=True)
class Report:
    snapshot: Snapshot
    scope: DateScope
    prior: DateScope | None
    selection: str

    @property
    def currency(self) -> str:
        return self.snapshot.currency

    def lines(self, *, previous: bool = False) -> pd.DataFrame:
        scope = self.prior if previous else self.scope
        return (
            sample_scope(in_scope(self.snapshot.lines, scope), self.selection)
            if scope
            else self.snapshot.lines.iloc[:0]
        )

    def mart(self, name: str) -> pd.DataFrame:
        return mart_in_scope(sample_scope(self.snapshot.marts[name], self.selection), self.scope)


active_report: ContextVar[tuple[Report, st.delta_generator.DeltaGenerator]] = ContextVar("active_report")


def run_view(render: Callable[[Report], pd.DataFrame], name: str) -> None:
    report, export_slot = active_report.get()
    data = render(report)
    if len(data.columns):
        with export_slot:
            download(data, name, "Export Report", currency=report.currency)
