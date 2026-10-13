from __future__ import annotations

import math
import os
from typing import Any


FEATURE_COLUMNS = (
    "item",
    "day_of_week",
    "weekend",
    "holiday",
    "festival",
    "college_term",
    "temp_c",
    "rain_mm",
    "lag_sold_1",
    "lag_sold_7",
    "rolling_mean_7",
    "sold_out_yesterday",
)


def _fallback_forecast(feature_rows: list[dict[str, Any]], item: str) -> float:
    rows = [row for row in feature_rows if row["item"] == item]
    if not rows:
        return 12.0
    recent = [row["sold"] for row in rows[-7:]]
    base = sum(recent) / max(len(recent), 1)
    weather_boost = 0.0
    if rows[-1]["rain_mm"] > 18:
        weather_boost += 2.0
    if rows[-1]["temp_c"] > 30:
        weather_boost += 1.5
    if rows[-1]["holiday"]:
        weather_boost += 4.0
    if rows[-1]["festival"]:
        weather_boost += 3.0
    return max(0.0, round(base + weather_boost, 1))


def _next_day_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = rows[-1]
    previous_sales = [row["sold"] for row in rows]
    next_day_of_week = (int(latest["day_of_week"]) + 1) % 7
    next_features = {
        "item": latest["item"],
        "day_of_week": next_day_of_week,
        "weekend": int(next_day_of_week >= 5),
        "holiday": latest["holiday"],
        "festival": latest["festival"],
        "college_term": latest["college_term"],
        "temp_c": latest["temp_c"],
        "rain_mm": latest["rain_mm"],
        "lag_sold_1": previous_sales[-1],
        "lag_sold_7": previous_sales[-7] if len(previous_sales) >= 7 else previous_sales[0],
        "rolling_mean_7": sum(previous_sales[-7:]) / min(7, len(previous_sales)),
        "sold_out_yesterday": int(bool(latest["sold_out"])),
    }
    return next_features


def _safe_error_detail(exc: Exception) -> str:
    detail = str(exc)
    token = os.getenv("TABPFN_TOKEN")
    if token:
        detail = detail.replace(token, "[redacted]")
    detail = " ".join(detail.split())
    return detail[:240] or type(exc).__name__


def _tabpfn_predictions(
    feature_rows: list[dict[str, Any]],
) -> tuple[dict[str, float] | None, str | None]:
    if not os.getenv("TABPFN_TOKEN"):
        return None, "TABPFN_TOKEN is not configured"
    if not feature_rows or any("true_demand" not in row for row in feature_rows):
        return None, "TabPFN demo training requires synthetic true_demand labels"

    try:
        import pandas as pd

        from tabpfn_client import TabPFNRegressor
    except ImportError:
        return None, "TabPFN dependencies are not installed; install with pip install -e .[tabpfn]"

    items = sorted({row["item"] for row in feature_rows})
    train_x = pd.DataFrame(
        [{column: row[column] for column in FEATURE_COLUMNS} for row in feature_rows]
    )
    train_y = pd.Series([float(row["true_demand"]) for row in feature_rows])
    predict_x = pd.DataFrame(
        [_next_day_features([row for row in feature_rows if row["item"] == item]) for item in items],
        columns=FEATURE_COLUMNS,
    )
    try:
        model = TabPFNRegressor()
        model.fit(train_x, train_y)
        predictions = model.predict(predict_x)
        forecast_values = [float(prediction) for prediction in predictions]
        if any(not math.isfinite(prediction) for prediction in forecast_values):
            return None, "TabPFN returned a non-finite prediction"
        return {
            item: max(0.0, round(prediction, 1))
            for item, prediction in zip(items, forecast_values, strict=True)
        }, None
    except Exception as exc:
        return None, f"TabPFN call failed ({type(exc).__name__}): {_safe_error_detail(exc)}"


def forecast_all_items_with_status(
    feature_rows: list[dict[str, Any]], provider: str | None = None
) -> tuple[dict[str, float], dict[str, str]]:
    selected = (provider or os.getenv("FORECAST_PROVIDER") or os.getenv("MODEL_PROVIDER") or "template").lower()
    if selected in {"tabpfn", "prior", "priorlabs", "live"}:
        predictions, error = _tabpfn_predictions(feature_rows)
        if predictions is not None:
            return predictions, {"requested": "tabpfn", "used": "tabpfn", "status": "success"}
        fallback = {item: _fallback_forecast(feature_rows, item) for item in sorted({row["item"] for row in feature_rows})}
        return fallback, {
            "requested": "tabpfn",
            "used": "local_fallback",
            "status": "fallback",
            "reason": error or "TabPFN did not return predictions",
        }
    if selected != "template":
        return (
            {item: _fallback_forecast(feature_rows, item) for item in sorted({row["item"] for row in feature_rows})},
            {"requested": selected, "used": "local_fallback", "status": "fallback", "reason": "Unknown forecast provider"},
        )
    return (
        {item: _fallback_forecast(feature_rows, item) for item in sorted({row["item"] for row in feature_rows})},
        {"requested": "template", "used": "local_fallback", "status": "local"},
    )


def forecast_all_items(feature_rows: list[dict[str, Any]], provider: str | None = None) -> dict[str, float]:
    predictions, _ = forecast_all_items_with_status(feature_rows, provider=provider)
    return predictions
