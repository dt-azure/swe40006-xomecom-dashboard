"""Pipeline entry point: `python -m pipeline.run`.

PLACEHOLDER: checks it can reach the Source API and PostgreSQL, then exits.
That proves the container wiring (network names, env vars, credentials)
before the real fetch/load/transform code exists. The Pipeline workstream
replaces `run()` but keeps `main()` as the entry point, because the image and
the daily scheduled job call `python -m pipeline.run`.
"""

import logging
import os
import sys
from dataclasses import dataclass

import psycopg
import requests

log = logging.getLogger("pipeline")


@dataclass(frozen=True)
class Settings:
    source_api_url: str
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            source_api_url=os.getenv("SOURCE_API_URL", "http://localhost:5000").rstrip("/"),
            pg_host=os.getenv("POSTGRES_HOST", "localhost"),
            pg_port=int(os.getenv("POSTGRES_PORT", "5432")),
            pg_db=os.getenv("POSTGRES_DB", "ecommerce"),
            pg_user=os.getenv("POSTGRES_USER", "ecommerce"),
            pg_password=os.environ.get("POSTGRES_PASSWORD", ""),
        )

    def pg_conninfo(self) -> str:
        return psycopg.conninfo.make_conninfo(
            host=self.pg_host,
            port=self.pg_port,
            dbname=self.pg_db,
            user=self.pg_user,
            password=self.pg_password,
            connect_timeout=10,
        )


def run(settings: Settings) -> None:
    resp = requests.get(f"{settings.source_api_url}/health", timeout=10)
    resp.raise_for_status()
    log.info("Source API reachable at %s", settings.source_api_url)

    with psycopg.connect(settings.pg_conninfo()) as conn:
        version = conn.execute("SELECT version()").fetchone()[0]
    log.info("PostgreSQL reachable: %s", version.split(",")[0])

    log.info("Placeholder run finished: nothing fetched or loaded yet")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        run(Settings.from_env())
    except Exception:
        log.exception("Pipeline run failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
