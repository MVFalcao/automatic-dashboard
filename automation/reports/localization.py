"""Deterministic en-US and pt-BR formatting shared by all renderers."""

from __future__ import annotations

from datetime import date, datetime

from babel.dates import format_date, format_datetime
from babel.numbers import format_currency, format_decimal


def normalized_locale(language: str) -> str:
    return "pt_BR" if language.casefold().startswith("pt") else "en_US"


def format_value(value: object, *, language: str, currency: str | None = None) -> str:
    locale = normalized_locale(language)
    if isinstance(value, datetime):
        return format_datetime(value, format="short", locale=locale)
    if isinstance(value, date):
        return format_date(value, format="short", locale=locale)
    if currency and isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_currency(value, currency, locale=locale)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_decimal(value, format="#,##0.00" if isinstance(value, float) else "#,##0", locale=locale)
    if value is None:
        return ""
    return str(value)


def excel_number_format(*, language: str, currency: str | None = None, date_only: bool = False, datetime_value: bool = False) -> str:
    if datetime_value:
        return "dd/mm/yyyy hh:mm" if language.startswith("pt") else "mm/dd/yyyy hh:mm"
    if date_only:
        return "dd/mm/yyyy" if language.startswith("pt") else "mm/dd/yyyy"
    number = "#.##0,00" if language.startswith("pt") else "#,##0.00"
    return f'[$${currency}] {number}' if currency else number
