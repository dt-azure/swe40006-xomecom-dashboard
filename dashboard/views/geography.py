import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number, percent
from dashboard.components.layout import KPI, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.data.analytics import geography_breakdown, percent_change, search_rows

# Schematic west-to-east/north-to-south positions for all Brazilian federative units.
TILE_ROWS = [
    [None, "RR", None, "AP", None, None, None, None, None],
    [None, "AM", None, "PA", "MA", "PI", "CE", "RN", None],
    ["AC", "RO", "MT", "TO", None, "BA", "PE", "PB", None],
    [None, None, "MS", "GO", "DF", "MG", "SE", "AL", None],
    [None, None, None, "PR", "SP", "RJ", "ES", None, None],
    [None, None, None, "RS", "SC", None, None, None, None],
]
MEASURES = {"Revenue": "revenue_cents", "Orders": "orders", "Customers": "customers"}


def cartogram(states: pd.DataFrame, metric: str) -> go.Figure:
    tiles = pd.DataFrame(
        [(state, x, -y) for y, row in enumerate(TILE_ROWS) for x, state in enumerate(row) if state],
        columns=["state", "x", "y"],
    ).merge(states, on="state", how="left")
    tiles["has_data"] = tiles[MEASURES[metric]].notna()
    tiles["value"] = tiles[MEASURES[metric]] / 100 if metric == "Revenue" else tiles[MEASURES[metric]]
    labels = [money(value, 2) if metric == "Revenue" else number(value) for value in tiles[MEASURES[metric]]]
    tiles["hover"] = [f"{state} · {metric}: {label}" if has_data else f"{state} · Outside current scope"
                      for state, label, has_data in zip(tiles["state"], labels, tiles["has_data"])]

    fig = go.Figure()
    for has_data, group in tiles.groupby("has_data"):
        marker = dict(symbol="square", size=35, color="#e8eff7", line=dict(color="white", width=1))
        text_color = "#3e4942"
        if has_data:
            marker.update(
                color=group["value"], colorscale=[[0, "#b6e5d5"], [.5, "#55ae94"], [1, "#006947"]],
                cmin=0, cmax=max(group["value"].max(), 1), showscale=True,
                colorbar=dict(thickness=10, len=.75, tickprefix="R$ " if metric == "Revenue" else ""),
            )
            text_color = ["white" if value >= .70 * marker["cmax"] else "#102f27"
                          for value in group["value"]]
        fig.add_trace(go.Scatter(
            x=group["x"], y=group["y"], text=group["state"], customdata=group["hover"],
            mode="markers+text", marker=marker, textfont=dict(color=text_color, size=10),
            hovertemplate="%{customdata}<extra></extra>", showlegend=False,
        ))
    fig.update_xaxes(visible=False, range=[-.65, 8.05], constrain="domain")
    fig.update_yaxes(visible=False, range=[-5.6, .65], scaleanchor="x", scaleratio=1)
    return fig


def render(report: Report) -> pd.DataFrame:
    page_heading("Geographic Distribution & Regional Sales", "Orders, customers and revenue across the Brazilian demo market.")
    all_orders = report.snapshot.orders
    region_slot, state_slot, metric_slot = st.columns([1, 1, 1.5])
    with region_slot:
        region = st.selectbox(
            "Region", ["All regions", *sorted(all_orders["region"].unique())], key="geo_region",
            on_change=lambda: st.session_state.update(geo_state="All states"),
        )
    eligible = all_orders if region == "All regions" else all_orders.loc[all_orders["region"].eq(region)]
    with state_slot:
        state = st.selectbox("State", ["All states", *sorted(eligible["state"].unique())], key="geo_state")
    with metric_slot:
        metric = st.segmented_control("Map metric", list(MEASURES), default="Revenue", selection_mode="single")
    locations = eligible if state == "All states" else eligible.loc[eligible["state"].eq(state)]
    allowed_states = locations["state"].unique()
    orders = report.orders()
    orders = orders.loc[orders["state"].isin(allowed_states)]
    states = geography_breakdown(orders, ["state"])
    metros = geography_breakdown(orders, ["region", "state", "city"])
    if states.empty:
        st.info("No sales match these dates and locations.")
        return metros

    previous = report.orders(previous=True)
    previous = geography_breakdown(previous.loc[previous["state"].isin(allowed_states)], ["state"])
    top = states.iloc[0]
    high_aov = states.loc[states["aov_cents"].idxmax()]
    growth = states.set_index("state")["customers"].pipe(percent_change, previous.set_index("state")["customers"])
    best_growth = growth.dropna().nlargest(1)
    kpis(
        KPI("Top performing state", top["state"], "location_on",
            f"{money(top['revenue_cents'])} · {percent(top['share'])} of regional scope"),
        KPI("Highest state AOV", money(high_aov["aov_cents"], 2), "price_check", high_aov["state"]),
        KPI("Customer growth leader", best_growth.index[0] if not best_growth.empty else "—", "trending_up",
            f"{best_growth.iloc[0]:+.1f}% vs {report.scope.comparison.lower()}" if not best_growth.empty else "Comparison unavailable"),
        KPI("States with sales", number(len(states)), "hub", f"{len(metros)} active metro clusters"),
    )

    spatial, ranking = st.columns([7, 5])
    with spatial, panel("geography_distribution", f"Brazilian {metric or 'Revenue'} by State",
                        "State tile map · schematic geography"):
        charts.plot(cartogram(states, metric or "Revenue"), "geography_distribution", 341)
    with ranking, panel("geography_metros", "Top Metro Clusters", "Ranked by merchandise revenue"):
        top_metros = metros.head(10)
        fig = charts.horizontal(
            top_metros["city"] + " · " + top_metros["state"], top_metros["revenue_cents"] / 100,
            custom=top_metros["customers"],
            hover="%{y}<br>R$ %{x:,.2f} · %{customdata:,} customers<extra></extra>", color=charts.MINT,
        )
        fig.update_xaxes(tickprefix="R$ ")
        charts.plot(fig, "geography_metros", 341)

    with panel("geography_ledger", "Regional Sales & Customer Breakdown", "Metro-level results for the selected locations"):
        query = st.text_input("Search cities, states or regions", placeholder="e.g. São Paulo or SP")
        display = search_rows(metros, query, ["region", "state", "city"])
        download(display, "geography")
        table(display)
    return display


if __name__ == "__main__":
    run_view(render, "geography")
