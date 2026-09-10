"""
Module B: The Transparent UI Overlay
--------------------------------------
A full-screen, frameless overlay that lets the user drag a crosshair box
around a slide / code editor / graph. On release, the region freezes and a
small text box appears so the user can optionally type extra instructions
("add an example", "explain this simpler", "focus on the left column") that
get passed through to the AI orchestrator alongside the image.

Design note - why this doesn't rely on WA_TranslucentBackground:
Qt's translucent-window attribute only actually renders as translucent when
your window manager/compositor supports it. On plenty of Linux setups
(tiling WMs, non-composited X11, some Wayland sessions) it doesn't, and the
"translucent" dark overlay paints as solid opaque black instead. To sidestep
that entirely, we grab a real screenshot of the desktop BEFORE showing the
overlay, use that screenshot as the widget's own background, and paint the
dark dimming tint directly onto that image in software.

Usage:
    overlay = ScreenRegionSelector(on_capture=my_callback)
    overlay.showFullScreen()

`on_capture(image_path, extra_instructions)` fires once, where:
  - image_path is the saved PNG path, or None if the user cancelled
    (Escape at any point, or drew a degenerate box).
  - extra_instructions is the (possibly empty) text the user typed, or
    None when image_path is None.
"""

from PyQt6.QtWidgets import QApplication, QWidget, QTextEdit
from PyQt6.QtGui import QPainter, QColor, QPen, QCursor, QGuiApplication, QPixmap
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal

import os
import shutil
import subprocess

import config


_WAYLAND_PORTAL_SCRIPT = r'''
import dbus
import dbus.mainloop.glib
import shutil
import sys
import urllib.parse
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
loop = GLib.MainLoop()

def response(code, results, **kwargs):
    if int(code) == 0:
        uri = str(results['uri'])
        source = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
        shutil.copyfile(source, sys.argv[1])
    loop.quit()

bus.add_signal_receiver(
    response, 'Response', 'org.freedesktop.portal.Request', path_keyword='path'
)
portal = bus.get_object(
    'org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop'
)
portal.Screenshot(
    '', {'interactive': dbus.Boolean(False)},
    dbus_interface='org.freedesktop.portal.Screenshot'
)
loop.run()
'''


def _capture_wayland_portal(path: str) -> bool:
    result = subprocess.run(
        ['/usr/bin/python3', '-c', _WAYLAND_PORTAL_SCRIPT, path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and os.path.exists(path)


def _grab_virtual_desktop() -> tuple[QPixmap, QRect]:
    """Grab every screen and composite them into a single pixmap positioned
    to match the virtual desktop layout. QScreen.grabWindow() only captures
    that screen's own pixels using that screen's local coordinate origin, so
    for multi-monitor setups each screen has to be grabbed separately and
    placed at its geometry offset.
    """
    is_wayland = (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )
    if is_wayland:
        path = os.path.join(config.TEMP_DIR, "desktop_capture.png")
        try:
            if _capture_wayland_portal(path):
                screenshot = QPixmap(path)
                if not screenshot.isNull():
                    return screenshot, QRect(0, 0, screenshot.width(), screenshot.height())
        except (OSError, subprocess.SubprocessError):
            pass

        for command in (("gnome-screenshot", "-f", path), ("grim", path)):
            if not shutil.which(command[0]):
                continue
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                screenshot = QPixmap(path)
                if not screenshot.isNull():
                    return screenshot, QRect(0, 0, screenshot.width(), screenshot.height())

    screens = QGuiApplication.screens()
    virtual_geo = QRect()
    for screen in screens:
        virtual_geo = virtual_geo.united(screen.geometry())

    combined = QPixmap(virtual_geo.size())
    combined.fill(Qt.GlobalColor.black)
    painter = QPainter(combined)
    for screen in screens:
        geo = screen.geometry()
        shot = screen.grabWindow(0)
        target = QPoint(geo.x() - virtual_geo.x(), geo.y() - virtual_geo.y())
        painter.drawPixmap(target, shot)
    painter.end()

    return combined, virtual_geo


class _InstructionInput(QTextEdit):
    """Multiline instruction box with Ctrl+Enter submit and Escape cancel."""
    submitted = pyqtSignal(str)
    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.submitted.emit(self.toPlainText().strip())
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class ScreenRegionSelector(QWidget):
    def __init__(self, on_capture=None):
        super().__init__()
        self.on_capture = on_capture
        self._origin = QPoint()
        self._current = QPoint()
        self._selecting = False      # True while actively dragging
        self._locked_rect = None     # set once the box is released
        self._instruction_input = None

        # Grab the real screen content FIRST, before this window exists and
        # before anything is dimmed - this becomes our background image.
        self._background, self._virtual_geo = _grab_virtual_desktop()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # avoid taskbar entry
        )
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setGeometry(self._virtual_geo)

    # ---------- painting ----------
    def paintEvent(self, event):
        painter = QPainter(self)

        # 1. draw the real screenshot as the base layer
        painter.drawPixmap(0, 0, self._background)

        # 2. dim everything with a translucent black wash, painted in
        #    software on top of the screenshot pixels
        painter.fillRect(self.rect(), QColor(0, 0, 0, 130))

        # 3. within the current/locked selection, redraw the ORIGINAL
        #    (undimmed) screenshot pixels to punch a bright "hole"
        active_rect = self._locked_rect or (
            QRect(self._origin, self._current).normalized() if self._selecting else None
        )
        if active_rect:
            painter.drawPixmap(active_rect, self._background, active_rect)
            pen = QPen(QColor(0, 200, 255), 2)
            painter.setPen(pen)
            painter.drawRect(active_rect)

    # ---------- mouse handling ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._locked_rect is not None:
                self._locked_rect = None
                if self._instruction_input is not None:
                    self._instruction_input.hide()
                    self._instruction_input.deleteLater()
                    self._instruction_input = None
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._locked_rect is not None:
            return
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            rect = QRect(self._origin, self._current).normalized()
            if rect.width() > 5 and rect.height() > 5:
                self._lock_selection(rect)
            else:
                self._cancel(None)

    def keyPressEvent(self, event):
        # Only reaches here while dragging (before the instruction box
        # exists and steals focus) - Escape during drag cancels outright.
        if event.key() == Qt.Key.Key_Escape:
            self._cancel(None)

    # ---------- post-selection: show the instruction text box ----------
    def _lock_selection(self, rect: QRect):
        self._locked_rect = rect
        self.update()
        self._show_instruction_input(rect)

    def _show_instruction_input(self, rect: QRect):
        box = _InstructionInput(self)
        box.setPlaceholderText(
            "Tell LecLens exactly how to write the note, e.g. summarize in "
            "5 bullets, explain the diagram simply, or include key formulas. "
            "Drag again to change the selection. Ctrl+Enter to generate, "
            "Esc to cancel"
        )
        box.setStyleSheet(
            "QLineEdit {"
            "  background-color: rgba(20, 20, 20, 235);"
            "  color: #eaeaea;"
            "  border: 1px solid rgb(0, 200, 255);"
            "  border-radius: 6px;"
            "  padding: 8px 10px;"
            "  font-size: 13px;"
            "}"
        )

        width = max(340, min(rect.width(), 560))
        height = 92
        x = rect.center().x() - width // 2
        # prefer just below the selection; flip above if there's no room
        y = rect.bottom() + 12
        if y + height > self._virtual_geo.bottom():
            y = rect.top() - height - 12
        # clamp fully inside the virtual desktop
        x = max(self._virtual_geo.left() + 8,
                min(x, self._virtual_geo.right() - width - 8))
        y = max(self._virtual_geo.top() + 8,
                min(y, self._virtual_geo.bottom() - height - 8))

        box.setGeometry(x, y, width, height)
        box.submitted.connect(self._finalize)
        box.cancelled.connect(lambda: self._cancel(self._locked_rect))
        box.show()
        box.setFocus()
        self._instruction_input = box

    def _finalize(self, extra_instructions: str):
        rect = self._locked_rect
        self.hide()
        path = self._save_region(rect)
        if self.on_capture:
            self.on_capture(path, extra_instructions)
        self.close()

    def _cancel(self, _rect):
        self.hide()
        if self.on_capture:
            self.on_capture(None, None)
        self.close()

    # ---------- capture ----------
    def _save_region(self, rect: QRect, path=None) -> str:
        path = path or config.IMAGE_TEMP_PATH
        cropped = self._background.copy(rect)
        cropped.save(path, "PNG")
        print(f"[overlay] region captured -> {path} ({rect.width()}x{rect.height()})")
        return path


def launch_selector(on_capture=None):
    """Convenience entrypoint: creates (if needed) a QApplication and shows
    the selector. Safe to call from a running Qt app (e.g. from main.py's
    tray icon) since it reuses QApplication.instance() when present."""
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication([])

    selector = ScreenRegionSelector(on_capture=on_capture)
    selector.showFullScreen()

    if owns_app:
        app.exec()
    return selector


if __name__ == "__main__":
    # Quick manual test: `python overlay.py` -> drag a box, type something
    # (or don't), press Enter, check temp/slide_capture.png + console output.
    launch_selector(on_capture=lambda p, instr: print("captured:", p, "| instructions:", instr))
