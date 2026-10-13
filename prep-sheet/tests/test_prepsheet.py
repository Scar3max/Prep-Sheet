import io
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from prepsheet.__main__ import _saved_prep_brief, main
from prepsheet.brief import (
    _gemini_brief,
    generate_brief_with_status,
    number_guardrail,
)
from prepsheet.bot import TelegramBot, parse_allowed_chat_ids
from prepsheet.config import load_dotenv
from prepsheet.extract import extractor_baseline
from prepsheet.features import build_feature_table
from prepsheet.forecast import forecast_all_items_with_status
from prepsheet.ledger import generate_ledger
from prepsheet.store import PrepStore, parse_menu_message, parse_sales_message


class PrepSheetTests(unittest.TestCase):
    def test_parse_allowed_chat_ids(self):
        self.assertEqual(parse_allowed_chat_ids("123, -456,123"), {123, -456})
        self.assertEqual(parse_allowed_chat_ids(""), set())
        with self.assertRaises(ValueError):
            parse_allowed_chat_ids("123,abc")

    def test_telegram_bot_only_serves_allowlisted_private_chat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PrepStore(Path(temp_dir) / "test.sqlite3")
            bot = TelegramBot(token="test-token", allowed_chat_ids={123}, store=store)
            sent: list[tuple[int, str]] = []
            bot.send_message = lambda chat_id, text: sent.append((chat_id, text))
            called: list[str] = []

            bot.handle_update(
                {"message": {"chat": {"id": 999, "type": "private"}, "text": "/prep"}},
                lambda chat_id: called.append("prep") or "synthetic brief",
            )
            self.assertEqual(called, [])
            self.assertIn("private", sent[-1][1].lower())

            bot.handle_update(
                {"message": {"chat": {"id": 123, "type": "group"}, "text": "/prep"}},
                lambda chat_id: called.append("prep") or "synthetic brief",
            )
            self.assertEqual(called, [])
            self.assertIn("private chat", sent[-1][1].lower())

            bot.handle_update(
                {"message": {"chat": {"id": 123, "type": "private"}, "text": "/prep"}},
                lambda chat_id: called.append("prep") or "synthetic brief",
            )
            self.assertEqual(called, ["prep"])
            self.assertEqual(sent[-1], (123, "synthetic brief"))

    def test_telegram_id_command_does_not_generate_prep(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = TelegramBot(
                token="test-token",
                allowed_chat_ids=set(),
                store=PrepStore(Path(temp_dir) / "test.sqlite3"),
            )
            sent: list[tuple[int, str]] = []
            bot.send_message = lambda chat_id, text: sent.append((chat_id, text))

            bot.handle_update(
                {"message": {"chat": {"id": 123, "type": "private"}, "text": "/id"}},
                lambda chat_id: self.fail("ID command must not invoke prep generation"),
            )
            self.assertEqual(sent, [(123, "🪪 Your Telegram chat ID\n123")])

    def test_menu_and_sales_parsers_validate_and_normalize_input(self):
        menu = parse_menu_message(
            "Tea | 25 | 8\nMasala Dosa | 60 | 26"
        )
        self.assertEqual(len(menu), 2)
        sales = parse_sales_message(
            "tea | 20 | 20 | yes\nMasala Dosa | 30 | 24 | no",
            menu,
        )
        self.assertEqual(sales[0]["item"], "Tea")
        self.assertTrue(sales[0]["sold_out"])
        with self.assertRaises(ValueError):
            parse_sales_message("Tea | 10 | 11 | no", menu)
        with self.assertRaises(ValueError):
            parse_sales_message("Coffee | 10 | 5 | no", menu)

    def test_telegram_menu_sales_confirmation_persists_and_prep_uses_saved_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PrepStore(Path(temp_dir) / "test.sqlite3")
            bot = TelegramBot(token="test-token", allowed_chat_ids={123}, store=store)
            sent: list[tuple[int, str]] = []
            bot.send_message = lambda chat_id, text: sent.append((chat_id, text))
            get_prep = lambda chat_id: str(store.prep_summary(chat_id))

            bot.handle_update(
                {"message": {"chat": {"id": 123, "type": "private"}, "text": "/menu"}},
                get_prep,
            )
            self.assertIn("ADD OR UPDATE YOUR MENU", sent[-1][1])
            self.assertIn("Name | selling price | unit cost", sent[-1][1])
            bot.handle_update(
                {
                    "message": {
                        "chat": {"id": 123, "type": "private"},
                        "text": "Tea | 25 | 8\nSamosa | 30 | 12",
                    }
                },
                get_prep,
            )
            self.assertIn("MENU REVIEW", sent[-1][1])
            self.assertEqual(store.list_menu(123), [])
            bot.handle_update(
                {"message": {"chat": {"id": 123, "type": "private"}, "text": "/confirm"}},
                get_prep,
            )
            self.assertEqual(len(store.list_menu(123)), 2)
            store.save_menu(
                123,
                [{"name": "tea", "price_inr": 27, "cost_inr": 9}],
            )
            updated_menu = store.list_menu(123)
            self.assertEqual(len(updated_menu), 2)
            tea = next(item for item in updated_menu if item["name"] == "Tea")
            self.assertEqual(tea["price_inr"], 27)

            bot.handle_update(
                {
                    "message": {
                        "chat": {"id": 123, "type": "private"},
                        "text": "/sales 2026-10-13",
                    }
                },
                get_prep,
            )
            bot.handle_update(
                {
                    "message": {
                        "chat": {"id": 123, "type": "private"},
                        "text": "Tea | 20 | 20 | yes\nSamosa | 24 | 18 | no",
                    }
                },
                get_prep,
            )
            self.assertIn("SALES REVIEW", sent[-1][1])
            self.assertEqual(store.list_sales(123), [])
            bot.handle_update(
                {"message": {"chat": {"id": 123, "type": "private"}, "text": "/confirm"}},
                get_prep,
            )

            reopened_store = PrepStore(Path(temp_dir) / "test.sqlite3")
            self.assertEqual(len(reopened_store.list_sales(123)), 2)
            summary = reopened_store.prep_summary(123)
            self.assertEqual(set(summary), {"Tea", "Samosa"})
            self.assertIn("stock-out adjustment", summary["Tea"]["reasons"][1])
            prep_message = _saved_prep_brief(reopened_store, 123)
            self.assertIn("PREP SHEET · TOMORROW", prep_message)
            self.assertIn("Tea: prepare", prep_message)
            self.assertIn("Brief by local template", prep_message)

    def test_cancel_discards_unconfirmed_menu_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PrepStore(Path(temp_dir) / "test.sqlite3")
            bot = TelegramBot(token="test-token", allowed_chat_ids={123}, store=store)
            sent: list[str] = []
            bot.send_message = lambda chat_id, text: sent.append(text)
            callback = lambda chat_id: "brief"
            for text in ("/menu", "Tea | 25 | 8", "/cancel"):
                bot.handle_update(
                    {"message": {"chat": {"id": 123, "type": "private"}, "text": text}},
                    callback,
                )
            self.assertEqual(store.list_menu(123), [])
            self.assertIsNone(store.get_draft(123))

    def test_schema_validity(self):
        note = "sold 14 croissants, 9 cold coffees, puffs gone by 4pm, binned 6 muffins"
        field_map = extractor_baseline(note)
        required = {"item", "made", "sold", "leftover", "sold_out", "sold_out_time", "context_tags", "confidence"}
        self.assertTrue(required.issubset(field_map.keys()))

    def test_no_dates_or_place_names_in_feature_rows(self):
        rows = [r.__dict__ for r in generate_ledger(days=30, seed=7)]
        feature_rows = build_feature_table(rows)
        joined_text = " ".join(str(x) for x in feature_rows)
        self.assertNotIn("2025", joined_text)
        self.assertNotIn("Bengaluru", joined_text)
        self.assertNotIn("Delhi", joined_text)

    def test_number_guardrail(self):
        brief = "Croissant: prepare 25 units. Tea: prepare 18 units."
        safe = number_guardrail(brief, {"item": "Croissant", "qty": 25, "other": 18})
        self.assertIn("25", safe)
        self.assertIn("18", safe)

    def test_number_guardrail_checks_nested_prep_quantities(self):
        summary = {"Tea": {"qty": 18}, "Samosa": {"qty": 25}}
        self.assertEqual(
            number_guardrail("Prepare 18 tea and 25 samosas.", summary),
            "Prepare 18 tea and 25 samosas.",
        )
        self.assertNotEqual(
            number_guardrail("Prepare 999 teas.", summary),
            "Prepare 999 teas.",
        )

    def test_dotenv_loads_keys_without_overriding_process_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                'GEMINI_API_KEY="file-key"\nTABPFN_TOKEN=file-token\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GEMINI_API_KEY": "process-key"}, clear=False):
                loaded = load_dotenv(env_path)
                self.assertEqual(os.environ["GEMINI_API_KEY"], "process-key")
                self.assertEqual(os.environ["TABPFN_TOKEN"], "file-token")
                self.assertEqual(loaded["GEMINI_API_KEY"], "process-key")

    def test_gemini_success_and_failure_are_reported_without_network(self):
        summary = {"Tea": {"qty": 18, "reasons": ["recent sales"]}}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            with patch("prepsheet.brief._gemini_brief", return_value=("Prepare 18 teas.", None)):
                _, status = generate_brief_with_status(summary, provider="gemini")
                self.assertEqual(status["used"], "gemini")
                self.assertEqual(status["status"], "success")
            with patch(
                "prepsheet.brief._gemini_brief",
                return_value=(None, "Gemini HTTP 403: API key invalid"),
            ):
                _, status = generate_brief_with_status(summary, provider="gemini")
                self.assertEqual(status["used"], "local_template")
                self.assertEqual(status["status"], "fallback")
                self.assertIn("HTTP 403", status["reason"])

    def test_tabpfn_success_path_uses_mock_client_without_network(self):
        ledger_rows = [row.__dict__ for row in generate_ledger(days=8, seed=11)]
        feature_rows = build_feature_table(ledger_rows)

        class FakeRegressor:
            def fit(self, features, target):
                self.target_shape = target.shape
                self.target = target

            def predict(self, features):
                return [17.25] * len(features)

        class FakeSeries(list):
            @property
            def shape(self):
                return (len(self),)

        fake_pandas = types.SimpleNamespace(
            DataFrame=lambda rows, columns=None: rows,
            Series=FakeSeries,
        )
        fake_client = types.SimpleNamespace(TabPFNRegressor=FakeRegressor)
        with patch.dict(os.environ, {"TABPFN_TOKEN": "test-token"}, clear=False):
            with patch.dict(sys.modules, {"pandas": fake_pandas, "tabpfn_client": fake_client}):
                predictions, status = forecast_all_items_with_status(
                    feature_rows, provider="tabpfn"
                )
        self.assertEqual(len(predictions), 10)
        self.assertEqual(set(predictions.values()), {17.2})
        self.assertEqual(status["used"], "tabpfn")
        self.assertEqual(status["status"], "success")

    def test_tabpfn_missing_token_reports_local_fallback(self):
        ledger_rows = [row.__dict__ for row in generate_ledger(days=8, seed=11)]
        feature_rows = build_feature_table(ledger_rows)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TABPFN_TOKEN", None)
            predictions, status = forecast_all_items_with_status(
                feature_rows, provider="tabpfn"
            )
        self.assertEqual(len(predictions), 10)
        self.assertEqual(status["used"], "local_fallback")
        self.assertEqual(status["status"], "fallback")
        self.assertIn("TABPFN_TOKEN", status["reason"])

    def test_tabpfn_exception_detail_is_reported_but_token_is_redacted(self):
        ledger_rows = [row.__dict__ for row in generate_ledger(days=8, seed=11)]
        feature_rows = build_feature_table(ledger_rows)

        class BrokenRegressor:
            def fit(self, features, target):
                raise AttributeError("client object has no attribute fit")

        fake_pandas = types.SimpleNamespace(
            DataFrame=lambda rows, columns=None: rows,
            Series=lambda values: values,
        )
        fake_client = types.SimpleNamespace(TabPFNRegressor=BrokenRegressor)
        token = "private-test-token"
        with patch.dict(os.environ, {"TABPFN_TOKEN": token}, clear=False):
            with patch.dict(sys.modules, {"pandas": fake_pandas, "tabpfn_client": fake_client}):
                _, status = forecast_all_items_with_status(
                    feature_rows, provider="tabpfn"
                )
        self.assertEqual(status["status"], "fallback")
        self.assertIn("AttributeError", status["reason"])
        self.assertIn("no attribute fit", status["reason"])
        self.assertNotIn(token, status["reason"])

    def test_gemini_http_error_reports_status_and_message_without_key(self):
        key = "private-gemini-test-key"
        http_error = urllib.error.HTTPError(
            "https://example.invalid",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"error":{"message":"API key not authorized"}}'),
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": key}, clear=False):
            with patch("prepsheet.brief.urllib.request.urlopen", side_effect=http_error):
                _, reason = _gemini_brief("test")
        self.assertIn("HTTP 403", reason)
        self.assertIn("not authorized", reason)
        self.assertNotIn(key, reason)

    def test_gemini_retries_transient_error_then_succeeds(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-3.5-flash-lite"},
            clear=False,
        ):
            with patch(
                "prepsheet.brief._request_gemini_model",
                side_effect=[
                    (None, "gemini-3.5-flash-lite HTTP 503: busy", 503),
                    ("A useful prep brief.", None, None),
                ],
            ) as request:
                with patch("prepsheet.brief.time.sleep"):
                    result, error = _gemini_brief("test prompt")
        self.assertEqual(result, "A useful prep brief.")
        self.assertIsNone(error)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[2], "gemini-3.5-flash-lite")

    def test_gemini_uses_secondary_model_after_primary_capacity_errors(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-3.5-flash-lite"},
            clear=False,
        ):
            with patch(
                "prepsheet.brief._request_gemini_model",
                side_effect=[
                    (None, "primary busy", 503),
                    (None, "primary still busy", 503),
                    ("Brief from secondary model.", None, None),
                ],
            ) as request:
                with patch("prepsheet.brief.time.sleep"):
                    result, error = _gemini_brief("test prompt")
        self.assertEqual(result, "Brief from secondary model.")
        self.assertIsNone(error)
        self.assertEqual(request.call_args_list[2].args[2], "gemini-3.8-flash")

    def test_demo_runs(self):
        with patch.dict(
            os.environ,
            {"FORECAST_PROVIDER": "template", "BRIEF_PROVIDER": "template"},
            clear=False,
        ):
            result = main(["demo"])
        self.assertEqual(result, 0)
        results_path = Path("results/demo_results.json")
        self.assertTrue(results_path.exists())
        results = json.loads(results_path.read_text(encoding="utf-8"))
        self.assertEqual(results["data_source"], "synthetic")
        self.assertEqual(results["providers"]["forecast"]["used"], "local_fallback")
        self.assertEqual(results["providers"]["brief"]["used"], "local_template")


if __name__ == "__main__":
    unittest.main()
