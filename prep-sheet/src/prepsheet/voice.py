from __future__ import annotations


def synthesize_voice_note(text: str, output_path: str) -> str:
    """Stub for optional ElevenLabs integration. The function should be replaced by a real API call when a key is provided."""
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return output_path
