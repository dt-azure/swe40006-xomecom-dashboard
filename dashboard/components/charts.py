import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

GREEN = "#006947"
MINT = "#00855b"
SAGE = "#71bca3"
SLATE = "#435763"
AMBER = "#9e4300"
ORANGE = "#f6a575"
RED = "#ba1a1a"
GRID = "#e8eff7"
PALETTE = [GREEN, SAGE, SLATE, ORANGE, "#a4d9c5", "#7b92aa", "#d4ac80"]
STATUS_COLORS = {"Early": SAGE, "On time": GREEN, "Delayed": AMBER}


def plot(fig: go.Figure, key: str, height: int = 300) -> None:
    fig.update_layout(
        template="none", height=height, font=dict(family="Inter, sans-serif", size=11, color="#3e4942"),
        margin=dict(l=8, r=8, t=12, b=8), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(bgcolor="#2a3137", font_color="white"),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
    )
    fig.update_xaxes(automargin=True, gridcolor=GRID, zeroline=False)
    fig.update_yaxes(automargin=True, gridcolor=GRID, zeroline=False)
    st.plotly_chart(fig, key=f"chart_{key}", theme=None, width="stretch",
                    config={"displaylogo": False, "scrollZoom": False})


def dual_axis(
    x, primary, secondary, *, primary_name: str, secondary_name: str,
    left_format: str = ",.0f", right_format: str = ",.0f",
    left_prefix: str = "R$ ", right_suffix: str = "", bars: bool = False, range_slider: bool = False,
) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if bars:
        fig.add_trace(go.Bar(x=x, y=primary, name=primary_name, marker_color=SLATE,
                            hovertemplate=f"{left_prefix}%{{y:{left_format}}}"), secondary_y=False)
    else:
        fig.add_trace(go.Scatter(
            x=x, y=primary, name=primary_name, line=dict(color=GREEN, width=3),
            fill="tozeroy", fillcolor="rgba(0,133,91,0.11)",
            hovertemplate=f"{left_prefix}%{{y:{left_format}}}",
        ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=x, y=secondary, name=secondary_name, mode="lines+markers",
        line=dict(color=GREEN if bars else AMBER, width=2), marker=dict(size=4),
        hovertemplate=f"%{{y:{right_format}}}{right_suffix}",
    ), secondary_y=True)
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(tickprefix=left_prefix, tickformat=left_format, rangemode="tozero", secondary_y=False)
    fig.update_yaxes(ticksuffix=right_suffix, tickformat=right_format, showgrid=False,
                     rangemode="tozero", secondary_y=True)
    fig.update_xaxes(showgrid=False, rangeslider=dict(visible=range_slider, thickness=.12), type="date")
    return fig


def horizontal(labels, values, *, custom=None, hover=None, color=GREEN, ticksuffix="") -> go.Figure:
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", marker_color=color, customdata=custom,
        hovertemplate=hover or "%{y}<br>%{x:,.0f}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(ticksuffix=ticksuffix)
    return fig


def donut(labels, values, colors=PALETTE) -> go.Figure:
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=.66, sort=False,
        marker=dict(colors=colors, line=dict(color="white", width=2)),
        textinfo="none", hovertemplate="%{label}<br>%{value:,.2f} · %{percent}<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    return fig
