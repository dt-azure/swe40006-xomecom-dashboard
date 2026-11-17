"""Normalized reporting contract for the PostgreSQL Gold provider."""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class Snapshot:
    min_date: date
    calendar_end: date
    currency: str
    lines: pd.DataFrame
    marts: dict[str, pd.DataFrame]
    table_counts: pd.DataFrame
    read_at: datetime


class DataSourceError(Exception):
    """An actionable error safe to display in the dashboard."""


class DashboardDataProvider(Protocol):
    def load(self) -> Snapshot: ...
