import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number, percent
from dashboard.components.layout import KPI, delta, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.data.analytics import (
    PERIODS, daily_sales, daypart_velocity, divide, order_metrics, period_trend, search_rows,
)


def render(report: Report) -> pd.DataFrame:
    page_heading("Sales Trend & Velocity", "Revenue, order volume and buying patterns over the selected period.")
    orders = report.orders()
    daily = daily_sales(orders, report.scope)
    current = order_metrics(orders)
    previous = order_metrics(report.orders(previous=True))
    peak = daily.loc[daily["revenue_cents"].idxmax()]
    kpis(
        KPI("Period gross revenue", money(current["revenue"]), "payments",
            *delta(current["revenue"], previous["revenue"], report.scope.comparison)),
        KPI("Total order count", number(current["orders"]), "shopping_cart_checkout",
            *delta(current["orders"], previous["orders"], report.scope.comparison)),
        KPI("Peak daily revenue", money(peak["revenue_cents"]), "workspace_premium",
            peak["date"].strftime("%b %d, %Y") if current["orders"] else "No sales in period"),
        KPI("Revenue per order", money(current["aov"], 2), "point_of_sale",
            *delta(current["aov"], previous["aov"], report.scope.comparison)),
    )
    if orders.empty:
        st.info("No order activity is available for this date range.")
        return daily.iloc[:0]

    left, right = st.columns([7, 4])
    with left, panel("sales_revenue", "Revenue vs Order Count", "Merchandise revenue and non-cancelled orders"):
        granularity = st.segmented_control("Time grain", list(PERIODS), default="Daily",
                                           selection_mode="single", label_visibility="collapsed")
        trend = period_trend(orders, report.scope, granularity or "Daily")
        fig = charts.dual_axis(
            trend["date"], trend["revenue_cents"] / 100, trend["orders"], primary_name="Revenue (BRL)",
            secondary_name="Order count", range_slider=True,
        )
        charts.plot(fig, "sales_revenue", 335)
    with right, panel("sales_velocity", "Weekday vs Weekend Velocity", "Average orders per day by local hour"):
        velocity = daypart_velocity(orders, report.scope)
        fig = go.Figure(go.Heatmap(
            z=velocity, x=["06–11h", "11–16h", "16–21h", "21–06h"], y=velocity.index,
            colorscale=[[0, "#edf4fd"], [.5, "#a6d9c6"], [1, charts.GREEN]], showscale=False,
            texttemplate="%{z:.1f}", hovertemplate="%{y} · %{x}<br>%{z:.1f} orders/day<extra></extra>",
            hoverongaps=False,
        ))
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_xaxes(showgrid=False, side="top")
        charts.plot(fig, "sales_velocity", 280)
        weekends = daily.loc[daily["date"].dt.dayofweek.ge(5), "revenue_cents"].sum()
        st.caption(f"{percent(100 * divide(weekends, current['revenue']))} of revenue came from weekends.")

    with panel("sales_table", "Daily Sales Trend Breakdown", "Date-level orders, cancellations and fulfilment"):
        search, status = st.columns([2, 1])
        with search:
            query = st.text_input("Search dates or weekdays", placeholder="e.g. 2024-08 or Friday")
        with status:
            velocity_filter = st.selectbox("Velocity status", ["All", "Surging", "Normal", "Quiet", "No sales"])
        display = search_rows(daily.assign(weekday=daily["date"].dt.day_name()), query, ["date", "weekday"])
        if velocity_filter != "All":
            display = display.loc[display["velocity"].eq(velocity_filter)]
        download(display, "sales")
        table(display)
    return display


if __name__ == "__main__":
    run_view(render, "sales")
