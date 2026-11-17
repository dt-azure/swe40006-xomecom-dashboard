import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number, percent
from dashboard.components.layout import KPI, delta, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.data.analytics import (
    conversion_rate, geography_breakdown, in_scope, order_metrics, paid_orders, period_trend,
    purchased_lines, traffic_metrics,
)


def render(report: Report) -> pd.DataFrame:
    orders, traffic = report.orders(), report.traffic()
    page_heading("Executive Overview", "Commerce performance across sales channels, regions and devices.")
    current = order_metrics(orders)
    previous = order_metrics(report.orders(previous=True))
    current_cvr = conversion_rate(traffic)
    previous_cvr = conversion_rate(report.traffic(previous=True))
    specs = (
        ("Gross revenue", "revenue", money, "payments"),
        ("Total orders", "orders", number, "shopping_cart_checkout"),
        ("Customer base", "customers", number, "groups"),
        ("Average order value", "aov", money, "receipt_long"),
    )
    cards = []
    for label, key, fmt, symbol in specs:
        comparison = delta(current[key], previous[key], report.scope.comparison)
        cards.append(KPI(label, fmt(current[key]), symbol, *comparison))
    note, tone = delta(current_cvr, previous_cvr, report.scope.comparison, points=True)
    cards.append(KPI("Conversion rate · synthetic", percent(current_cvr, 2), "conversion_path",
                     note or "Demo sessions", tone))
    kpis(*cards)

    trend = period_trend(orders, report.scope, "Daily", traffic)
    if orders.empty:
        st.info("No orders are available for this date range.")
        return trend.iloc[:0]

    paid = paid_orders(orders)
    left, right = st.columns([7, 5])
    with left, panel("overview_trend", "Revenue & Conversion Rate Over Time", "Order revenue and synthetic sessions"):
        granularity = st.segmented_control("Time grain", ["Daily", "Weekly", "Monthly"], default="Weekly",
                                          selection_mode="single", label_visibility="collapsed")
        period = period_trend(orders, report.scope, granularity or "Weekly", traffic)
        fig = charts.dual_axis(
            period["date"], period["revenue_cents"] / 100, period["conversion"],
            primary_name="Revenue (BRL)", secondary_name="Conversion", right_suffix="%", right_format=".2f",
        )
        charts.plot(fig, "overview_trend", 285)
    with right, panel("overview_products", "Revenue & CVR by Top Products", "Top five SKUs by merchandise revenue"):
        products = purchased_lines(report.snapshot, orders).groupby(["sku", "product"], as_index=False)[
            "revenue_cents"
        ].sum().nlargest(5, "revenue_cents")
        visits = in_scope(report.snapshot.product_traffic, report.scope)
        products = products.merge(traffic_metrics(visits, "sku"), on="sku", how="left")
        fig = charts.horizontal(
            products["product"], products["revenue_cents"] / 100,
            custom=products["conversion"],
            hover="%{y}<br>R$ %{x:,.2f}<br>Synthetic CVR %{customdata:.2f}%<extra></extra>",
        )
        fig.update_traces(text=[percent(value, 2) for value in products["conversion"]],
                          textposition="auto", insidetextfont_color="white")
        fig.update_xaxes(tickprefix="R$ ")
        charts.plot(fig, "overview_products", 324)

    channel, region, device = st.columns(3)
    with channel, panel("overview_channels", "Attributed Revenue by Channel", "Synthetic channel assignment"):
        mix = paid.groupby("channel")["revenue_cents"].sum().sort_values(ascending=False)
        fig = charts.horizontal(mix.index, mix / 100, color=charts.SLATE,
                                hover="%{y}<br>R$ %{x:,.2f}<extra></extra>")
        fig.update_xaxes(tickprefix="R$ ")
        charts.plot(fig, "overview_channels", 228)
    with region, panel("overview_regions", "Regional Performance Snapshot", "Brazilian regions ranked by revenue"):
        regions = geography_breakdown(orders, ["region"])
        fig = charts.horizontal(regions["region"], regions["revenue_cents"] / 100,
                                custom=regions["orders"],
                                hover="%{y}<br>R$ %{x:,.2f}<br>%{customdata:,} orders<extra></extra>")
        fig.update_xaxes(tickprefix="R$ ")
        charts.plot(fig, "overview_regions", 228)
    with device, panel("overview_devices", "Revenue & CVR by Device", "Synthetic device and session data"):
        devices = traffic_metrics(traffic, "device").merge(
            paid.groupby("device", as_index=False)["revenue_cents"].sum(), on="device", how="left",
        ).sort_values("revenue_cents", ascending=False)
        fig = charts.horizontal(devices["device"], devices["revenue_cents"].fillna(0) / 100,
                                custom=devices["conversion"], color=charts.MINT,
                                hover="%{y}<br>R$ %{x:,.2f}<br>Synthetic CVR %{customdata:.2f}%<extra></extra>")
        fig.update_traces(text=[percent(value, 2) for value in devices["conversion"]],
                          textposition="auto", insidetextfont_color="white")
        fig.update_xaxes(tickprefix="R$ ")
        charts.plot(fig, "overview_devices", 228)
    return trend


if __name__ == "__main__":
    run_view(render, "overview")
