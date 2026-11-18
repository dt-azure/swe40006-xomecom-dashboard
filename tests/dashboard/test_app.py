from datetime import date
from importlib import import_module
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2] / "dashboard"
VIEWS = (
    ("overview", "Executive Overview", 5),
    ("sales", "Sales Trend & Velocity", 2),
    ("categories", "Category Performance & Merchandising", 2),
    ("geography", "Geographic Distribution & Regional Sales", 2),
    ("delivery", "Delivery Performance & Customer Reviews", 2),
    ("pipeline_health", "Data Pipeline Health & Ingestion Telemetry", 1),
)


@pytest.mark.parametrize("view,title,charts", VIEWS)
def test_views_are_importable_and_render(monkeypatch, view, title, charts):
    monkeypatch.setenv("DASHBOARD_DATA_SOURCE", "mock")
    assert callable(import_module(f"dashboard.views.{view}").render)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=20).run()
    if view != "overview":
        app.switch_page(f"views/{view}.py").run()
    assert not app.exception
    assert app.title[0].value == title
    assert len(app.get("plotly_chart")) == charts
    assert app.get("download_button")
    assert "DEMO ENVIRONMENT" in "".join(element.value for element in app.get("html"))


def test_navigation_preserves_shared_and_relevant_local_filters(monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_SOURCE", "mock")
    app = AppTest.from_file(ROOT / "app.py").run()
    span = (date(2024, 8, 1), date(2024, 8, 10))
    app.date_input(key="global_dates").set_value(span).run()
    app.selectbox(key="global_comparison").select("Previous period").run()

    app.switch_page("views/categories.py").run()
    app.selectbox(key="catalog_department").select("Sports").run()
    assert app.dataframe[0].value["department"].eq("Sports").all()
    app.switch_page("views/geography.py").run()
    app.selectbox(key="geo_region").select("South").run()
    app.selectbox(key="geo_state").select("PR").run()
    assert app.dataframe[0].value["state"].eq("PR").all()
    app.switch_page("views/categories.py").run()
    assert not app.exception
    assert app.selectbox(key="catalog_department").value == "Sports"
    assert app.date_input(key="global_dates").value == span
    assert app.selectbox(key="global_comparison").value == "Previous period"
    app.text_input(key="catalog_search").set_value("missing_sku").run()
    assert not app.exception and app.info
    assert app.get("download_button")[0].proto.disabled


def test_pipeline_filters_and_diagnostics(monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_SOURCE", "mock")
    app = AppTest.from_file(ROOT / "app.py").run().switch_page("views/pipeline_health.py").run()
    app.selectbox[1].select("Failed").run()
    failed = app.dataframe[0].value
    assert not failed.empty and failed["status"].eq("Failed").all()
    run_id = failed.iloc[0]["run_id"]
    app.text_input[0].set_value(run_id).run()
    assert len(app.dataframe[0].value) == 1
    app.selectbox[2].select(run_id).run()
    assert not app.exception
    assert "retry limit exceeded" in app.get("code")[0].proto.code_text


def test_postgres_configuration_is_displayed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_SOURCE", "postgres")
    monkeypatch.delenv("DASHBOARD_DATABASE_URL", raising=False)
    app = AppTest.from_file(ROOT / "app.py").run()
    assert not app.exception
    assert "DASHBOARD_DATABASE_URL" in app.error[0].value
