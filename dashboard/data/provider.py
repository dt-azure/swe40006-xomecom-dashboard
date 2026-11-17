"""Normalized reporting contract shared by all data sources."""
from dataclasses import dataclass
from datetime import date
import os
from typing import Protocol

import pandas as pd


ARCHITECTURE = (
    ("Source API", "Orders, catalog and customer records", "cloud_download"),
    ("Python ETL", "Extract and validate source records", "integration_instructions"),
    ("PostgreSQL Raw", "Persist source records", "database"),
    ("SQL Staging", "Normalize types and keys", "layers"),
    ("SQL Marts", "Build reporting aggregates", "table_chart"),
    ("Streamlit Dashboard", "Validate reporting outputs", "dashboard"),
)


@dataclass(frozen=True)
class Snapshot:
    min_date: date
    as_of: date
    orders: pd.DataFrame
    items: pd.DataFrame
    traffic: pd.DataFrame
    product_traffic: pd.DataFrame
    runs: pd.DataFrame
    stages: pd.DataFrame


class DataSourceError(Exception):
    """An actionable error safe to display in the dashboard."""


class DashboardDataProvider(Protocol):
    def load(self) -> Snapshot: ...


def select_provider(source: str | None = None) -> DashboardDataProvider:
    selected = (source if source is not None else os.getenv("DASHBOARD_DATA_SOURCE", "mock")).strip().lower()
    if selected == "mock":
        from .mock_provider import MockProvider

        return MockProvider()
    if selected == "postgres":
        from .postgres_provider import PostgresProvider

        return PostgresProvider(os.getenv("DASHBOARD_DATABASE_URL"))
    raise DataSourceError("Set DASHBOARD_DATA_SOURCE to mock or postgres.")
