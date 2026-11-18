import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number, percent
from dashboard.components.layout import KPI, delta, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, mart_table, table
from dashboard.data.analytics import (
    breakdown,
    customer_activity,
    daily_sales,
    observed_customer_value,
    period_trend,
    retention_by_segment,
    rfm_segments,
    sample_scope,
    segment_performance,
    totals,
)


def render(report: Report) -> pd.DataFrame:
    lines = report.lines()
    currency = report.currency
    prefix = f"{currency} "
    page_heading("Executive Overview", f"Gold warehouse sales, profit, products and customers · {currency}")
    current, previous = totals(lines), totals(report.lines(previous=True))
    specs = (
        ("Net sales", "net_sales_cents", "payments"),
        ("Total orders", "orders", "shopping_cart_checkout"),
        ("Known customers", "customers", "groups"),
        ("Average order value", "aov_cents", "receipt_long"),
        ("Profit", "profit_cents", "trending_up"),
    )
    cards = [
        KPI(
            label,
            money(current[key], currency=currency) if key.endswith("_cents") else number(current[key]),
            symbol,
            *delta(current[key], previous[key], report.scope.comparison),
        )
        for label, key, symbol in specs
    ]
    kpis(*cards)
    export = daily_sales(lines, report.scope)
    if lines.empty:
        st.info("No Gold sales lines match the selected dates and data scope.")
        return export

    left, right = st.columns([7, 5])
    with left, panel("overview_trend", "Net Sales & Profit Over Time", "Net sales and profit after discounts"):
        granularity = st.segmented_control(
            "Time grain",
            ["Daily", "Weekly", "Monthly"],
            default="Weekly",
            selection_mode="single",
            label_visibility="collapsed",
        )
        trend = period_trend(lines, report.scope, granularity or "Weekly")
        fig = charts.dual_axis(
            trend["date"],
            trend["net_sales_cents"] / 100,
            trend["profit_cents"] / 100,
            primary_name=f"Net sales ({currency})",
            secondary_name=f"Profit ({currency})",
            left_prefix=prefix,
            right_prefix=prefix,
        )
        charts.plot(fig, "overview_trend", 285)
    with right, panel("overview_products", "Net Sales by Top Products", "Top products ranked by net sales"):
        products = breakdown(lines, ["sku", "product"]).head(5)
        fig = charts.horizontal(
            products["product"],
            products["net_sales_cents"] / 100,
            custom=products["margin"],
            hover=f"%{{y}}<br>{prefix}%{{x:,.2f}}<br>Margin %{{customdata:.1f}}%<extra></extra>",
        )
        fig.update_xaxes(tickprefix=prefix)
        charts.plot(fig, "overview_products", 324)

    segment, market, category = st.columns(3)
    segments = segment_performance(lines)
    with segment, panel("overview_segments", "Net Sales by Customer Segment"):
        fig = charts.horizontal(
            segments["segment"],
            segments["net_sales_cents"] / 100,
            custom=segments["margin"],
            hover=f"%{{y}}<br>{currency} %{{x:,.2f}}<br>Profit margin %{{customdata:.1f}}%<extra></extra>",
            color=charts.SLATE,
        )
        fig.update_xaxes(tickprefix=prefix)
        charts.plot(fig, "overview_segments", 228)
    with market, panel("overview_markets", "Market Performance Snapshot"):
        value_bars(lines, "market", "net_sales", currency, "overview_markets", charts.GREEN)
    with category, panel("overview_categories", "Profit by Category"):
        value_bars(lines, "category", "profit", currency, "overview_categories", charts.MINT)

    with st.expander("Segment Profitability & Loss-making Orders"):
        st.caption(
            "Gross share includes all segments. A loss-making order has negative summed profit within its segment."
        )
        display = segments[
            [
                "segment",
                "sales_cents",
                "gross_share_pct",
                "net_sales_cents",
                "profit_cents",
                "margin",
                "orders",
                "loss_orders",
            ]
        ]
        table(display, height=205, currency=currency)
        download(display, "segment-profitability", currency=currency)
        st.markdown("**Consumer and Corporate Gross Sales Share by Category**")
        st.caption("Each share uses gross sales across all segments in its category.")
        gross = lines.groupby(["category", "segment"])["sales_cents"].sum().unstack(fill_value=0)
        share = (
            gross.reindex(columns=["Consumer", "Corporate"], fill_value=0).div(
                gross.sum(axis=1).replace(0, float("nan")),
                axis=0,
            )
            * 100
        )
        share.columns = ["consumer_share_pct", "corporate_share_pct"]
        table(share.reset_index(), height=240, currency=currency)
    mart_table(
        report,
        "mart_segment_pnl",
        "Quarterly Segment P&L",
        [
            "order_quarter",
            "segment",
            "is_sample",
            "order_count",
            "customer_count",
            "gross_sales",
            "net_sales",
            "discount_amount",
            "profit",
            "profit_margin",
            "median_order_value",
            "loss_order_count",
            "first_order_date",
            "last_order_date",
        ],
    )
    retention_analysis(report, lines)
    mart_table(
        report,
        "mart_customer_retention",
        "Customer Retention Cohorts",
        [
            "cohort_month",
            "months_since_first_order",
            "is_sample",
            "cohort_customers",
            "active_customers",
            "retention_rate",
            "order_count",
            "net_sales",
            "profit",
            "first_order_date",
            "last_order_date",
        ],
    )
    return export


def retention_analysis(report: Report, lines: pd.DataFrame) -> None:
    currency = report.currency
    with st.expander("Repeat Purchases & Customer Activity"):
        segment = st.selectbox("Customer activity segment", ["All segments", *sorted(lines["segment"].unique())])
        scoped = lines if segment == "All segments" else lines.loc[lines["segment"].eq(segment)]
        activity = customer_activity(scoped)
        if activity.empty:
            st.info("No known customers match the selected dates and segment.")
        else:
            observed_through = scoped["date"].max()
            st.caption(f"Purchases in the selected period, observed through {observed_through:%b %d, %Y}.")
            repeat_rate = 100 * activity["orders"].gt(1).mean()
            history = sample_scope(report.snapshot.lines, report.selection)
            if segment != "All segments":
                history = history.loc[history["segment"].eq(segment)]
            average_value = observed_customer_value(history, activity.index, observed_through)
            segments = rfm_segments(activity)
            inactive = segments.loc[
                segments["recency"].eq("181+ days") & segments["value"].eq("Upper quartile"), "customers"
            ].sum()
            enough_history = (scoped["date"].max() - scoped["date"].min()).days >= 181
            kpis(
                KPI("Repeat purchase rate", percent(repeat_rate), "repeat", "At least two distinct orders"),
                KPI(
                    "Observed lifetime sales per customer",
                    money(average_value, 2, currency=currency),
                    "payments",
                    "From first recorded purchase",
                ),
                KPI(
                    "High-value inactive customers",
                    number(inactive) if enough_history else "—",
                    "person_search",
                    "Upper quartile · 181+ days" if enough_history else "Requires 181+ days of order history",
                ),
            )
            st.caption(
                "Lifetime sales sum recorded net sales through the observation date for customers in view. "
                "RFM groups and the inactive count use the selected period and do not predict churn."
            )
            table(segments, height=250, currency=currency)
            download(segments, "customer-rfm-segments", currency=currency)
        st.markdown("**Repeat purchase rate by segment**")
        st.caption("Customers with activity in multiple segments are counted within each segment.")
        table(retention_by_segment(lines), height=195, currency=currency)

    cohorts = report.mart("mart_customer_retention")
    with st.expander("Cohort Retention Heatmap"):
        st.caption("Latest 12 cohort rows. Rows without full order-date coverage in the selected window are excluded.")
        if cohorts.empty:
            st.info("Expand the date range to include a complete cohort observation.")
        else:
            labels = pd.to_datetime(cohorts["cohort_month"]).dt.strftime("%Y-%m")
            if report.selection == "Include sample rows":
                labels += cohorts["is_sample"].map({True: " · sample", False: " · historical"})
            pivot = (
                cohorts.assign(cohort=labels)
                .pivot(
                    index="cohort",
                    columns="months_since_first_order",
                    values="retention_rate",
                )
                .tail(12)
            )
            fig = go.Figure(
                go.Heatmap(
                    x=pivot.columns,
                    y=pivot.index,
                    z=pivot,
                    zmin=0,
                    zmax=1,
                    colorscale=[[0, "#edf4fd"], [0.45, charts.SAGE], [1, charts.GREEN]],
                    colorbar=dict(tickformat=".0%"),
                    hovertemplate="Cohort %{y}<br>Month %{x}<br>Retained %{z:.1%}<extra></extra>",
                    hoverongaps=False,
                )
            )
            fig.update_xaxes(title="Months since first order")
            charts.plot(fig, "retention_heatmap", 300)


def value_bars(lines: pd.DataFrame, dimension: str, metric: str, currency: str, key: str, color: str) -> None:
    amounts = lines.groupby(dimension)[f"{metric}_cents"].sum().sort_values(ascending=False)
    fig = charts.horizontal(
        amounts.index, amounts / 100, color=color, hover=f"%{{y}}<br>{currency} %{{x:,.2f}}<extra></extra>"
    )
    fig.update_xaxes(tickprefix=f"{currency} ")
    charts.plot(fig, key, 228)


if __name__ == "__main__":
    run_view(render, "overview")
