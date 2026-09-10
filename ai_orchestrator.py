"""
Module C: The Multimodal AI Orchestrator
-------------------------------------------
Given a .png (selected screen region) and writing instructions:
    1. Send the screenshot + writing instructions to a local vision model via Ollama.
    2. Enforce Markdown + LaTeX formatting via the system prompt.
    3. Return the generated note for review before it is saved.

This module is deliberately synchronous/blocking internally -- the caller
(main.py) runs generation on a background thread so the UI never stalls.
"""

import base64
import datetime
import json

import requests

import config


def _encode_image_b64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _validate_image(image_path: str):
    """Reject blank captures before sending them to the vision model."""
    from PyQt6.QtGui import QImage

    image = QImage(image_path)
    if image.isNull():
        raise RuntimeError(f"Screenshot could not be read: {image_path}")

    sample = image.scaled(32, 32).convertToFormat(QImage.Format.Format_RGB32)
    colors = {sample.pixel(x, y) & 0x00FFFFFF
              for x in range(sample.width()) for y in range(sample.height())}
    if colors == {0}:
        raise RuntimeError(
            "Screenshot is completely black. On Wayland, install and use "
            "a native screenshot backend such as grim, or run LecLens in "
            "an Xorg session."
        )


def synthesize_note(image_path: str, extra_instructions: str = "") -> str:
    """Send a screenshot and writing instructions to Ollama."""
    _validate_image(image_path)
    user_prompt = (
        "Analyze the attached screenshot and produce the note. Even if the "
        "image is blank, always return a concise Markdown note in the response "
        "field. Do not return only internal reasoning. Keep the final note "
        "under 400 words.\n\n"
    )
    if extra_instructions.strip():
        user_prompt += (
            "ADDITIONAL INSTRUCTIONS FROM THE USER (follow these on top of "
            "the base rules — e.g. add a worked example, simplify the "
            "explanation, focus on one part of the image, etc.):\n"
            f"\"{extra_instructions.strip()}\"\n\n"
        )

    user_prompt += (
        "Using the attached image and the instructions above, produce the note "
        "as instructed."
    )

    payload = {
        "model": config.OLLAMA_MODEL,
        "system": config.SYSTEM_PROMPT,
        "prompt": user_prompt,
        "images": [_encode_image_b64(image_path)],
        "stream": False,
        "think": config.OLLAMA_THINK,
        "options": {
            "temperature": 0.2,
            "num_predict": config.OLLAMA_MAX_TOKENS,
        },
    }

    resp = requests.post(
        config.OLLAMA_URL,
        json=payload,
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    note = data.get("response", "").strip()

    if not note:
        thinking = data.get("thinking", "").strip()
        if thinking:
            note = thinking
            if note.startswith("<think>"):
                note = note[len("<think>"):].strip()
            if note.endswith("</think>"):
                note = note[:-len("</think>")].strip()

    if not note:
        raise RuntimeError("Ollama returned neither a final note nor reasoning.")

    return note


def append_note(note: str, notes_path=None):
    notes_path = notes_path or config.NOTES_OUTPUT_PATH
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(notes_path, "a", encoding="utf-8") as f:
        f.write(f"\n\n---\n### Capture @ {timestamp}\n\n{note}\n")
    print(f"[ai_orchestrator] note appended -> {notes_path}")


def process_capture(image_path: str, extra_instructions: str = "",
                     notes_path=None) -> str:
    """Generate and append a screenshot-based note."""
    note = synthesize_note(image_path, extra_instructions)
    append_note(note, notes_path)
    return note


if __name__ == "__main__":
    # Quick manual test: `python ai_orchestrator.py` using existing temp files
    result = process_capture(config.IMAGE_TEMP_PATH)
    print("\n--- NOTE ---\n", result)
