import pandas as pd


def money(cents, decimals: int = 0) -> str:
    return f"R$ {cents / 100:,.{decimals}f}" if pd.notna(cents) else "—"


def number(value, decimals: int = 0, suffix: str = "") -> str:
    return f"{value:,.{decimals}f}{suffix}" if pd.notna(value) else "—"


def percent(value, decimals: int = 1) -> str:
    return number(value, decimals, "%")
