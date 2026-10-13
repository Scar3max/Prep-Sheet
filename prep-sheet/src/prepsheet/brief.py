from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any


NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
FALLBACK_GEMINI_MODEL = "gemini-3.8-flash"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _extract_numbers(text: str) -> set[str]:
    return set(NUMBER_PATTERN.findall(text))


def _request_gemini_model(prompt: str, api_key: str, model: str) -> tuple[str | None, str | None, int | None]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 256},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            response_body = json.loads(exc.read().decode("utf-8"))
            detail = response_body.get("error", {}).get("message", "")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = ""
        detail = " ".join(str(detail).replace(api_key, "[redacted]").split())[:240]
        reason = f"{model} HTTP {exc.code}"
        if detail:
            reason += f": {detail}"
        return None, reason, exc.code
    except Exception as exc:
        detail = " ".join(str(exc).replace(api_key, "[redacted]").split())[:240]
        reason = f"{model} call failed ({type(exc).__name__})"
        if detail:
            reason += f": {detail}"
        return None, reason, None

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        if not isinstance(text, str) or not text.strip():
            return None, f"{model} returned empty generated text", None
        return text.strip(), None, None
    except (KeyError, IndexError, TypeError):
        return None, f"{model} response did not contain generated text", None


def _gemini_brief(prompt: str) -> tuple[str | None, str | None]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY is not configured"

    primary_model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    models = list(dict.fromkeys((primary_model, FALLBACK_GEMINI_MODEL)))
    failures: list[str] = []

    for model in models:
        for attempt in range(2):
            text, error, status = _request_gemini_model(prompt, api_key, model)
            if text:
                return text, None
            failures.append(error or f"{model} returned no text")
            if status not in RETRYABLE_HTTP_STATUS or attempt == 1:
                break
            time.sleep(1)

    return None, "Gemini provider attempts failed: " + " | ".join(failures)


def number_guardrail(brief: str, structured_input: dict[str, Any]) -> str:
    def collect_numbers(value: Any) -> set[str]:
        if isinstance(value, (int, float)):
            return {str(value)}
        if isinstance(value, str):
            return _extract_numbers(value)
        if isinstance(value, dict):
            return set().union(*(collect_numbers(item) for item in value.values()))
        if isinstance(value, (list, tuple)):
            return set().union(*(collect_numbers(item) for item in value))
        return set()

    numbers = collect_numbers(structured_input)
    if not numbers:
        return brief
    text_numbers = _extract_numbers(brief)
    if text_numbers - numbers:
        return "Prepare 0 units. Weather and demand signals are below the threshold."
    return brief


def generate_brief_with_status(
    prep_summary: dict[str, Any], provider: str | None = None
) -> tuple[str, dict[str, str]]:
    provider = (provider or os.getenv("BRIEF_PROVIDER") or os.getenv("MODEL_PROVIDER") or "template").lower()
    lines: list[str] = []
    for key, value in prep_summary.items():
        if isinstance(value, dict):
            qty = value.get("qty")
            reasons = value.get("reasons", [])
            if qty is not None:
                lines.append(f"{key}: prepare {qty} units. Reason: {', '.join(reasons[:2]) if reasons else 'recent sales mix'}.")
            else:
                lines.append(f"{key}: check demand. Reason: {', '.join(reasons[:2]) if reasons else 'recent trends'}.")
    fallback_brief = "\n".join(lines) if lines else "Prepare based on demand and recent sales patterns."
    if provider in {"gemini", "google", "llm", "generative"}:
        prompt = (
            "You are a cafe prep planner. Write a short, practical morning brief "
            "for the following prep summary. Keep it concise and only use the numbers provided.\n\n"
            f"{json.dumps(prep_summary, sort_keys=True)}"
        )
        live_brief, error = _gemini_brief(prompt)
        if live_brief:
            safe_brief = number_guardrail(live_brief, prep_summary)
            if safe_brief != live_brief:
                return fallback_brief, {
                    "requested": "gemini",
                    "used": "local_template",
                    "status": "fallback",
                    "reason": "Gemini response failed the numeric guardrail",
                }
            return safe_brief, {"requested": "gemini", "used": "gemini", "status": "success"}
        return number_guardrail(fallback_brief, prep_summary), {
            "requested": "gemini",
            "used": "local_template",
            "status": "fallback",
            "reason": error or "Gemini did not return generated text",
        }
    if provider != "template":
        return number_guardrail(fallback_brief, prep_summary), {
            "requested": provider,
            "used": "local_template",
            "status": "fallback",
            "reason": "Unknown brief provider",
        }
    return number_guardrail(fallback_brief, prep_summary), {
        "requested": "template",
        "used": "local_template",
        "status": "local",
    }


def generate_brief(prep_summary: dict[str, Any], provider: str | None = None) -> str:
    brief, _ = generate_brief_with_status(prep_summary, provider=provider)
    return brief
