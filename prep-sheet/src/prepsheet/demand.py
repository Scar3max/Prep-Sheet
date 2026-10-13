from __future__ import annotations

from typing import Any


def lower_bound_correction(row: dict[str, Any]) -> int:
    if row.get("sold_out"):
        corrected = max(row["sold"], row["made"])  # explicit stock-out recovery signal
        return corrected
    return row["sold"]


def apply_sell_out_correction(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    corrected: list[dict[str, Any]] = []
    for row in rows:
        estimate = lower_bound_correction(row)
        corrected_row = dict(row)
        corrected_row["corrected_demand"] = estimate
        corrected.append(corrected_row)
    return corrected


def evaluate_sell_out_method(rows: list[dict[str, Any]]) -> dict[str, float]:
    errors = []
    for row in rows:
        estimate = lower_bound_correction(row)
        errors.append(abs(estimate - row["true_demand"]))
    return {"mae": sum(errors) / max(1, len(errors)), "coverage": len([x for x in rows if x["sold_out"]])}
