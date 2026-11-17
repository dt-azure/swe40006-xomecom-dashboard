import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.formatting import money, number, percent
from dashboard.components.layout import KPI, kpis, page_heading, panel
from dashboard.components.report import Report, run_view
from dashboard.components.tables import download, mart_table, table
from dashboard.data.analytics import breakdown, cross_region_customers, monthly_growth, percent_change, sample_scope, search_rows

MEASURES = {"Net sales": "net_sales_cents", "Orders": "orders", "Customers": "customers"}


def by_location(lines: pd.DataFrame, market: str, country: str) -> pd.DataFrame:
    if market != "All markets":
        lines = lines.loc[lines["market"].eq(market)]
    if country != "All countries":
        lines = lines.loc[lines["country"].eq(country)]
    return lines


def render(report: Report) -> pd.DataFrame:
    currency = report.currency
    page_heading("Geographic Distribution & Regional Sales", f"Gold markets, countries and cities · {currency}")
    market_slot, country_slot, metric_slot = st.columns([1, 1, 1.5])
    all_lines = report.snapshot.lines
    with market_slot:
        market = st.selectbox(
            "Market", ["All markets", *sorted(all_lines["market"].unique())], key="geo_market",
            on_change=lambda: st.session_state.pop("geo_country", None),
        )
    eligible = by_location(all_lines, market, "All countries")
    with country_slot:
        country = st.selectbox("Country", ["All countries", *sorted(eligible["country"].unique())], key="geo_country")
    with metric_slot:
        metric = st.segmented_control("Distribution metric", list(MEASURES), default="Net sales",
                                      selection_mode="single") or "Net sales"
    lines = by_location(report.lines(), market, country)
    countries = breakdown(lines, ["country"])
    cities = breakdown(lines, ["market", "region", "country", "state", "city"])
    if cities.empty:
        st.info("No sales match these dates and locations.")
        return cities

    previous = breakdown(by_location(report.lines(previous=True), market, country), ["country"])
    known = countries.loc[countries["country"].ne("Unknown")]
    top = known.iloc[0] if not known.empty else countries.iloc[0]
    high_aov = known.loc[known["aov_cents"].idxmax()] if not known.empty else top
    growth = known.set_index("country")["customers"].pipe(
        percent_change, previous.set_index("country")["customers"],
    ).dropna().nlargest(1)
    kpis(
        KPI("Top market country", top["country"], "location_on",
            f"{money(top['net_sales_cents'], currency=currency)} · {percent(top['share'])} of scoped sales"),
        KPI("Highest country AOV", money(high_aov["aov_cents"], 2, currency=currency), "price_check", high_aov["country"]),
        KPI("Customer growth leader", growth.index[0] if not growth.empty else "—", "trending_up",
            f"{growth.iloc[0]:+.1f}% vs {report.scope.comparison.lower()}" if not growth.empty else "Comparison unavailable"),
        KPI("Countries with sales", number(len(known)), "hub",
            f"{cities.loc[cities['city'].ne('Unknown')].shape[0]:,} known city groups"),
    )

    distribution, metro = st.columns([7, 5])
    dimension = "country" if market != "All markets" else "market"
    location_scope = countries if dimension == "country" else breakdown(lines, ["market"])
    with distribution, panel("geography_distribution", f"{metric.title()} by {dimension.title()}"):
        measure = MEASURES[metric]
        if metric == "Net sales" and dimension == "market":
            fig = charts.sales_composition(location_scope[dimension], location_scope[measure], currency, treemap=True)
            if fig is None:
                st.info("Sales share is unavailable when every market has zero net sales.")
            elif location_scope[measure].lt(0).any():
                st.caption("Negative net sales are shown on a signed scale.")
        else:
            ranked = location_scope.nlargest(15 if dimension == "country" else 12, measure)
            values = ranked[measure] / 100 if metric == "Net sales" else ranked[measure]
            prefix = f"{currency} " if metric == "Net sales" else ""
            fmt = ",.2f" if metric == "Net sales" else ",.0f"
            fig = charts.horizontal(ranked[dimension], values,
                                    hover=f"%{{y}}<br>{prefix}%{{x:{fmt}}}<extra></extra>")
            fig.update_xaxes(tickprefix=prefix)
        if fig is not None:
            charts.plot(fig, "geography_distribution", 331)
    with metro, panel("geography_metros", "Top Cities", "Ranked by net sales"):
        ranked = cities.loc[cities["city"].ne("Unknown")].head(10)
        fig = charts.horizontal(
            ranked["city"] + " · " + ranked["country"], ranked["net_sales_cents"] / 100,
            custom=ranked["customers"], color=charts.MINT,
            hover=f"%{{y}}<br>{currency} %{{x:,.2f}} · %{{customdata:,}} known customers<extra></extra>",
        )
        fig.update_xaxes(tickprefix=f"{currency} ")
        charts.plot(fig, "geography_metros", 313)

    with panel("geography_ledger", "Regional Sales & Customer Breakdown",
               "Orders and customers may appear in more than one location group."):
        query = st.text_input("Search locations", placeholder="City, state, country, region or market")
        display = search_rows(cities, query, ["city", "state", "country", "region", "market"])
        download(display, "geography", currency=currency)
        table(display, currency=currency)
    market_analysis(report, lines, market, country)
    if country == "All countries" and not query:
        growth_mart = report.mart("mart_market_growth")
        if market != "All markets":
            growth_mart = growth_mart.loc[growth_mart["market"].fillna("Unknown").eq(market)]
        mart_table(report, "mart_market_growth", "Annual Market Growth", [
            "order_year", "market", "region", "is_sample", "order_count", "customer_count",
            "net_sales", "prev_year_net_sales", "net_sales_yoy_change", "profit", "profit_margin",
            "first_order_date", "last_order_date",
        ], growth_mart)
    return display


def market_analysis(report: Report, lines: pd.DataFrame, market: str, country: str) -> None:
    currency = report.currency
    with st.expander("Regional Profitability & Monthly Growth"):
        st.caption(f"{number(cross_region_customers(lines))} known customers purchased in multiple recorded "
                   "market–region pairs within the selected filters.")
        geography = st.segmented_control("Profitability grouping", ["Market", "Region", "Country"],
                                         default="Region") or "Region"
        groups = ["market", "region"] if geography == "Region" else [geography.lower()]
        summary = breakdown(lines, groups)
        if geography == "Country":
            summary = summary.head(15)
        values = summary[[*groups, "net_sales_cents", "profit_cents", "margin", "orders", "customers"]]
        table(values, height=250, currency=currency)
        download(values, "geography-profitability", currency=currency)
        regions = sorted(lines["region"].unique())
        region = st.selectbox("Region for monthly growth", ["All regions", *regions])
        history = by_location(sample_scope(report.snapshot.lines, report.selection), market, country)
        if region != "All regions":
            history = history.loc[history["region"].eq(region)]
        monthly = monthly_growth(history, report.scope)
        st.caption("Monthly growth uses only complete calendar months inside the selected dates. "
                   "Month-over-month and year-over-year changes require an observed comparison month.")
        table(monthly[["date", "net_sales_cents", "prior_net_sales_cents", "growth", "yoy_growth_pct"]], height=225, currency=currency)


if __name__ == "__main__":
    run_view(render, "geography")
