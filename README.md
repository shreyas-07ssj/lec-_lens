# LecLens — setup guide

A local, offline screenshot note-taker: region screenshot + local VLM via
Ollama = Markdown/LaTeX notes appended to `lecture_notes.md`.

Everything runs on your own machine. No screenshots or text ever leave your
computer.

---

## 0. Prerequisites

- NVIDIA GPU + recent driver is recommended for Ollama, but CPU-only works too.
- Python 3.10–3.11 recommended.
- [Ollama](https://ollama.com) installed.

## 1. Install Ollama and pull the vision model

```bash
# after installing Ollama for your OS (need Ollama >= 0.12.7 for Qwen3-VL):
ollama pull qwen3-vl:8b
# more VRAM available / want higher quality:
# ollama pull qwen3-vl:30b   (set OLLAMA_MODEL = "qwen3-vl:30b" in config.py)
# older/lighter fallback:
# ollama pull llava:7b       (set OLLAMA_MODEL = "llava:7b" in config.py)

ollama serve   # if it isn't already running as a service
```

Check your Ollama version if the pull fails:
```bash
ollama --version   # needs to be >= 0.12.7
```

Verify it's reachable:
```bash
curl http://localhost:11434/api/tags
```

## 2. Python environment

```bash
cd leclens
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The first Ollama request loads the vision model into memory, so the initial
generation can take longer than later requests.

## 3. Global hotkey permissions

The `keyboard` library needs elevated privileges to hook global keys:
- **Linux**: run with `sudo` or add your user to the `input` group
  (`sudo usermod -aG input $USER`, then log out/in).
- **Windows**: run your terminal/IDE as Administrator.
- **macOS**: grant Accessibility permissions to your terminal in
  System Settings → Privacy & Security → Accessibility.

## 4. Run it

```bash
python main.py
```

You should see a tray icon and a "LecLens is running" notification.
Use it as follows:
1. Press **Ctrl+Shift+L**.
2. Your screen dims; drag a box around the slide/code/graph.
3. Type specific writing instructions in the chatbox, then press **Ctrl+Enter**.
4. Review, edit, regenerate, save, or discard the generated note.

## 5. Tuning

All in `config.py`:
| Setting | Effect |
|---|---|
| `OLLAMA_MODEL` | `qwen3-vl:8b` default; `qwen3-vl:30b`/`32b` for more accuracy, `llava:7b` as a lighter fallback |
| `OLLAMA_TIMEOUT_SECONDS` | Maximum time allowed for note generation |
| `OLLAMA_MAX_TOKENS` | Maximum length of the generated note |
| `SYSTEM_PROMPT` | Adjust note style / strictness of LaTeX enforcement |

## 6. Troubleshooting

- **Hotkey doesn't fire**: check the permissions step above — this is by far
  the most common issue on Linux/macOS.
- **Ollama call times out or errors**: confirm `ollama serve` is running and
  `ollama list` shows your model; try `curl` the endpoint manually.
- **Screenshot is black on Wayland**: on Ubuntu GNOME install
  `gnome-screenshot` (`sudo apt install gnome-screenshot`) and restart LecLens.
  Otherwise use an Xorg session.
- **CUDA out of memory**: use a smaller Ollama vision model such as `llava:7b`.
- **Overlay doesn't cover all monitors**: this is handled via
  `QGuiApplication.screens()` — if it's still off, check your OS display
  scaling settings.

## 7. Project layout

```
leclens/
├── config.py            # all tunables in one place
├── overlay.py             # screenshot selector + instruction chatbox
├── ai_orchestrator.py     # screenshot + instruction VLM synthesis
├── main.py                 # tray app, hotkey, wiring
├── requirements.txt
└── lecture_notes.md        # generated — your running notes file
```

## Suggested next steps once this is working

- Add a small "processing..." toast overlay instead of relying only on the
  tray notification (some tray implementations are easy to miss).
- Batch multiple captures into a single end-of-lecture summary pass.
- Swap LLaVA for a newer local VLM (e.g. `moondream` for speed, or
  `llama3.2-vision` via Ollama) if you want to compare quality/speed.
