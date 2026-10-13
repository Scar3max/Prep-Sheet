from __future__ import annotations

from typing import Any


def critical_ratio(item: dict[str, Any]) -> float:
    margin = item["price"] - item["cost"]
    waste_penalty = item["cost"] * 0.9
    return max(0.05, min(0.95, margin / max(1.0, margin + waste_penalty)))


def compute_prep_quantity(item: dict[str, Any], expected_demand: float) -> int:
    ratio = critical_ratio(item)
    qty = expected_demand * (0.5 + ratio)
    return max(0, int(round(qty)))


def summarize_prep_brief(item_name: str, prep_qty: int, reasons: list[str]) -> str:
    return f"{item_name}: prepare {prep_qty} units. Reasons: {', '.join(reasons[:2])}."
