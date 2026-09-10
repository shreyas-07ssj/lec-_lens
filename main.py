"""
LecLens entry point (pynput-based global hotkey).
Run with: python main.py

Flow:
  1. Start the rolling audio buffer (Module A) in the background.
  2. Register a global hotkey via pynput (default Ctrl+Shift+L).
  3. On hotkey press:
       a. Freeze the audio buffer to a .wav IMMEDIATELY (before showing the
          overlay), so the 30s window isn't shifted by however long the
          user takes to drag a selection box.
       b. Show the transparent region-select overlay (Module B), which also
          collects optional "extra instructions" text.
       c. Transcribe + generate a note on a worker thread (Module C).
       d. Show a preview dialog with the generated note - the user can edit
          it by hand, Regenerate (re-runs just the VLM call with tweaked
          instructions), or Discard. Nothing touches lecture_notes.md until
          they click Save.
  4. Lives in the system tray; right-click to quit.

Threading note: pynput's GlobalHotKeys listener and the AI pipeline worker
both run on plain Python threads, NOT the Qt GUI thread. Any call that
touches a Qt object (QSystemTrayIcon.showMessage, creating/showing a
QWidget, starting a QTimer, etc.) from one of those threads will either
silently misbehave or throw "QObject::startTimer: Timers cannot be started
from another thread". Every hop back to Qt-land goes through a pyqtSignal.
"""

import sys
import threading
import os

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from pynput import keyboard

import config
from overlay import ScreenRegionSelector
from preview import NotePreviewDialog
from ai_orchestrator import synthesize_note, append_note


def _make_tray_icon() -> QIcon:
    """Generate a simple dot icon at runtime so we don't need an asset file."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor(0, 200, 255))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 24, 24)
    painter.end()
    return QIcon(pixmap)


class LecLensApp(QObject):
    # Every one of these crosses from a background thread onto the GUI
    # thread. Never call self.tray / self._selector / a dialog directly
    # from a thread other than the one running app.exec() - always go
    # through a signal.
    show_overlay_requested = pyqtSignal()
    capture_started = pyqtSignal()
    note_ready = pyqtSignal(str, str, str)                    # note, image_path, instructions
    generation_failed = pyqtSignal(str)                       # error message
    regenerate_finished = pyqtSignal(object, str)              # dialog, new note text
    regenerate_failed = pyqtSignal(object, str)                # dialog, error message
    note_saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self._selector = None        # keep a reference so it isn't GC'd mid-drag
        self._preview_dialog = None  # keep a reference so it isn't GC'd while open
        self._hotkey_listener = None

        self._setup_tray()
        self._setup_signals()

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(_make_tray_icon())
        self.tray.setToolTip(f"LecLens — press {config.HOTKEY} to capture")

        menu = QMenu()
        status_action = menu.addAction("LecLens is running")
        status_action.setEnabled(False)
        menu.addSeparator()
        open_notes_action = menu.addAction("Open lecture_notes.md")
        open_notes_action.triggered.connect(self._open_notes)
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.quit)

        self.tray.setContextMenu(menu)
        self.tray.show()
        self.tray.showMessage(
            "LecLens", f"Running in background. Press {config.HOTKEY} to capture.",
            QSystemTrayIcon.MessageIcon.Information, 3000,
        )

    def _setup_signals(self):
        # These slots run on the GUI thread (Qt guarantees this for
        # queued connections across threads), so it's safe to touch
        # self.tray / self._selector / self._preview_dialog inside them.
        self.show_overlay_requested.connect(self._show_overlay)
        self.capture_started.connect(
            lambda: self.tray.showMessage(
                "LecLens", "Transcribing + generating note...",
                QSystemTrayIcon.MessageIcon.Information, 2000,
            )
        )
        self.note_ready.connect(self._show_preview)
        self.generation_failed.connect(
            lambda err: self.tray.showMessage(
                "LecLens", f"Capture failed: {err}",
                QSystemTrayIcon.MessageIcon.Warning, 5000,
            )
        )
        self.regenerate_finished.connect(
            lambda dlg, note: (dlg.set_note_text(note), dlg.set_busy(False))
        )
        self.regenerate_failed.connect(
            lambda dlg, err: (dlg.set_busy(False), dlg.show_error(f"Regenerate failed: {err}"))
        )
        self.note_saved.connect(
            lambda: self.tray.showMessage(
                "LecLens", "Note added to lecture_notes.md",
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )
        )

    def _open_notes(self):
        import os
        import subprocess
        path = config.NOTES_OUTPUT_PATH
        if not os.path.exists(path):
            open(path, "a").close()
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            os.startfile(path)  # Windows

    # ---------- capture flow ----------
    def _on_hotkey_pressed(self):
        """Runs on pynput's listener thread and requests a screenshot."""
        self.show_overlay_requested.emit()

    def _show_overlay(self):
        """Runs on the GUI thread. Safe to construct/show a QWidget here."""
        self._selector = ScreenRegionSelector(
            on_capture=self._on_region_selected
        )
        self._selector.showFullScreen()

    def _on_region_selected(self, png_path, instructions):
        if png_path is None:
            return  # user cancelled
        self.capture_started.emit()
        threading.Thread(
            target=self._generate_note, args=(png_path, instructions or ""),
            daemon=True,
        ).start()

    def _generate_note(self, image_path, instructions):
        """Generate from the screenshot without writing until confirmed."""
        try:
            note = synthesize_note(image_path, instructions)
            self.note_ready.emit(note, image_path, instructions)
        except Exception as e:
            print(f"[main] generation error: {e}")
            self.generation_failed.emit(str(e))

    # ---------- preview dialog ----------
    def _show_preview(self, note, image_path, instructions):
        """Runs on the GUI thread (queued connection from note_ready)."""
        dlg = NotePreviewDialog(note_text=note, instructions=instructions)
        dlg.save_requested.connect(self._save_note)
        dlg.regenerate_requested.connect(
            lambda new_instructions: self._regenerate(dlg, image_path, new_instructions)
        )
        dlg.discarded.connect(self._discard_preview)
        self._preview_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _save_note(self, final_text):
        """Runs on the GUI thread (button click). The file write itself is
        tiny, so no need to bounce this to a worker thread."""
        try:
            append_note(final_text)
            self.note_saved.emit()
        except Exception as e:
            print(f"[main] save error: {e}")
            self.generation_failed.emit(str(e))
        finally:
            self._preview_dialog = None

    def _discard_preview(self):
        self._preview_dialog = None

    def _regenerate(self, dlg, image_path, new_instructions):
        dlg.set_busy(True, "Regenerating...")
        threading.Thread(
            target=self._regenerate_worker, args=(dlg, image_path, new_instructions),
            daemon=True,
        ).start()

    def _regenerate_worker(self, dlg, image_path, new_instructions):
        """Runs the screenshot-only VLM call on a worker thread."""
        try:
            note = synthesize_note(image_path, new_instructions)
            self.regenerate_finished.emit(dlg, note)
        except Exception as e:
            print(f"[main] regenerate error: {e}")
            self.regenerate_failed.emit(dlg, str(e))

    def quit(self):
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
        self.app.quit()

    def run(self):
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            print("[main] Warning: global pynput hotkeys use X11 and may not "
                  "work in native Wayland apps. Use an Xorg session for "
                  "reliable Ctrl+Shift+L capture.")

        # pynput's GlobalHotKeys runs its own listener thread internally;
        # the callback fires on that thread, not the GUI thread.
        self._hotkey_listener = keyboard.GlobalHotKeys({
            _to_pynput_hotkey(config.HOTKEY): self._on_hotkey_pressed
        }, on_error=self._on_hotkey_error)
        self._hotkey_listener.start()

        print(f"[main] LecLens ready. Hotkey: {config.HOTKEY}")
        sys.exit(self.app.exec())

    @staticmethod
    def _on_hotkey_error(error):
        print(f"[main] hotkey listener error: {error}", file=sys.stderr)


def _to_pynput_hotkey(hotkey_str: str) -> str:
    """Convert a 'ctrl+shift+l' style string (matches config.HOTKEY, and the
    `keyboard` library's format) into pynput's '<ctrl>+<shift>+l' format."""
    modifier_names = {"ctrl", "shift", "alt", "cmd", "super"}
    parts = hotkey_str.lower().split("+")
    return "+".join(f"<{p}>" if p in modifier_names else p for p in parts)


if __name__ == "__main__":
    LecLensApp().run()
