from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .brief import generate_brief_with_status
from .config import load_menu
from .demand import evaluate_sell_out_method
from .extract import extractor_baseline
from .features import build_feature_table
from .forecast import forecast_all_items_with_status
from .ledger import generate_ledger
from .notes import generate_realistic_notes
from .prep import compute_prep_quantity


def _price_map_from_menu() -> dict[str, dict[str, int]]:
    menu = load_menu()
    return {entry["name"]: {"price": int(entry["price_inr"]), "cost": int(entry["cost_inr"])} for entry in menu}


def run_demo(
    days: int = 120,
    seed: int = 42,
    forecast_provider: str | None = None,
    brief_provider: str | None = None,
) -> dict[str, Any]:
    ledger = generate_ledger(days=days, seed=seed)
    note_rows = generate_realistic_notes([row.__dict__ for row in ledger], seed=seed)
    feature_rows = build_feature_table([row.__dict__ for row in ledger])
    forecasts, forecast_status = forecast_all_items_with_status(
        feature_rows, provider=forecast_provider
    )
    menu_prices = _price_map_from_menu()

    prepared: dict[str, Any] = {}
    for item in sorted({row["item"] for row in feature_rows}):
        item_meta = {"name": item, "price": menu_prices.get(item, {"price": 45, "cost": 20})["price"], "cost": menu_prices.get(item, {"price": 45, "cost": 20})["cost"]}
        prep_qty = compute_prep_quantity(item_meta, forecasts[item])
        prepared[item] = {"qty": prep_qty, "reasons": ["recent sales", "weather cues"]}

    extractor_results = {
        "baseline": extractor_baseline(note_rows[0]["note"]) if note_rows else {},
        "sample_count": len(note_rows),
    }
    sell_out_result = evaluate_sell_out_method([row.__dict__ for row in ledger])
    brief, brief_status = generate_brief_with_status(prepared, provider=brief_provider)
    ranking = {item: {"forecast": value, "prep": prepared[item]["qty"]} for item, value in forecasts.items()}
    summary = {
        "data_source": "synthetic",
        "days": days,
        "items": list(sorted(forecasts.keys())),
        "forecasts": forecasts,
        "prep": prepared,
        "extractor_baseline": extractor_results,
        "sell_out_evaluation": sell_out_result,
        "ranking": ranking,
        "morning_brief": brief,
        "providers": {"forecast": forecast_status, "brief": brief_status},
    }

    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)
    (out_dir / "demo_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "extractor_metrics.json").write_text(json.dumps(extractor_results, indent=2), encoding="utf-8")
    (out_dir / "forecast_results.json").write_text(
        json.dumps(
            {"forecasts": forecasts, "ranking": ranking, "provider": forecast_status},
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary
