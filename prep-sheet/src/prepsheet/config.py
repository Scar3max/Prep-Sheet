from __future__ import annotations

import os
from pathlib import Path
import tomllib


ROOT_DIR = Path(__file__).resolve().parents[2]


def _read_toml(path: str | Path) -> dict:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(config_path: str | Path | None = None) -> dict:
    config_file = Path(config_path) if config_path else ROOT_DIR / "config.example.toml"
    config = _read_toml(config_file)
    config.setdefault("project", {})
    config["project"].setdefault("name", "Prep Sheet")
    config["project"].setdefault("locale", "IN")
    config["project"].setdefault("currency", "INR")
    return config


def load_menu(menu_path: str | Path | None = None) -> list[dict]:
    menu_file = Path(menu_path) if menu_path else ROOT_DIR / "menu.example.toml"
    menu = _read_toml(menu_file)
    return menu.get("items", [])


def load_env_file(env_path: str | Path | None = None) -> dict[str, str]:
    env_file = Path(env_path) if env_path else ROOT_DIR / ".env"
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            if value.startswith(("'", '"')) and value.endswith(value[0]):
                value = value[1:-1]
            values[key] = value
    known_keys = [
        "TINKER_API_KEY",
        "TABPFN_TOKEN",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "TELEGRAM_BOT_TOKEN",
        "ELEVENLABS_API_KEY",
        "FORECAST_PROVIDER",
        "BRIEF_PROVIDER",
        "MODEL_PROVIDER",
    ]
    for key in known_keys:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def load_dotenv(env_path: str | Path | None = None) -> dict[str, str]:
    """Load local .env values without overriding variables already in the process."""
    env_file = Path(env_path) if env_path else ROOT_DIR / ".env"
    file_values = load_env_file(env_file)
    for key, value in file_values.items():
        os.environ.setdefault(key, value)
    return load_env_file(env_file)
