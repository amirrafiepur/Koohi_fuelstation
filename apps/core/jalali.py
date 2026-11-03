"""
Centralized Gregorian <-> Jalali (Persian/Shamsi) date conversion.

Architecture (see project handoff doc, "Convert Application Dates from
Gregorian to Jalali"):
  - The database, all business logic, chronology, and internal date
    comparisons continue to use plain Gregorian datetime.date objects.
    Nothing here ever touches a model field or a stored value.
  - Only the presentation layer (templates, print templates, and the
    two form widgets that let an operator type/pick a date) converts
    to/from Jalali. Every other date-touching module is unaffected.
  - This is the single place that import/use jdatetime, so there is
    exactly one conversion implementation to test and maintain --
    nothing else in the codebase should import jdatetime directly.

Library choice: jdatetime (pure Python, zero dependencies, actively
maintained) -- a good fit for the packaged desktop build's low-resource
Windows target, unlike heavier alternatives that pull in C extensions.
"""

from __future__ import annotations

import datetime

import jdatetime
from django import forms

JALALI_DATE_FORMAT = "%Y/%m/%d"


def to_jalali(value: datetime.date | None) -> jdatetime.date | None:
    """Gregorian -> Jalali. Accepts date or datetime; returns None for None."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        value = value.date()
    return jdatetime.date.fromgregorian(date=value)


def to_gregorian(value: jdatetime.date | None) -> datetime.date | None:
    """Jalali -> Gregorian. Returns None for None."""
    if value is None:
        return None
    return value.togregorian()


def format_jalali(value: datetime.date | None) -> str:
    """Gregorian date -> 'YYYY/MM/DD' Jalali string for display. Empty
    string for None so templates don't need a separate null check."""
    j = to_jalali(value)
    if j is None:
        return ""
    return j.strftime(JALALI_DATE_FORMAT)


def parse_jalali(text: str) -> datetime.date:
    """
    'YYYY/MM/DD' or 'YYYY-MM-DD' Jalali string -> Gregorian date.
    Raises ValueError on anything else, matching datetime.date.fromisoformat's
    contract so callers (form field .clean(), JS-submitted values) can
    handle it the same way they already handle Gregorian parse errors.
    """
    text = (text or "").strip()
    normalized = text.replace("-", "/")
    parts = normalized.split("/")
    if len(parts) != 3:
        raise ValueError(f"Invalid Jalali date: {text!r}")
    year, month, day = (int(p) for p in parts)
    j = jdatetime.date(year, month, day)
    return j.togregorian()


def jalali_month_bounds(jalali_year: int, jalali_month: int) -> tuple[datetime.date, datetime.date]:
    """
    Given a Jalali year/month (jalali_month in 1..12), returns
    (first_day, last_day) as Gregorian dates -- the correct Gregorian
    boundary for "this Jalali month", handling 29/30/31-day months and
    leap Esfand (30 days) correctly.

    This exists because "first/last of the month" must mean the
    operator's Jalali month, not the Gregorian calendar month: a period
    such as "1405/06" has to bound its data/backfill range by the
    Gregorian dates that 1405/06 actually spans, not by date(1405, 6, 1)
    misread as a Gregorian year/month, and not by the Gregorian calendar
    month that happens to share part of the same wall-clock time.

    The last day is computed as "the day before the first day of the
    next Jalali month" rather than a fixed 29/30/31 table, so leap years
    (which move Esfand from 29 to 30 days) are handled correctly without
    a separate leap-year check.
    """
    first = jdatetime.date(jalali_year, jalali_month, 1)
    if jalali_month == 12:
        next_month_first = jdatetime.date(jalali_year + 1, 1, 1)
    else:
        next_month_first = jdatetime.date(jalali_year, jalali_month + 1, 1)
    last = next_month_first.togregorian() - datetime.timedelta(days=1)
    return first.togregorian(), last


def jalali_month_start(value: datetime.date) -> datetime.date:
    """
    Given any Gregorian date, returns the Gregorian date of day 1 of the
    JALALI month containing it -- e.g. 2026-09-01 (Jalali 1405/06/10)
    returns 2026-08-23 (Jalali 1405/06/01), NOT 2026-09-01 itself.

    This is the fix for a specific bug class: anywhere the codebase used
    to compute "first of the month" as value.replace(day=1) (a Gregorian
    operation) and then display that result through the |jalali filter,
    the displayed date looked like a nonsensical mid-month Jalali date
    (e.g. "1405/06/10") instead of the real first-of-month
    ("1405/06/01"), because replace(day=1) finds the 1st of the
    Gregorian month, which essentially never lines up with the 1st of
    the corresponding Jalali month. Use this function instead of
    value.replace(day=1) wherever the "first of the month" the operator
    sees/reads needs to be a Jalali month boundary.
    """
    j = to_jalali(value)
    first, _ = jalali_month_bounds(j.year, j.month)
    return first


def current_jalali_year_month(today: datetime.date) -> tuple[int, int]:
    """The Jalali (year, month) containing the given Gregorian date --
    used wherever a view needs "this month" to mean the operator's
    current Jalali month rather than the Gregorian one."""
    j = to_jalali(today)
    return j.year, j.month


class JalaliDateWidget(forms.TextInput):
    """
    A plain text input that displays and accepts Jalali dates
    ('YYYY/MM/DD'), backed by the same client-side calendar widget used
    for the global Date Control (static/js/jalali.js). The value that
    ends up in the widget's HTML is Jalali text for the operator to
    read/type; JalaliDateField below converts it to/from a Gregorian
    date object at the form boundary, so views and models never see
    anything but ordinary Gregorian dates.
    """

    def __init__(self, attrs=None):
        default_attrs = {"class": "form-input jalali-date-field", "inputmode": "numeric", "autocomplete": "off"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    def format_value(self, value):
        if value is None or value == "":
            return ""
        if isinstance(value, str):
            # Re-displaying a bound/invalid submission: show back exactly
            # what the operator typed rather than silently altering it.
            return value
        return format_jalali(value)

    class Media:
        js = ("js/jalali.js", "js/jalali_date_field.js")


class JalaliDateField(forms.DateField):
    """
    Drop-in replacement for forms.DateField that reads/writes Jalali text
    but produces an ordinary Gregorian datetime.date in cleaned_data --
    exactly like forms.DateField already does internally, just with a
    Jalali-aware widget and parser instead of Gregorian ISO parsing.
    """

    widget = JalaliDateWidget

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, datetime.date):
            return value
        try:
            return parse_jalali(value)
        except (ValueError, TypeError) as exc:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid") from exc
