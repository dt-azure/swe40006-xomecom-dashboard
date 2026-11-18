"""Date-only velocity card for Gold sources without transaction timestamps."""
from html import escape

import pandas as pd
import streamlit as st

from dashboard.data.analytics import weekday_sales_split, weekday_velocity

from .formatting import money, number, percent
from .layout import icon

HOUR_NOTE = "Hourly breakdown unavailable: Gold contains order dates but no transaction timestamps."


def velocity_card(lines: pd.DataFrame, currency: str) -> None:
    velocity = weekday_velocity(lines)
    weekday_cents, weekend_cents = weekday_sales_split(lines)
    with st.container(key="cp_panel_sales_velocity", border=True):
        st.html(f"""
            <div class="cp-velocity">
                <div class="cp-velocity-header">
                    <h3>Weekday vs Weekend Velocity</h3>
                    <span class="cp-velocity-help">
                        <button type="button" aria-label="About order velocity"
                                aria-describedby="cp-velocity-tooltip">{icon("info")}</button>
                        <span id="cp-velocity-tooltip" role="tooltip">Share of distinct orders on each day
                        of the week, within the selected date range and Gold data scope.</span>
                    </span>
                </div>
                <p class="cp-velocity-subtitle">Distinct orders by day of week</p>
                <table aria-label="Distinct order distribution by weekday">
                    <thead><tr><th scope="col">Day</th><th scope="col">Orders</th>
                    <th scope="col">Share of orders</th></tr></thead>
                    <tbody>{_day_rows(velocity)}</tbody>
                </table>
                {_share_bar(weekday_cents, weekend_cents, currency)}
                <p class="cp-velocity-note">{HOUR_NOTE}</p>
            </div>
        """)


def _day_rows(velocity: pd.DataFrame) -> str:
    peak = velocity["share"].max()
    rows = []
    for index, (day, row) in enumerate(velocity.iterrows()):
        weekend = index >= 5
        count = number(row["orders"])
        share = percent(row["share"])
        level = "low"
        if pd.notna(row["share"]) and row["share"] > 0:
            ratio = row["share"] / peak
            if ratio >= .9:
                level = "peak" if weekend else "high"
            elif ratio >= .6:
                level = "surge" if weekend else "moderate"
        rows.append(
            f'<tr class="{"weekend" if weekend else "weekday"}"><th scope="row">{day}{" ★" if weekend else ""}</th>'
            f'<td>{count}</td><td><span class="cp-velocity-cell {level}" '
            f'title="{day}: {count} distinct orders · {share} of selected orders">{share}</span></td></tr>'
        )
    return "".join(rows)


def _share_bar(weekday: int, weekend: int, currency: str) -> str:
    total = weekday + weekend
    heading = '<div class="cp-velocity-share-heading"><strong>Weekend Revenue Share</strong>'
    if total <= 0 or min(weekday, weekend) < 0:
        reason = "net sales are zero" if total == 0 else "one or both net sales amounts are negative"
        return (f'{heading}</div><p class="cp-velocity-note">Share unavailable: {reason}. '
                f'Mon–Fri {money(weekday, 2, currency=currency)} · '
                f'Sat–Sun {money(weekend, 2, currency=currency)}.</p>')

    weekday_share = 100 * weekday / total
    weekday_label = round(weekday_share, 1)
    weekend_label = 100 - weekday_label
    weekdays = escape(f"Mon–Fri: {percent(weekday_label)} · {money(weekday, 2, currency=currency)}")
    weekends = escape(f"Sat–Sun: {percent(weekend_label)} · {money(weekend, 2, currency=currency)}")
    return f"""
        {heading}<strong>{percent(weekend_label)}</strong></div>
        <div class="cp-velocity-split" role="img" aria-label="{weekdays}; {weekends}">
            <span class="weekdays" style="width:{weekday_share:.8f}%" title="{weekdays}"></span>
            <span class="weekends" style="width:{100 - weekday_share:.8f}%" title="{weekends}"></span>
        </div>
        <div class="cp-velocity-legend">
            <span class="weekdays">Mon–Fri: {percent(weekday_label)}</span>
            <span class="weekends">Sat–Sun: {percent(weekend_label)}</span>
        </div>
    """
