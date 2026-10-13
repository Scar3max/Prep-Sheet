from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

ITEMS = [
    {"name": "Croissant", "price": 45, "cost": 20, "fresh_daily": True, "seasonal_bias": 1.1},
    {"name": "Masala Dosa", "price": 60, "cost": 26, "fresh_daily": True, "seasonal_bias": 1.0},
    {"name": "Veg Puff", "price": 40, "cost": 18, "fresh_daily": True, "seasonal_bias": 1.2},
    {"name": "Cold Coffee", "price": 110, "cost": 35, "fresh_daily": False, "seasonal_bias": 1.15},
    {"name": "Tea", "price": 25, "cost": 8, "fresh_daily": False, "seasonal_bias": 1.05},
    {"name": "Muffin", "price": 70, "cost": 28, "fresh_daily": True, "seasonal_bias": 0.9},
    {"name": "Bun Maska", "price": 35, "cost": 15, "fresh_daily": True, "seasonal_bias": 1.0},
    {"name": "Sandwich", "price": 90, "cost": 38, "fresh_daily": True, "seasonal_bias": 1.1},
    {"name": "Samosa", "price": 30, "cost": 12, "fresh_daily": True, "seasonal_bias": 1.2},
    {"name": "Cake Slice", "price": 120, "cost": 55, "fresh_daily": True, "seasonal_bias": 0.95},
]

HOLIDAYS = {
    "Diwali": 1.25,
    "Navratri": 1.18,
    "Holi": 1.15,
    "Eid": 1.12,
    "Republic Day": 1.08,
    "Christmas": 1.06,
}


@dataclass(frozen=True)
class LedgerRow:
    date: str
    item: str
    day_of_week: int
    weekend: int
    temp_c: float
    rain_mm: float
    holiday: str | None
    festival: int
    college_term: int
    true_demand: int
    made: int
    sold: int
    leftover: int
    sold_out: int
    sold_out_time: int | None


def _day_name(day_number: int) -> str:
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day_number % 7]


def generate_ledger(days: int = 150, seed: int = 42) -> list[LedgerRow]:
    rnd = random.Random(seed)
    start = date(2025, 1, 1)
    rows: list[LedgerRow] = []

    for offset in range(days):
        day = start + timedelta(days=offset)
        weekend = 1 if day.weekday() >= 5 else 0
        temp_c = 22 + 9 * __import__("math").sin(offset / 9) + rnd.uniform(-4, 5)
        rain_mm = max(0.0, 10 + 28 * max(0.0, __import__("math").sin(offset / 6)) + rnd.uniform(0, 10))
        holiday = None
        festival = 0
        for name, multiplier in HOLIDAYS.items():
            if offset % 21 == 0:
                holiday = name
                festival = 1
                break
        if holiday is None and day.month in {10, 11}:
            holiday = "Diwali" if rnd.random() < 0.35 else None
            festival = 1 if holiday else 0

        if day.month in {3, 4} and rnd.random() < 0.5:
            festival = 1
        college_term = 1 if day.month in {1, 2, 7, 8, 9} and rnd.random() < 0.5 else 0

        for item in ITEMS:
            base = 18
            if item["name"] in {"Cold Coffee", "Tea"}:
                base = 24
            if item["name"] in {"Croissant", "Veg Puff", "Samosa", "Bun Maska"}:
                base = 22

            weekday_factor = 1.15 if day.weekday() in {0, 1, 2, 3, 4} else 1.3
            if item["name"] in {"Tea", "Cold Coffee"} and rain_mm > 18:
                weekday_factor += 0.35
            if item["name"] in {"Cold Coffee"} and temp_c > 30:
                weekday_factor += 0.25
            if item["name"] in {"Croissant", "Muffin", "Cake Slice"} and day.weekday() == 6:
                weekday_factor *= 0.8
            if holiday:
                weekday_factor *= HOLIDAYS.get(holiday, 1.05)
            if festival:
                weekday_factor *= 1.18
            if college_term:
                weekday_factor *= 1.14

            demand = max(0, round(base * item["seasonal_bias"] * weekday_factor + rnd.uniform(-6, 8)))
            if item["name"] == "Tea" and weekend:
                demand += 6
            if item["name"] == "Cold Coffee" and rain_mm > 30:
                demand += 8
            if item["name"] in {"Veg Puff", "Samosa", "Croissant"} and day.weekday() == 5:
                demand += 5

            made = max(8, int(round(demand * rnd.uniform(0.9, 1.25))))
            sold = min(demand, made)
            sold_out = 1 if demand > made else 0
            sold_out_time = None
            leftover = max(0, made - demand)
            if sold_out:
                sold_out_time = 16 if rnd.random() < 0.75 else 14
                if rnd.random() < 0.5:
                    sold_out_time = 18
            rows.append(
                LedgerRow(
                    date=day.isoformat(),
                    item=item["name"],
                    day_of_week=day.weekday(),
                    weekend=weekend,
                    temp_c=round(temp_c, 1),
                    rain_mm=round(rain_mm, 1),
                    holiday=holiday,
                    festival=festival,
                    college_term=college_term,
                    true_demand=demand,
                    made=made,
                    sold=sold,
                    leftover=leftover,
                    sold_out=sold_out,
                    sold_out_time=sold_out_time,
                )
            )
    return rows


def ledger_to_rows(ledger: list[LedgerRow]) -> list[dict[str, Any]]:
    return [row.__dict__ for row in ledger]
