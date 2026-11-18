import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

GREEN = "#006947"
MINT = "#00855b"
SAGE = "#71bca3"
SLATE = "#435763"
AMBER = "#9e4300"
ORANGE = "#f6a575"
GRID = "#e8eff7"
PALETTE = [GREEN, SAGE, SLATE, ORANGE, "#a4d9c5", "#7b92aa", "#d4ac80"]


def plot(fig: go.Figure, key: str, height: int = 300, *, bottom_margin: int = 8) -> None:
    fig.update_layout(
        template="none",
        height=height,
        font=dict(family="Inter, sans-serif", size=11, color="#3e4942"),
        margin=dict(l=8, r=8, t=12, b=bottom_margin),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#2a3137", font_color="white"),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
    )
    fig.update_xaxes(automargin=True, gridcolor=GRID, zeroline=False)
    fig.update_yaxes(automargin=True, gridcolor=GRID, zeroline=False)
    st.plotly_chart(
        fig, key=f"chart_{key}", theme=None, width="stretch", config={"displaylogo": False, "scrollZoom": False}
    )


def dual_axis(
    x,
    primary,
    secondary,
    *,
    primary_name: str,
    secondary_name: str,
    left_format: str = ",.0f",
    right_format: str = ",.0f",
    left_prefix: str = "",
    right_prefix: str = "",
    range_slider: bool = False,
) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=x,
            y=primary,
            name=primary_name,
            line=dict(color=GREEN, width=3),
            fill="tozeroy",
            fillcolor="rgba(0,133,91,0.11)",
            connectgaps=False,
            hovertemplate=f"{left_prefix}%{{y:{left_format}}}",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=secondary,
            name=secondary_name,
            mode="lines+markers",
            connectgaps=False,
            line=dict(color=AMBER, width=2),
            marker=dict(size=4),
            hovertemplate=f"{right_prefix}%{{y:{right_format}}}",
        ),
        secondary_y=True,
    )
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(tickprefix=left_prefix, tickformat=left_format, rangemode="tozero", secondary_y=False)
    fig.update_yaxes(
        tickprefix=right_prefix, tickformat=right_format, showgrid=False, rangemode="tozero", secondary_y=True
    )
    fig.update_xaxes(showgrid=False, rangeslider=dict(visible=range_slider, thickness=0.12), type="date")
    return fig


def horizontal(labels, values, *, custom=None, hover=None, color=GREEN, ticksuffix="") -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=color,
            customdata=custom,
            hovertemplate=hover or "%{y}<br>%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(ticksuffix=ticksuffix)
    return fig


def sales_composition(
    labels: pd.Series,
    cents: pd.Series,
    currency: str,
    *,
    treemap: bool = False,
) -> go.Figure | None:
    cents = cents.dropna()
    if cents.empty or not cents.ne(0).any():
        return None
    labels = labels.loc[cents.index]
    hover = f"%{{label}}<br>{currency} %{{value:,.2f}}<br>%{{customdata:.1f}}% of net sales<extra></extra>"
    if cents.lt(0).any():
        # Areas cannot encode signed amounts. Retain every amount in a signed bar chart.
        fig = horizontal(labels, cents / 100, hover=f"%{{y}}<br>{currency} %{{x:,.2f}}<extra></extra>")
        fig.update_xaxes(tickprefix=f"{currency} ")
        return fig

    positive = cents.gt(0)
    values = cents.loc[positive] / 100
    names = labels.loc[positive]
    share = (100 * values / values.sum()).tolist()
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(values))]
    common = dict(
        labels=names.tolist(),
        values=values.tolist(),
        customdata=share,
        hovertemplate=hover,
        sort=False,
        marker=dict(colors=colors, line=dict(color="white", width=2)),
    )
    if treemap:
        fig = go.Figure(
            go.Treemap(
                **common,
                parents=[""] * len(names),
                pathbar=dict(visible=False),
                texttemplate="%{label}<br>%{customdata:.1f}%",
                tiling=dict(pad=3),
            )
        )
        fig.update_layout(uniformtext=dict(minsize=10, mode="hide"))
    else:
        fig = go.Figure(
            go.Pie(
                **common,
                texttemplate="%{label}<br>%{customdata:.1f}%",
                textposition="auto",
            )
        )
    return fig
