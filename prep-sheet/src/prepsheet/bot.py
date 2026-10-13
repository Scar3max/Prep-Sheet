from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from typing import Any

from .store import PrepStore, parse_menu_message, parse_sales_message, today_iso

TELEGRAM_API_BASE = "https://api.telegram.org"


def parse_allowed_chat_ids(value: str | None) -> set[int]:
    if not value:
        return set()
    try:
        return {int(part.strip()) for part in value.split(",") if part.strip()}
    except ValueError as exc:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS must be comma-separated integer IDs") from exc


class TelegramBot:
    def __init__(
        self,
        token: str | None = None,
        allowed_chat_ids: set[int] | None = None,
        api_base: str = TELEGRAM_API_BASE,
        store: PrepStore | None = None,
    ) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.allowed_chat_ids = (
            set(allowed_chat_ids)
            if allowed_chat_ids is not None
            else parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"))
        )
        self.api_base = api_base.rstrip("/")
        self.store = store or PrepStore()

    def is_configured(self) -> bool:
        return bool(self.token)

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        url = f"{self.api_base}/bot{self.token}/{method}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
                description = str(error_body.get("description", ""))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                description = ""
            description = description.replace(self.token, "[redacted]").strip()
            detail = f": {description}" if description else ""
            raise RuntimeError(f"Telegram API {method} failed with HTTP {exc.code}{detail}") from None
        except Exception as exc:
            detail = str(exc).replace(self.token, "[redacted]") if self.token else str(exc)
            raise RuntimeError(
                f"Telegram API {method} failed ({type(exc).__name__}): {' '.join(detail.split())[:200]}"
            ) from None

        if not isinstance(body, dict) or not body.get("ok"):
            description = body.get("description", "invalid response") if isinstance(body, dict) else "invalid response"
            description = str(description).replace(self.token, "[redacted]").strip()
            raise RuntimeError(f"Telegram API {method} returned an error: {description}")
        return body.get("result")

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise RuntimeError("Telegram getUpdates returned an invalid result")
        return result

    def send_message(self, chat_id: int, text: str) -> None:
        self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text[:4096]},
        )

    def _start_menu_entry(self, chat_id: int) -> str:
        self.store.set_state(chat_id, "awaiting_menu")
        return (
            "🍽️ ADD OR UPDATE YOUR MENU\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Send one item per line:\n"
            "Name | selling price | unit cost\n\n"
            "Example\n"
            "Masala Dosa | 60 | 26\n\n"
            "I’ll show a review before saving. Send /cancel to discard."
        )

    def _start_sales_entry(self, chat_id: int, sales_date: str) -> str:
        self.store.set_state(chat_id, "awaiting_sales", sales_date)
        return (
            f"📊 RECORD SALES · {sales_date}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Send one menu item per line:\n"
            "Name | made | sold | sold out (yes/no)\n\n"
            "Example\n"
            "Masala Dosa | 40 | 40 | yes\n\n"
            "I’ll show a review before saving. Send /cancel to discard."
        )

    def _format_menu(self, items: list[dict[str, Any]]) -> str:
        lines = [f"🍽️ YOUR MENU · {len(items)} ITEMS", "━━━━━━━━━━━━━━━━━━"]
        lines.extend(
            f"• {item['name']}\n"
            f"  Price ₹{item['price_inr']:g}  ·  Cost ₹{item['cost_inr']:g}"
            for item in items
        )
        return "\n".join(lines)

    def _preview_draft(self, chat_id: int) -> str:
        draft_info = self.store.get_draft(chat_id)
        if not draft_info:
            return "ℹ️ No pending review\nSend /menu or /sales to start an entry."
        draft = draft_info["draft"]
        if draft_info["kind"] == "menu":
            lines = [
                f"🧾 MENU REVIEW · {len(draft)} ITEM(S)",
                "━━━━━━━━━━━━━━━━━━",
            ]
            lines.extend(
                f"• {row['name']}\n"
                f"  Price ₹{row['price_inr']:g}  ·  Cost ₹{row['cost_inr']:g}"
                for row in draft
            )
        else:
            lines = [
                f"🧾 SALES REVIEW · {draft_info['sales_date']} · {len(draft)} ITEM(S)",
                "━━━━━━━━━━━━━━━━━━",
            ]
            lines.extend(
                f"• {row['item']}\n"
                f"  Made {row['made']}  ·  Sold {row['sold']}  ·  "
                f"Sold out: {'Yes' if row['sold_out'] else 'No'}"
                for row in draft
            )
        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━",
                "✅ Send /confirm to save",
                "↩️ Send /cancel to discard",
            ]
        )
        return "\n".join(lines)

    def _handle_text(
        self, chat_id: int, text: str, get_prep_brief: Callable[[int], str]
    ) -> str:
        command_part, *args = text.strip().split(maxsplit=1)
        command = command_part.split("@", 1)[0].lower()
        argument = args[0].strip() if args else ""

        if command == "/cancel":
            self.store.clear_state(chat_id)
            self.store.clear_draft(chat_id)
            return "↩️ Cancelled\nNo pending entry was saved."
        if command == "/menu":
            if argument.casefold() == "list":
                items = self.store.list_menu(chat_id)
                return (
                    self._format_menu(items)
                    if items
                    else "🍽️ No menu saved yet.\n\nSend /menu to add your items."
                )
            return self._start_menu_entry(chat_id)
        if command == "/sales":
            sales_date = argument or today_iso()
            try:
                sales_date = date.fromisoformat(sales_date).isoformat()
            except ValueError:
                return "⚠️ Invalid date\nUse /sales or /sales YYYY-MM-DD."
            return self._start_sales_entry(chat_id, sales_date)
        if command == "/confirm":
            draft_info = self.store.get_draft(chat_id)
            if not draft_info:
                return "ℹ️ Nothing to confirm\nStart with /menu or /sales."
            if draft_info["kind"] == "menu":
                self.store.save_menu(chat_id, draft_info["draft"])
                response = f"✅ MENU SAVED\n{len(draft_info['draft'])} item(s) added or updated."
            else:
                try:
                    self.store.save_sales(
                        chat_id, draft_info["sales_date"], draft_info["draft"]
                    )
                except sqlite3.IntegrityError:
                    return (
                        f"⚠️ SALES NOT SAVED · {draft_info['sales_date']}\n"
                        "Some items already have sales for this date. "
                        "No rows were saved. Use another date or send /cancel."
                    )
                response = (
                    f"✅ SALES SAVED · {draft_info['sales_date']}\n"
                    f"{len(draft_info['draft'])} item(s) recorded."
                )
            self.store.clear_draft(chat_id)
            self.store.clear_state(chat_id)
            return response
        if command == "/prep":
            return get_prep_brief(chat_id)
        if command in {"/start", "/help"}:
            return (
                "👋 PREP SHEET\n"
                "Your cafe’s daily prep assistant.\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🍽️ /menu — add or update menu items\n"
                "📋 /menu list — view your saved menu\n"
                "📊 /sales — enter today’s sales\n"
                "🗓️ /sales YYYY-MM-DD — enter another date\n"
                "🌅 /prep — get your prep plan\n"
                "✅ /confirm — save the preview\n"
                "↩️ /cancel — discard the current entry\n\n"
                "Add your menu and sales first to get a useful prep plan."
            )

        state = self.store.get_state(chat_id)
        if not state:
            return (
                "ℹ️ Ready when you are\n"
                "Send /menu to set up your menu, /sales to record sales, "
                "or /help to see all commands."
            )
        state_name, sales_date = state
        try:
            if state_name == "awaiting_menu":
                draft = parse_menu_message(text)
                self.store.save_draft(chat_id, "menu", draft)
            elif state_name == "awaiting_sales":
                draft = parse_sales_message(text, self.store.list_menu(chat_id))
                self.store.save_draft(chat_id, "sales", draft, sales_date)
            else:
                return "⚠️ This entry expired\nStart again with /menu or /sales."
        except ValueError as exc:
            return f"⚠️ I couldn’t read that entry\n{exc}\n\nPlease correct it and send again."
        self.store.set_state(chat_id, "awaiting_confirmation", sales_date)
        return self._preview_draft(chat_id)

    def handle_update(
        self, update: dict[str, Any], get_prep_brief: Callable[[int], str]
    ) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
            return
        chat_id = chat["id"]
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return

        command = text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower()
        if chat.get("type") != "private":
            self.send_message(
                chat_id,
                "🔒 For privacy, Prep Sheet only responds in a private chat.",
            )
            return
        if command == "/id":
            self.send_message(chat_id, f"🪪 Your Telegram chat ID\n{chat_id}")
            return
        if chat_id not in self.allowed_chat_ids:
            self.send_message(
                chat_id,
                "🔒 This bot is private.\n"
                "Add your chat ID to TELEGRAM_ALLOWED_CHAT_IDS, restart the bot, "
                "then try again.",
            )
            return
        self.send_message(chat_id, self._handle_text(chat_id, text, get_prep_brief))

    def run_polling(self, get_prep_brief: Callable[[int], str]) -> None:
        if not self.is_configured():
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        offset: int | None = None
        while True:
            updates = self.get_updates(offset=offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                self.handle_update(update, get_prep_brief)
            if not updates:
                time.sleep(0.1)
