"""
Template-side entry point for Jalali date display. Wraps apps/core/jalali.py
so templates never import jdatetime or format dates by hand -- every
user-facing date in the project should go through {{ value|jalali }}
instead of Django's built-in |date filter.

Usage: {{ working_day.date|jalali }} -> "1405/06/23"

Does NOT replace |date:"Y-m-d" usages that build URLs or hidden form
values from a date -- those remain Gregorian on purpose (see
apps/core/jalali.py's module docstring).
"""

from django import template

from apps.core.jalali import format_jalali

register = template.Library()


@register.filter(name="jalali")
def jalali(value):
    """Gregorian date/datetime -> 'YYYY/MM/DD' Jalali string. Falls back
    to an empty string for None, same as Django's |date filter."""
    return format_jalali(value)
