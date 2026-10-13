from __future__ import annotations

import random
from typing import Any, Iterable

from .ledger import ITEMS


def generate_owner_note(item: str, sold: int, made: int, leftover: int, sold_out: bool, sold_out_time: int | None, context: list[str] | None = None) -> str:
    context = context or []
    context_text = "" if not context else " " + " ".join(context)
    if sold_out and sold_out_time:
        return f"sold {sold} {item.lower()} by {sold_out_time}pm, made {made}, {item.lower()} gone by {sold_out_time}pm{context_text}."
    if leftover > 0:
        return f"sold {sold} {item.lower()}, made {made}, {leftover} {item.lower()} left{context_text}."
    return f"sold {sold} {item.lower()}, made {made}{context_text}."


def generate_realistic_notes(ledger_rows: Iterable[dict[str, Any]], seed: int = 42) -> list[dict[str, Any]]:
    rnd = random.Random(seed)
    notes: list[dict[str, Any]] = []
    for row in ledger_rows:
        item = row["item"]
        context = []
        if row["rain_mm"] > 20:
            context.append("rainy")
        if row["temp_c"] > 31:
            context.append("hot day")
        if row["holiday"]:
            context.append(row["holiday"].lower())
        if row["college_term"]:
            context.append("exam week")
        if rnd.random() < 0.3:
            context.append("match day")
        context = context[:2]

        note = generate_owner_note(item, row["sold"], row["made"], row["leftover"], bool(row["sold_out"]), row["sold_out_time"], context)
        notes.append({
            "note": note,
            "item": item,
            "made": row["made"],
            "sold": row["sold"],
            "leftover": row["leftover"],
            "sold_out": bool(row["sold_out"]),
            "sold_out_time": row["sold_out_time"],
            "context": context,
        })
    return notes
