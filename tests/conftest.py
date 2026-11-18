# conftest.py
import pytest

@pytest.fixture
def dashboard_app_path(pytestconfig) -> str:
    return str(pytestconfig.rootpath / "dashboard" / "app.py")