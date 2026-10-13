from __future__ import annotations

import re
from typing import Any

from .ledger import ITEMS

REQUIRED_SCHEMA = ["item", "made", "sold", "leftover", "sold_out", "sold_out_time", "context_tags", "confidence"]


def extract_note_fields(note: str) -> dict[str, Any]:
    text = note.lower().strip()
    item_name = None
    sold = None
    made = None
    leftover = None
    sold_out = False
    sold_out_time = None
    context_tags = []

    for item in ITEMS:
        name = item["name"].lower()
        if re.search(rf"\b{re.escape(name.lower())}\b", text):
            item_name = item["name"]
            break

    match = re.search(r"sold\s+(\d+)\s+([a-zA-Z ]+)", text)
    if match:
        sold = int(match.group(1))
        candidate = match.group(2).strip()
        if item_name is None:
            for item in ITEMS:
                if candidate.startswith(item["name"].lower()[:3]):
                    item_name = item["name"]
                    break
        if candidate:
            context_tags.extend([candidate])

    match = re.search(r"made\s+(\d+)", text)
    if match:
        made = int(match.group(1))

    match = re.search(r"(\d+)\s+(?:left|leftover|remaining|still)", text)
    if match:
        leftover = int(match.group(1))

    if "gone by" in text or "sold out" in text or "sold-out" in text:
        sold_out = True
    sold_out_match = re.search(r"gone by\s*(\d{1,2})\s*pm|sold out around\s*(\d{1,2})", text)
    if sold_out_match:
        time = sold_out_match.group(1) or sold_out_match.group(2)
        sold_out_time = int(time)

    for context_word in ["rainy", "hot day", "exam week", "match day", "diwali", "festive", "college"]:
        if context_word in text:
            context_tags.append(context_word)

    if sold is None and item_name:
        sold = 0
    if made is None and item_name:
        made = sold if sold is not None else 0
    if leftover is None and made is not None and sold is not None:
        leftover = max(0, made - sold)

    return {
        "item": item_name,
        "made": made,
        "sold": sold,
        "leftover": leftover,
        "sold_out": sold_out,
        "sold_out_time": sold_out_time,
        "context_tags": list(dict.fromkeys(context_tags)),
        "confidence": 0.7,
    }


def extractor_baseline(note: str) -> dict[str, Any]:
    result = extract_note_fields(note)
    for field in REQUIRED_SCHEMA:
        if field not in result:
            result[field] = None
    return result
