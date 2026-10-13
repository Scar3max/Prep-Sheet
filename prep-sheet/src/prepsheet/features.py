from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_feature_table(ledger_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    history_by_item: dict[str, list[int]] = defaultdict(list)
    last_row_by_item: dict[str, dict[str, Any]] = {}

    for row in ledger_rows:
        item = row["item"]
        sales_hist = history_by_item[item]
        previous = sales_hist[-1] if sales_hist else row["sold"]
        last_week_window = sales_hist[-7:] if sales_hist else [row["sold"]]
        rolling_mean = sum(last_week_window) / max(1, len(last_week_window))
        sold_out_yesterday = 1 if last_row_by_item.get(item, {}).get("sold_out") else 0

        rows.append({
            "item": item,
            "day_of_week": row["day_of_week"],
            "weekend": row["weekend"],
            "holiday": 1 if row["holiday"] else 0,
            "festival": row["festival"],
            "college_term": row["college_term"],
            "temp_c": row["temp_c"],
            "rain_mm": row["rain_mm"],
            "lag_sold_1": previous,
            "lag_sold_7": last_week_window[0] if last_week_window else row["sold"],
            "rolling_mean_7": round(rolling_mean, 2),
            "sold_out_yesterday": sold_out_yesterday,
            "true_demand": row["true_demand"],
            "sold": row["sold"],
            "sold_out": row["sold_out"],
        })

        history_by_item[item].append(row["sold"])
        last_row_by_item[item] = row

    return rows
