import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number
from dashboard.components.layout import KPI, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, mart_table, table
from dashboard.data.analytics import (
    breakdown, discount_performance, divide, percent_change, search_rows, top_profitable_products,
)


def select_catalog(lines: pd.DataFrame, category: str, query: str) -> pd.DataFrame:
    if category != "All categories":
        lines = lines.loc[lines["category"].eq(category)]
    return search_rows(lines, query, ["category", "subcategory", "sku", "product"])


def render(report: Report) -> pd.DataFrame:
    currency = report.currency
    page_heading("Category Performance & Merchandising", f"Net sales, discount impact and profit by catalog · {currency}")
    category_slot, search = st.columns([1, 2])
    with category_slot:
        category = st.selectbox("Category", ["All categories", *sorted(report.snapshot.lines["category"].unique())],
                                key="catalog_category")
    with search:
        query = st.text_input("Search catalog", placeholder="Category, subcategory, product or SKU")
    lines = select_catalog(report.lines(), category, query)
    catalog = breakdown(lines, ["category"])
    if catalog.empty:
        st.info("No sales lines match these dates and catalog filters.")
        return catalog

    previous = breakdown(select_catalog(report.lines(previous=True), category, query), ["category"])
    catalog["growth"] = percent_change(catalog["net_sales_cents"],
                                       catalog["category"].map(previous.set_index("category")["net_sales_cents"]))
    top, volume = catalog.iloc[0], catalog.loc[catalog["orders"].idxmax()]
    growth = catalog.dropna(subset=["growth"]).nlargest(1, "growth")
    leader = growth.iloc[0] if not growth.empty else None
    kpis(
        KPI("Active categories", number(len(catalog)), "category", f"{lines['sku'].nunique():,} known selling SKUs"),
        KPI("Top category by net sales", money(top["net_sales_cents"], currency=currency),
            "workspace_premium", top["category"]),
        KPI("Highest order volume", number(volume["orders"]), "shopping_bag", volume["category"]),
        KPI("Net sales growth leader", leader["category"] if leader is not None else "—", "trending_up",
            f"{leader['growth']:+.1f}% vs {report.scope.comparison.lower()}" if leader is not None else "Comparison unavailable"),
    )
    share, matrix = st.columns([5, 7])
    with share, panel("category_mix", "Net Sales by Category", "Share of net sales in the filtered catalog"):
        fig = charts.sales_composition(catalog["category"], catalog["net_sales_cents"], currency)
        if fig is None:
            st.info("Sales share is unavailable when every category has zero net sales.")
        else:
            if catalog["net_sales_cents"].lt(0).any():
                st.caption("Negative net sales are shown on a signed scale.")
            charts.plot(fig, "category_mix", 322, bottom_margin=32)
    with matrix, panel("category_matrix", "Category Volume vs. Net Sales",
                       "Bubble size shows units sold. Guides mark the category medians."):
        fig = go.Figure(go.Scatter(
            x=catalog["orders"], y=catalog["net_sales_cents"] / 100, text=catalog["category"],
            mode="markers", customdata=catalog["units"],
            marker=dict(size=14 + 22 * (catalog["units"] / catalog["units"].clip(lower=1).max()) ** .5,
                        color=charts.MINT),
            hovertemplate=f"%{{text}}<br>%{{x:,}} orders · %{{customdata:,}} units<br>{currency} %{{y:,.2f}}<extra></extra>",
        ))
        fig.add_vline(x=catalog["orders"].median(), line_dash="dot", line_color=charts.SAGE)
        fig.add_hline(y=catalog["net_sales_cents"].median() / 100, line_dash="dot", line_color=charts.SAGE)
        fig.update_xaxes(title="Distinct orders", rangemode="tozero")
        fig.update_yaxes(tickprefix=f"{currency} ", rangemode="tozero")
        charts.plot(fig, "category_matrix", 294)

    with panel("category_catalog", "Merchandising & Catalog Breakdown",
               "Orders may appear in multiple categories. Net sales and profit add across categories."):
        display = breakdown(lines, ["category", "subcategory"])
        download(display, "categories", currency=currency)
        table(display, height=290, currency=currency)
    discount_analysis(lines, currency)
    if not query:
        discount = report.mart("mart_discount_impact")
        if category != "All categories":
            discount = discount.loc[discount["category"].fillna("Unknown").eq(category)]
        mart_table(report, "mart_discount_impact", "Monthly Discount Impact", [
            "order_month", "category", "discount_band", "is_sample", "order_count", "avg_discount", "gross_sales",
            "discount_amount", "net_sales", "profit", "profit_margin", "loss_line_share",
            "first_order_date", "last_order_date",
        ], discount)
    return display


def discount_analysis(lines: pd.DataFrame, currency: str) -> None:
    with st.expander("Discounts and Profitability"):
        st.caption("Observed results by discount band. These transactions do not establish what "
                   "would have sold at a different discount.")
        bands = discount_performance(lines)
        bands["discount_band"] = pd.Categorical(
            bands["discount_band"], categories=["none", "low", "medium", "high"], ordered=True,
        )
        band_totals = bands.groupby("discount_band", observed=True)[["profit_cents", "net_sales_cents"]].sum()
        margin = 100 * divide(band_totals["profit_cents"], band_totals["net_sales_cents"])
        fig = charts.horizontal(margin.index, margin, ticksuffix="%",
                                hover="%{y}<br>Profit margin %{x:.1f}%<extra></extra>")
        charts.plot(fig, "discount_profitability", 205)
        category_avg = lines.groupby("category", as_index=False)["discount"].mean()
        category_avg["avg_discount_pct"] = category_avg.pop("discount") * 100
        st.markdown("**Average sales-line discount by category**")
        table(category_avg, height=220, currency=currency)
        st.markdown("**Profitability by category and discount band**")
        display = bands.sort_values(["category", "discount_band"])[[
            "category", "discount_band", "avg_discount_pct", "orders", "net_sales_cents", "profit_cents", "margin",
        ]]
        table(display, height=250, currency=currency)
        download(display, "discount-profitability", currency=currency)
        st.markdown("**Top three profitable products per category**")
        products = top_profitable_products(lines)[["category", "product", "net_sales_cents", "profit_cents", "margin"]]
        table(products, height=250, currency=currency)
        download(products, "profitable-products", currency=currency)


if __name__ == "__main__":
    run_view(render, "categories")
