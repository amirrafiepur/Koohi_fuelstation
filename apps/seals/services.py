"""
Seal queries shared by the on-screen list and its PDF, so both always show the
same records in the same order.
"""

from .models import NozzleSeal


def seals_in_range(start_date, end_date):
    """
    The seals dated within [start_date, end_date], ordered:

      1. by nozzle number, ascending (نازل ۱ ... نازل ۲۶) -- the number itself,
         so 2 comes before 10 and a seal on nozzle 14 never jumps ahead of the
         records of nozzles 1-13;
      2. within a nozzle, newest first: by date descending, and for seals
         on the same date by registration order descending (-id), because a
         seal carries a date but no time of day. A new seal for a nozzle
         therefore lands at the top of that nozzle's own group.

    Read-only; no stored data is changed.
    """
    return (
        NozzleSeal.objects.select_related("nozzle__tank__product")
        .filter(date__gte=start_date, date__lte=end_date)
        .order_by("nozzle__number", "-date", "-id")
    )
