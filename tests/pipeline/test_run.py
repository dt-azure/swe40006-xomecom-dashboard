from pipeline import run as pipeline_run
from pipeline.run import Settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SOURCE_API_URL", "http://api:5000/")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "6543")

    s = Settings.from_env()

    assert s.source_api_url == "http://api:5000"  # trailing slash stripped
    assert s.pg_host == "db"
    assert s.pg_port == 6543


def test_main_returns_1_when_api_unreachable(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("no api")

    monkeypatch.setattr(pipeline_run.requests, "get", boom)

    assert pipeline_run.main() == 1
