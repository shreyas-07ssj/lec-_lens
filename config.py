"""
LecLens configuration.
Tweak these values instead of hunting through the modules.
"""

import os

# ---------- Paths ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

IMAGE_TEMP_PATH = os.path.join(TEMP_DIR, "slide_capture.png")
NOTES_OUTPUT_PATH = os.path.join(BASE_DIR, "lecture_notes.md")

# ---------- Hotkey (Module B trigger) ----------
HOTKEY = "ctrl+shift+l"

# ---------- Vision-Language Model (Ollama) ----------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3-vl:8b"      # requires Ollama >= 0.12.7
                                   # bigger/slower: "qwen3-vl:30b" / "qwen3-vl:32b"
                                   # or fall back to "llava:13b" / "llava:7b"
OLLAMA_TIMEOUT_SECONDS = 600
OLLAMA_MAX_TOKENS = 2048
OLLAMA_THINK = False

SYSTEM_PROMPT = """You are LecLens, a note-taking assistant embedded in a live lecture.
You are given a screenshot of a slide, code editor, or diagram.

Your job: produce a single, well-structured Markdown note based on the image
and the user's writing instructions. Rules:

- Use Markdown headings/bullets for structure.
- Any mathematical notation MUST be written as LaTeX, using $$ ... $$ for
  display equations and $ ... $ for inline math. Never describe math in prose
  if it can be written as an equation.
- If the image contains code, reproduce it in a fenced code block with the
  correct language tag, and briefly explain what it does.
- If the image contains a diagram/graph with no text equivalent, describe its
  structure concisely (axes, key points, relationships) and connect it to what
  the speaker said.
- If the user provides ADDITIONAL INSTRUCTIONS, treat them as a priority
  request layered on top of everything above — e.g. add a worked example,
  simplify the explanation, focus on a specific part of the image, add an
  analogy. Do not ignore or water down the additional instructions.
- Keep it tight. No filler, no "As an AI...", no repeating these instructions.
- Output ONLY the Markdown note, nothing else.
"""
