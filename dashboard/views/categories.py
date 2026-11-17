import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number, percent
from dashboard.components.layout import KPI, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, table
from dashboard.data.analytics import catalog_breakdown, percent_change, purchased_lines, search_rows


def filter_catalog(lines: pd.DataFrame, department: str, query: str) -> pd.DataFrame:
    if department != "All departments":
        lines = lines.loc[lines["department"].eq(department)]
    return search_rows(lines, query, ["category", "department", "sku", "product"])


def render(report: Report) -> pd.DataFrame:
    page_heading("Category Performance & Merchandising", "Revenue contribution and order volume by product hierarchy.")
    category_filter, search = st.columns([1, 2])
    departments = sorted(report.snapshot.items["department"].unique())
    with category_filter:
        department = st.selectbox("Department", ["All departments", *departments], key="catalog_department")
    with search:
        query = st.text_input("Search catalog", placeholder="Category, product or SKU", key="catalog_search")

    scoped_lines = purchased_lines(report.snapshot, report.orders())
    lines = filter_catalog(scoped_lines, department, query)
    catalog = catalog_breakdown(lines)
    if catalog.empty:
        st.info("No purchased items match these dates and catalog filters.")
        return catalog

    previous = filter_catalog(purchased_lines(report.snapshot, report.orders(previous=True)), department, query)
    previous = catalog_breakdown(previous).set_index("category")["revenue_cents"]
    catalog["growth"] = percent_change(catalog["revenue_cents"], catalog["category"].map(previous))
    top = catalog.iloc[0]
    volume = catalog.loc[catalog["orders"].idxmax()]
    growth = catalog.dropna(subset=["growth"]).nlargest(1, "growth")
    growth_label = growth.iloc[0]["category"] if not growth.empty else "—"
    growth_note = f"{growth.iloc[0]['growth']:+.1f}% vs {report.scope.comparison.lower()}" if not growth.empty else "Comparison unavailable"
    kpis(
        KPI("Active categories", number(len(catalog)), "category", f"{lines['sku'].nunique()} selling SKUs"),
        KPI("Top grossing category", money(top["revenue_cents"]), "workspace_premium", top["category"]),
        KPI("Highest order volume", number(volume["orders"]), "shopping_bag", volume["category"]),
        KPI("Revenue growth leader", growth_label, "trending_up", growth_note),
    )

    share, matrix = st.columns([5, 7])
    with share, panel("category_mix", "Revenue Share by Hierarchy", "Contribution across the filtered catalog"):
        donut, ranking = st.columns([3, 4], gap="small")
        palette = [charts.PALETTE[index % len(charts.PALETTE)] for index in range(len(catalog))]
        with donut:
            fig = charts.donut(catalog["category"], catalog["revenue_cents"] / 100, colors=palette)
            fig.update_traces(hovertemplate="%{label}<br>R$ %{value:,.2f} · %{percent}<extra></extra>")
            fig.add_annotation(x=.5, y=.5, text=f"<b>{len(catalog)}</b><br>categories", showarrow=False)
            charts.plot(fig, "category_mix", 252)
        with ranking:
            st.html('<div class="cp-ranking">' + "".join(
                ranking_row(row.category, percent(row.share), color)
                for row, color in zip(catalog.itertuples(), palette)
            ) + "</div>")
        st.caption(f"{money(lines['revenue_cents'].sum(), 2)} in merchandise revenue")
    with matrix, panel("category_matrix", "Category Volume vs. Revenue Matrix",
                       "Bubble size reflects units sold. Guides mark the category medians."):
        fig = go.Figure(go.Scatter(
            x=catalog["orders"], y=catalog["revenue_cents"] / 100, text=catalog["category"],
            mode="markers", customdata=catalog["units"],
            marker=dict(
                size=12 + 24 * (catalog["units"] / catalog["units"].max()) ** .5,
                color=palette, opacity=.85, line=dict(color="white", width=1),
            ),
            hovertemplate="%{text}<br>%{x:,} orders · %{customdata:,} units<br>R$ %{y:,.2f}<extra></extra>",
        ))
        fig.add_vline(x=catalog["orders"].median(), line_dash="dot", line_color=charts.SAGE)
        fig.add_hline(y=catalog["revenue_cents"].median() / 100, line_dash="dot", line_color=charts.SAGE)
        fig.update_xaxes(title="Order count", rangemode="tozero")
        fig.update_yaxes(tickprefix="R$ ", rangemode="tozero")
        charts.plot(fig, "category_matrix", 283)

    with panel("category_catalog", "Merchandising & Catalog Breakdown",
               "Orders can contribute to multiple categories. Revenue adds across categories."):
        display = catalog[[
            "category", "department", "active_skus", "revenue_cents", "share", "orders", "units",
            "basket_depth", "growth",
        ]]
        download(display, "categories")
        table(display, height=290)
    return display


def ranking_row(label: str, value: str, color: str) -> str:
    from html import escape

    return (f'<div class="cp-rank-row"><i style="background:{color}"></i>'
            f'<span>{escape(label)}</span><strong>{escape(value)}</strong></div>')


if __name__ == "__main__":
    run_view(render, "categories")
