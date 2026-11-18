# conftest.py
import pytest

@pytest.fixture
def dashboard_app_path(pytestconfig) -> str:
    # rootpath = the folder containing pyproject.toml (the repo root)
    return str(pytestconfig.rootpath / "dashboard" / "app.py")