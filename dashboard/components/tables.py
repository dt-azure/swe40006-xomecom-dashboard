import pandas as pd
import streamlit as st
from pandas.api.types import is_string_dtype

from dashboard.data.analytics import currency_columns

FORMATS = {
    "share": ("Net sales share", "%.1f%%"),
    "growth": ("Net sales growth", "%+.1f%%"),
    "basket_depth": ("Units / order", "%.2f"),
    "margin": ("Profit margin", "%.1f%%"),
}
MART_AMOUNTS = {"gross_sales", "net_sales", "profit", "discount_amount", "median_order_value", "prev_year_net_sales"}
MART_RATES = {"avg_discount", "profit_margin", "retention_rate", "loss_line_share", "net_sales_yoy_change"}


def csv_text(frame: pd.DataFrame, currency: str) -> str:
    export = currency_columns(frame, currency)
    for column in export.columns:
        if is_string_dtype(export[column]):
            values = export[column]
            # Warehouse strings can become formulas when opened in a spreadsheet.
            export[column] = values.map(
                lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(
                    ("=", "+", "-", "@")
                ) else value
            )
    return export.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S")


def download(frame: pd.DataFrame, name: str, label: str = "Download CSV", *, currency: str = "USD") -> None:
    st.download_button(
        label, csv_text(frame, currency),
        file_name=f"commercepulse-{name}.csv", mime="text/csv", icon=":material/download:",
        key=f"download_{name}_{label}", type="primary", on_click="ignore", disabled=frame.empty,
        width="stretch" if label == "Export Report" else "content",
    )


def table(frame: pd.DataFrame, height: int = 330, *, currency: str = "USD") -> None:
    if frame.empty:
        st.info("No records match the current filters.")
        return
    display = currency_columns(frame, currency)
    config = {column: column.replace("_", " ").capitalize() for column in display}
    config.update({
        column: st.column_config.NumberColumn(f"{column.removesuffix('_' + currency.lower()).replace('_', ' ').capitalize()} ({currency})",
                                              format="%.2f")
        for column in display if column.endswith("_" + currency.lower()) or column in MART_AMOUNTS
    })
    config.update({
        column: st.column_config.NumberColumn(label, format=fmt)
        for column, (label, fmt) in FORMATS.items() if column in display
    })
    config.update({
        column: st.column_config.NumberColumn(column.removesuffix("_pct").replace("_", " ").capitalize(),
                                              format="%.1f%%")
        for column in display if column.endswith("_pct")
    })
    for column in display.select_dtypes(include=["datetime"]):
        config[column] = st.column_config.DateColumn(config[column], format="MMM D, YYYY")
    st.dataframe(display, column_config=config, hide_index=True, height=height, width="stretch")


def mart_table(report, name: str, title: str, columns: list[str], frame: pd.DataFrame | None = None) -> None:
    frame = report.mart(name) if frame is None else frame
    with st.expander(title):
        st.caption("Gold mart rows with order-date coverage entirely inside the selected dates. "
                   "Historical and sample rows retain their original grains.")
        display = frame[columns].copy()
        rates = [column for column in columns if column in MART_RATES]
        display[rates] = display[rates] * 100
        display = display.rename(columns={
            **{column: f"{column}_{report.currency.lower()}" for column in columns if column in MART_AMOUNTS},
            **{column: f"{column}_pct" for column in rates},
        })
        table(display, height=270, currency=report.currency)
        download(display, name, currency=report.currency)
