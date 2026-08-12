"""Small deterministic locale formatting helpers shared by renderers."""

from __future__ import annotations

from datetime import date, datetime


def format_value(value: object, *, language: str, currency: str | None = None) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y" if language.startswith("pt") else "%Y-%m-%d")
    if currency and isinstance(value, (int, float)):
        return f"{currency} {format_value(float(value), language=language)}"
    if isinstance(value, float):
        rendered = f"{value:,.2f}"
        return rendered.replace(",", "X").replace(".", ",").replace("X", ".") if language.startswith("pt") else rendered
    return str(value)
