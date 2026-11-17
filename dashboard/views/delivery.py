from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import number, percent
from dashboard.components.layout import KPI, delta, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.data.analytics import SLA_STATUSES, divide, on_time_rate, search_rows, shipments

COLUMNS = ["order_id", "city", "state", "carrier", "dispatched_at", "estimated_at", "delivered_at",
           "transit_days", "variance_hours", "sla_status", "review_score", "review_note"]


def render(report: Report) -> pd.DataFrame:
    page_heading("Delivery Performance & Customer Reviews", "Carrier transit time, delivery estimates and customer ratings.")
    carrier_slot, score_slot = st.columns(2)
    with carrier_slot:
        carriers = sorted(report.snapshot.orders["carrier"].unique())
        carrier = st.selectbox("Carrier", ["All carriers", *carriers], key="delivery_carrier")
    with score_slot:
        score = st.selectbox("Review score", ["All ratings", "4–5 stars", "1–3 stars", "Unreviewed"])
    deliveries = filter_shipments(shipments(report.orders()), carrier, score)
    previous = filter_shipments(shipments(report.orders(previous=True)), carrier, score)
    delayed = deliveries["sla_status"].eq("Delayed").sum()
    kpis(
        KPI("Average delivery duration", number(deliveries["transit_days"].mean(), 1, " days"), "timer",
            "Dispatch to delivery"),
        KPI("On-time delivery rate", percent(on_time_rate(deliveries)), "verified",
            *delta(on_time_rate(deliveries), on_time_rate(previous), report.scope.comparison, points=True)),
        KPI("Average review score", number(deliveries["review_score"].mean(), 2, " / 5"), "star",
            f"{number(deliveries['review_score'].count())} submitted ratings"),
        KPI("Delayed shipments", number(delayed), "warning",
            f"{percent(100 * divide(delayed, len(deliveries)))} of delivered orders", "negative"),
    )
    if deliveries.empty:
        st.info("No delivered orders match the current dates, carrier and review filters.")
        return deliveries[COLUMNS]

    impact, variance = st.columns([7, 5])
    with impact, panel("delivery_rating", "Delivery Duration vs Customer Review Score",
                       "Mean rating by transit time with the number of reviews per group"):
        reviews = deliveries.dropna(subset=["review_score"]).copy()
        if reviews.empty:
            st.info("There are no ratings in the selected shipment group.")
        else:
            bins = ["≤ 2 days", "> 2–3 days", "> 3–4 days", "> 4–5 days", "> 5 days"]
            reviews["cohort"] = pd.cut(reviews["transit_days"], [0, 2, 3, 4, 5, np.inf], labels=bins)
            cohorts = reviews.groupby("cohort", observed=False)["review_score"].agg(["mean", "count"])
            fig = charts.horizontal(
                cohorts.index, cohorts["mean"], custom=cohorts["count"],
                hover="%{y}<br>%{x:.2f} / 5 · %{customdata:,} reviews<extra></extra>",
                color=[charts.GREEN, charts.MINT, charts.SAGE, charts.ORANGE, charts.AMBER],
            )
            fig.update_traces(text=cohorts["mean"].map(lambda value: number(value, 2)), textposition="auto")
            fig.update_xaxes(range=[0, 5], title="Mean review score")
            charts.plot(fig, "delivery_rating", 298)
    with variance, panel("delivery_variance", "Estimated vs Actual Delivery Variance",
                         "Actual arrival minus estimated arrival, in hours"):
        mix = deliveries["sla_status"].value_counts().reindex(SLA_STATUSES, fill_value=0)
        fig = go.Figure(go.Histogram(
            x=deliveries["variance_hours"], xbins=dict(size=12), marker_color=charts.MINT,
            hovertemplate="Variance bin: %{x} hours<br>%{y} shipments<extra></extra>",
        ))
        fig.update_layout(bargap=.08)
        fig.add_vline(x=0, line_color=charts.AMBER, line_width=2, line_dash="dot")
        fig.update_xaxes(title="Hours from estimate")
        fig.update_yaxes(title="Shipments")
        charts.plot(fig, "delivery_variance", 236)
        mix_cards = "".join(
            f'<div><span>{escape(label)}</span><strong style="color:{charts.STATUS_COLORS[label]}">'
            f'{percent(100 * count / len(deliveries))}</strong></div>'
            for label, count in mix.items()
        )
        st.html(f'<div class="cp-sla">{mix_cards}</div>')

    with panel("delivery_ledger", "Recent Shipments & Review Log", "Delivered orders sorted by arrival date"):
        query_slot, status_slot = st.columns([2, 1])
        with query_slot:
            query = st.text_input("Search shipments", placeholder="Order ID, city or carrier")
        with status_slot:
            status = st.selectbox("Delivery status", ["All statuses", *SLA_STATUSES])
        display = search_rows(deliveries, query, ["order_id", "city", "state", "carrier"])
        if status != "All statuses":
            display = display.loc[display["sla_status"].eq(status)]
        display = display.sort_values("delivered_at", ascending=False)[COLUMNS]
        download(display, "delivery-reviews")
        table(display)
    return display


def filter_shipments(deliveries: pd.DataFrame, carrier: str, score: str) -> pd.DataFrame:
    if carrier != "All carriers":
        deliveries = deliveries.loc[deliveries["carrier"].eq(carrier)]
    filters = {
        "4–5 stars": deliveries["review_score"].ge(4),
        "1–3 stars": deliveries["review_score"].lt(4),
        "Unreviewed": deliveries["review_score"].isna(),
    }
    return deliveries.loc[filters[score]] if score in filters else deliveries


if __name__ == "__main__":
    run_view(render, "delivery-reviews")
