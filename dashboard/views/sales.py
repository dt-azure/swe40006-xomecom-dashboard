import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number
from dashboard.components.layout import KPI, delta, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.components.velocity import velocity_card
from dashboard.data.analytics import PERIODS, daily_sales, period_trend, search_rows, totals


def render(report: Report) -> pd.DataFrame:
    currency = report.currency
    page_heading("Sales Trend & Velocity", f"Net sales, order volume and weekday patterns · {currency}")
    lines = report.lines()
    daily = daily_sales(lines, report.scope)
    if daily.empty:
        st.info("No Gold sales lines match the selected dates and data scope.")
        velocity_card(lines, currency)
        return daily

    current, previous = totals(lines), totals(report.lines(previous=True))
    peak = daily.loc[daily["net_sales_cents"].idxmax()]
    kpis(
        KPI("Period net sales", money(current["net_sales_cents"], currency=currency), "payments",
            *delta(current["net_sales_cents"], previous["net_sales_cents"], report.scope.comparison)),
        KPI("Total order count", number(current["orders"]), "shopping_cart_checkout",
            *delta(current["orders"], previous["orders"], report.scope.comparison)),
        KPI("Peak daily net sales", money(peak["net_sales_cents"], currency=currency), "workspace_premium",
            peak["date"].strftime("%b %d, %Y")),
        KPI("Net sales per order", money(current["aov_cents"], 2, currency=currency), "point_of_sale",
            *delta(current["aov_cents"], previous["aov_cents"], report.scope.comparison)),
    )

    left, right = st.columns([7, 4])
    with left, panel("sales_revenue", "Net Sales vs Order Count", "Periods without sales appear as gaps."):
        granularity = st.segmented_control("Time grain", list(PERIODS), default="Daily",
                                           selection_mode="single", label_visibility="collapsed")
        trend = period_trend(lines, report.scope, granularity or "Daily")
        fig = charts.dual_axis(
            trend["date"], trend["net_sales_cents"] / 100, trend["orders"],
            primary_name=f"Net sales ({currency})", secondary_name="Distinct orders",
            left_prefix=f"{currency} ", range_slider=True,
        )
        charts.plot(fig, "sales_revenue", 335)
    with right:
        velocity_card(lines, currency)

    with panel("sales_table", "Daily Sales Trend Breakdown", "Sales, discounts, profit and distinct order counts"):
        search, status = st.columns([2, 1])
        with search:
            query = st.text_input("Search dates or weekdays", placeholder="e.g. 2023-12 or Friday")
        with status:
            speed = st.selectbox("Velocity status", ["All", "Surging", "Normal", "Quiet"],
                                 help="Surging exceeds 125% of median daily orders. Quiet is below 75%.")
        display = search_rows(daily.assign(weekday=daily["date"].dt.day_name()), query, ["date", "weekday"])
        if speed != "All":
            display = display.loc[display["velocity"].eq(speed)]
        download(display, "sales", currency=currency)
        table(display, currency=currency)
    return display


if __name__ == "__main__":
    run_view(render, "sales")
