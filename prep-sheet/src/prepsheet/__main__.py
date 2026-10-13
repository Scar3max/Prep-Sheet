from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .bot import TelegramBot, parse_allowed_chat_ids
from .brief import generate_brief_with_status
from .config import load_dotenv
from .evaluate import run_demo
from .store import PrepStore


def _demo(forecast_provider: str | None = None, brief_provider: str | None = None) -> None:
    results = run_demo(
        days=120,
        seed=42,
        forecast_provider=forecast_provider,
        brief_provider=brief_provider,
    )
    heading = "Prep Sheet demo summary"
    print(heading)
    print("-" * len(heading))
    print(json.dumps({"forecasts": results["forecasts"], "prep": results["prep"]}, indent=2))
    print("\nMorning brief:\n")
    print(results["morning_brief"])
    print("\nProvider status:\n")
    print(json.dumps(results["providers"], indent=2))
    print("\nSaved results to:")
    print(str(Path("results/demo_results.json")))


def _run_telegram() -> int:
    load_dotenv()
    try:
        allowed_chat_ids = parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"))
        store = PrepStore()
        bot = TelegramBot(allowed_chat_ids=allowed_chat_ids, store=store)
        if not bot.is_configured():
            print("TELEGRAM_BOT_TOKEN is not configured.", file=sys.stderr)
            return 1
        print("Prep Sheet Telegram bot is polling. Press Ctrl+C to stop.")
        bot.run_polling(lambda chat_id: _saved_prep_brief(store, chat_id))
    except (RuntimeError, ValueError) as exc:
        print(f"Telegram bot stopped: {exc}", file=sys.stderr)
        return 1
    return 0


def _saved_prep_brief(store: PrepStore, chat_id: int) -> str:
    try:
        prep_summary = store.prep_summary(chat_id)
    except ValueError as exc:
        return f"⚠️ SET UP YOUR DATA FIRST\n{exc}"
    brief, status = generate_brief_with_status(prep_summary)
    heading = [
        "🌅 PREP SHEET · TOMORROW",
        "━━━━━━━━━━━━━━━━━━",
    ]
    heading.extend(f"• {line.strip()}" for line in brief.splitlines() if line.strip())
    heading.append("━━━━━━━━━━━━━━━━━━")
    if status["status"] == "fallback":
        heading.append("ℹ️ Gemini unavailable · local brief used")
    elif status["status"] == "success":
        heading.append("✨ Brief by Gemini")
    else:
        heading.append("📌 Brief by local template")
    return "\n".join(heading)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prep Sheet CLI")
    parser.add_argument("command", nargs="?", default="demo", help="demo or help")
    parser.add_argument(
        "--forecast-provider",
        choices=("template", "tabpfn"),
        default=None,
        help="forecast engine; defaults to FORECAST_PROVIDER or template",
    )
    parser.add_argument(
        "--brief-provider",
        choices=("template", "gemini"),
        default=None,
        help="brief generator; defaults to BRIEF_PROVIDER or template",
    )
    args = parser.parse_args(argv)

    if args.command == "demo":
        load_dotenv()
        _demo(args.forecast_provider, args.brief_provider)
        return 0
    if args.command == "telegram":
        return _run_telegram()
    if args.command == "help":
        print("Available commands: demo, telegram")
        print("Telegram chat commands: /menu, /menu list, /sales [YYYY-MM-DD], /prep, /confirm, /cancel")
        return 0
    print("Unknown command. Try: python -m prepsheet demo or python -m prepsheet telegram")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
