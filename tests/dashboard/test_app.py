import json
import os
import pytest
from datetime import date
from importlib import import_module
from pathlib import Path
from streamlit.testing.v1 import AppTest
from dashboard.data.analytics import totals
from dashboard.data.postgres_provider import PostgresProvider


ROOT = Path(__file__).resolve().parents[2] / "dashboard"
VIEWS = (
    ("overview", "Executive Overview", 6),
    ("sales", "Sales Trend & Velocity", 1),
    ("categories", "Category Performance & Merchandising", 3),
    ("geography", "Geographic Distribution & Regional Sales", 2),
    ("pipeline_health", "Data Pipeline Health & Gold Availability", 0),
)


def test_pages_are_importable():
    for name, _, _ in VIEWS:
        assert callable(import_module(f"dashboard.views.{name}").render)


def test_missing_database_configuration_is_displayed(monkeypatch):
    monkeypatch.delenv("DASHBOARD_DATABASE_URL", raising=False)
    app = AppTest.from_file(ROOT / "app.py").run()
    assert not app.exception
    assert "DASHBOARD_DATABASE_URL" in app.error[0].value
    assert [link.proto.label for link in app.get("page_link")] == [
        "Overview", "Sales Trend", "Categories", "Geography", "Pipeline Health",
    ]


@pytest.mark.integration
def test_loaded_gold_snapshot_and_dashboard(monkeypatch):
    url = os.getenv("DASHBOARD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DASHBOARD_TEST_DATABASE_URL to the supplied local Gold snapshot.")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", url)
    snapshot = PostgresProvider(url).load()
    assert snapshot.currency == "USD"
    assert len(snapshot.lines) == 51290
    assert len(snapshot.table_counts) == 9
    assert snapshot.table_counts["rows"].sum() == 105673
    assert snapshot.lines["date"].min().date() == date(2020, 1, 1)
    assert snapshot.lines["date"].max().date() == date(2023, 12, 31)
    baseline = totals(snapshot.lines)
    assert baseline["sales_cents"] == 651767400
    assert baseline["net_sales_cents"] == 556525931
    assert baseline["profit_cents"] == 106541358
    assert baseline["orders"] == 25728

    app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
    date_range = app.date_input(key="global_dates").value
    assert date_range[-1].isoformat() == "2023-12-31"
    for name, title, charts in VIEWS:
        if name != "overview":
            app.switch_page(f"views/{name}.py").run()
        assert not app.exception and not app.error
        assert app.title[0].value == title
        assert app.date_input(key="global_dates").value == date_range
        assert len(app.get("plotly_chart")) == charts
        assert app.get("download_button")

    app.switch_page("views/categories.py").run()
    pie = json.loads(app.get("plotly_chart")[0].proto.spec)["data"][0]
    assert pie["type"] == "pie" and sum(pie["customdata"]) == pytest.approx(100)
    app.selectbox(key="catalog_category").select("Face care").run()
    filtered_pie = json.loads(app.get("plotly_chart")[0].proto.spec)["data"][0]
    assert filtered_pie["labels"] == ["Face care"] and filtered_pie["customdata"] == [100]

    app.switch_page("views/geography.py").run()
    treemap = json.loads(app.get("plotly_chart")[0].proto.spec)["data"][0]
    assert treemap["type"] == "treemap"
    start, end = date_range
    scoped = snapshot.lines.loc[snapshot.lines["date"].between(str(start), str(end))]
    expected = (scoped.groupby("market")["net_sales_cents"].sum() / 100).to_dict()
    assert dict(zip(treemap["labels"], treemap["values"], strict=True)) == expected
    app.selectbox(key="geo_market").select("Europe").run()
    assert app.dataframe[0].value["market"].eq("Europe").all()
    app.switch_page("views/sales.py").run()
    app.date_input(key="global_dates").set_value((date(2023, 12, 31), date(2023, 12, 31))).run()
    html = "".join(item.proto.body for item in app.get("html"))
    assert "Hourly breakdown unavailable: Gold contains order dates but no transaction timestamps." in html
    assert "Mon–Fri: 0.0%" in html and "Sat–Sun: 100.0%" in html
    app.selectbox(key="gold_scope").select("Sample only").run()
    assert not app.exception
    assert "No Gold sales lines" in app.info[0].value
