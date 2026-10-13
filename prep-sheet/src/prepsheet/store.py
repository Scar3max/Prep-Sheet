from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "prepsheet.sqlite3"


class PrepStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS menu_items (
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    price_inr REAL NOT NULL CHECK (price_inr >= 0),
                    cost_inr REAL NOT NULL CHECK (cost_inr >= 0),
                    PRIMARY KEY (chat_id, name)
                );
                CREATE TABLE IF NOT EXISTS sales (
                    chat_id INTEGER NOT NULL,
                    sales_date TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    made INTEGER NOT NULL CHECK (made >= 0),
                    sold INTEGER NOT NULL CHECK (sold >= 0 AND sold <= made),
                    sold_out INTEGER NOT NULL CHECK (sold_out IN (0, 1)),
                    PRIMARY KEY (chat_id, sales_date, item_name)
                );
                CREATE TABLE IF NOT EXISTS conversation_state (
                    chat_id INTEGER PRIMARY KEY,
                    state TEXT NOT NULL,
                    sales_date TEXT
                );
                CREATE TABLE IF NOT EXISTS pending_drafts (
                    chat_id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    sales_date TEXT
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def set_state(self, chat_id: int, state: str, sales_date: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_state (chat_id, state, sales_date)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET state = excluded.state,
                    sales_date = excluded.sales_date
                """,
                (chat_id, state, sales_date),
            )

    def get_state(self, chat_id: int) -> tuple[str, str | None] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state, sales_date FROM conversation_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return (row["state"], row["sales_date"]) if row else None

    def clear_state(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM conversation_state WHERE chat_id = ?", (chat_id,))

    def save_draft(
        self, chat_id: int, kind: str, draft: list[dict[str, Any]], sales_date: str | None = None
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pending_drafts (chat_id, kind, draft_json, sales_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET kind = excluded.kind,
                    draft_json = excluded.draft_json, sales_date = excluded.sales_date
                """,
                (chat_id, kind, json.dumps(draft), sales_date),
            )

    def get_draft(self, chat_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT kind, draft_json, sales_date FROM pending_drafts WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "kind": row["kind"],
            "draft": json.loads(row["draft_json"]),
            "sales_date": row["sales_date"],
        }

    def clear_draft(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM pending_drafts WHERE chat_id = ?", (chat_id,))

    def save_menu(self, chat_id: int, items: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            existing = {
                row["name"].casefold(): row["name"]
                for row in connection.execute(
                    "SELECT name FROM menu_items WHERE chat_id = ?", (chat_id,)
                )
            }
            for item in items:
                stored_name = existing.get(item["name"].casefold(), item["name"])
                connection.execute(
                    """
                    INSERT INTO menu_items (chat_id, name, price_inr, cost_inr)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id, name) DO UPDATE SET
                        price_inr = excluded.price_inr, cost_inr = excluded.cost_inr
                    """,
                    (
                        chat_id,
                        stored_name,
                        item["price_inr"],
                        item["cost_inr"],
                    ),
                )

    def list_menu(self, chat_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT name, price_inr, cost_inr FROM menu_items
                WHERE chat_id = ? ORDER BY name
                """,
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_sales(
        self, chat_id: int, sales_date: str, rows: list[dict[str, Any]]
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO sales (chat_id, sales_date, item_name, made, sold, sold_out)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chat_id,
                        sales_date,
                        row["item"],
                        row["made"],
                        row["sold"],
                        int(row["sold_out"]),
                    )
                    for row in rows
                ],
            )

    def list_sales(self, chat_id: int, item: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT sales_date, item_name, made, sold, sold_out FROM sales
            WHERE chat_id = ?
        """
        params: tuple[Any, ...] = (chat_id,)
        if item is not None:
            query += " AND item_name = ?"
            params += (item,)
        query += " ORDER BY sales_date, item_name"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def prep_summary(self, chat_id: int) -> dict[str, dict[str, Any]]:
        menu = self.list_menu(chat_id)
        if not menu:
            raise ValueError("No menu saved yet. Use /menu to add menu items first.")
        sales = self.list_sales(chat_id)
        if not sales:
            raise ValueError("No sales saved yet. Use /sales to enter daily sales first.")

        menu_by_name = {item["name"].casefold(): item for item in menu}
        sales_by_item: dict[str, list[dict[str, Any]]] = {}
        for row in sales:
            sales_by_item.setdefault(row["item_name"].casefold(), []).append(row)

        summary: dict[str, dict[str, Any]] = {}
        for normalized_name, records in sales_by_item.items():
            menu_item = menu_by_name.get(normalized_name)
            if not menu_item:
                continue
            recent = records[-7:]
            demand_estimates = [
                max(row["sold"], row["made"] if row["sold_out"] else row["sold"])
                for row in recent
            ]
            forecast = sum(demand_estimates) / len(demand_estimates)
            margin = float(menu_item["price_inr"]) - float(menu_item["cost_inr"])
            waste_penalty = float(menu_item["cost_inr"]) * 0.9
            ratio = max(0.05, min(0.95, margin / max(1.0, margin + waste_penalty)))
            prep_qty = max(0, int(round(forecast * (0.5 + ratio))))
            sold_out_days = sum(bool(row["sold_out"]) for row in recent)
            reasons = ["average of recent recorded sales"]
            if sold_out_days:
                reasons.append(f"stock-out adjustment on {sold_out_days} recent day(s)")
            summary[menu_item["name"]] = {
                "qty": prep_qty,
                "reasons": reasons,
                "forecast": round(forecast, 1),
            }
        if not summary:
            raise ValueError("No saved sales match the current menu. Check item names with /menu list.")
        return summary


def parse_menu_message(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3 or not parts[0]:
            raise ValueError(f"Menu line {line_number}: use Name | price_inr | cost_inr")
        name = parts[0]
        if name.casefold() in seen:
            raise ValueError(f"Menu line {line_number}: duplicate item name {name!r}")
        try:
            price = float(parts[1])
            cost = float(parts[2])
        except ValueError as exc:
            raise ValueError(f"Menu line {line_number}: price and cost must be numbers") from exc
        if price < 0 or cost < 0:
            raise ValueError(f"Menu line {line_number}: price and cost cannot be negative")
        seen.add(name.casefold())
        items.append({"name": name, "price_inr": price, "cost_inr": cost})
    if not items:
        raise ValueError("Send at least one menu item.")
    return items


def parse_sales_message(text: str, menu: list[dict[str, Any]]) -> list[dict[str, Any]]:
    menu_names = {item["name"].casefold(): item["name"] for item in menu}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4 or not parts[0]:
            raise ValueError(f"Sales line {line_number}: use Name | made | sold | sold_out(yes/no)")
        normalized_name = parts[0].casefold()
        if normalized_name not in menu_names:
            raise ValueError(f"Sales line {line_number}: {parts[0]!r} is not on your menu")
        if normalized_name in seen:
            raise ValueError(f"Sales line {line_number}: duplicate item {parts[0]!r}")
        try:
            made = int(parts[1])
            sold = int(parts[2])
        except ValueError as exc:
            raise ValueError(f"Sales line {line_number}: made and sold must be whole numbers") from exc
        if made < 0 or sold < 0 or sold > made:
            raise ValueError(f"Sales line {line_number}: require 0 <= sold <= made")
        stockout_value = parts[3].casefold()
        if stockout_value not in {"yes", "no"}:
            raise ValueError(f"Sales line {line_number}: stock-out must be yes or no")
        rows.append(
            {
                "item": menu_names[normalized_name],
                "made": made,
                "sold": sold,
                "sold_out": stockout_value == "yes",
            }
        )
        seen.add(normalized_name)
    if not rows:
        raise ValueError("Send at least one sales row.")
    return rows


def today_iso() -> str:
    return date.today().isoformat()
