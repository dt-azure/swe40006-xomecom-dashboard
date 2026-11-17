import pandas as pd
import streamlit as st

from dashboard.data.analytics import currency_columns

FORMATS = {
    "share": ("Revenue share", "%.1f%%"),
    "growth": ("Revenue growth", "%+.1f%%"),
    "conversion": ("Conversion rate", "%.2f%%"),
    "fulfilment": ("Fulfilment rate", "%.1f%%"),
    "on_time_rate": ("On-time rate", "%.1f%%"),
    "basket_depth": ("Units / order", "%.2f"),
    "variance_hours": ("Variance (h)", "%+.1f"),
    "transit_days": ("Transit (days)", "%.1f"),
    "review_score": ("Review score", "%d"),
    "duration_seconds": ("Duration (s)", "%d"),
}


def download(frame: pd.DataFrame, name: str, label: str = "Download CSV") -> None:
    st.download_button(
        label, currency_columns(frame).to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S"),
        file_name=f"commercepulse-{name}.csv", mime="text/csv", icon=":material/download:",
        key=f"download_{name}_{label}", type="primary", on_click="ignore", disabled=frame.empty,
        width="stretch" if label == "Export Report" else "content",
    )


def table(frame: pd.DataFrame, height: int = 330) -> None:
    if frame.empty:
        st.info("No records match the current filters.")
        return
    display = currency_columns(frame)
    config = {column: column.replace("_", " ").capitalize() for column in display}
    config.update({
        column: st.column_config.NumberColumn(f"{column[:-4].replace('_', ' ').capitalize()} (BRL)",
                                              format="R$ %.2f")
        for column in display if column.endswith("_brl")
    })
    config.update({
        column: st.column_config.NumberColumn(label, format=fmt)
        for column, (label, fmt) in FORMATS.items() if column in display
    })
    for column in display.select_dtypes(include=["datetime"]):
        if column == "date":
            config[column] = st.column_config.DateColumn("Order date", format="MMM D, YYYY")
        else:
            config[column] = st.column_config.DatetimeColumn(
                column.replace("_", " ").capitalize(), format="MMM D, YYYY HH:mm"
            )
    st.dataframe(display, column_config=config, hide_index=True, height=height, width="stretch")
