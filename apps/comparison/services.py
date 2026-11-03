"""
"مقایسه سیستم مکانیکی و دیجیتال" aggregation.

- فروش مکانیکی: reuses apps.statement.services.build_statement_rows()
  verbatim -- "the same data sources, calculations, and logic as the
  upper table of the final صورت وضعیت ماهانه section," per the task.
  No calculation is duplicated here.
- فروش دیجیتال: comes only from apps.comparison.models.DigitalEntry.
  Nothing here is derived from mechanical/system data; رسیده_total and
  dispatched_total are plain sums of that row's own entered fields
  (DigitalEntry.received_total / .dispatched_total), not a reuse of any
  mechanical calculation.
"""

from apps.stations.models import Tank

from .models import DigitalEntry


def build_mechanical_rows(year: int, month: int):
    from apps.statement import services as statement_services

    return statement_services.build_statement_rows(year, month)


def build_digital_rows(year: int, month: int):
    tanks = Tank.objects.select_related("product").order_by("product__name")
    rows = []
    for tank in tanks:
        entry, _ = DigitalEntry.objects.get_or_create(tank=tank, year=year, month=month)
        rows.append({
            "tank": tank,
            "product": tank.product,
            "entry": entry,
            "beginning_inventory": entry.beginning_inventory,
            "received_quantity": entry.received_quantity,
            "test_return": entry.test_return,
            "overage": entry.overage,
            "received_total": entry.received_total,
            "sales_quantity": entry.sales_quantity,
            "shortage": entry.shortage,
            "ending_inventory": entry.ending_inventory,
            "dispatched_total": entry.dispatched_total,
        })
    return rows
