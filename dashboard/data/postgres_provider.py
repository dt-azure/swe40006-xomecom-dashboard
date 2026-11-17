"""PostgreSQL integration boundary pending the project's mart mappings."""
from dataclasses import dataclass

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .provider import DataSourceError, Snapshot


@dataclass(frozen=True)
class PostgresProvider:
    database_url: str | None

    def load(self) -> Snapshot:
        if not self.database_url:
            raise DataSourceError(
                "Set DASHBOARD_DATABASE_URL to the PostgreSQL connection URL, "
                "or set DASHBOARD_DATA_SOURCE=mock to run locally."
            )
        try:
            url = make_url(self.database_url)
        except ArgumentError:
            raise DataSourceError("DASHBOARD_DATABASE_URL is not a valid SQLAlchemy URL.") from None
        if url.drivername not in {"postgresql", "postgresql+psycopg2"} or not url.database:
            raise DataSourceError("Use a postgresql+psycopg2 URL that includes the database name.")
        raise DataSourceError(
            "PostgreSQL mart mappings are pending. See the data contracts in dashboard/README.md "
            "and use DASHBOARD_DATA_SOURCE=mock in the meantime."
        )
