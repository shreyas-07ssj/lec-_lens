"""
Note preview dialog.
------------------------
Shown after the VLM generates a note, before anything is written to
lecture_notes.md. Lets the user:
  - read/edit the generated Markdown directly
    - tweak the instructions and Regenerate (re-runs the VLM call)
  - Save (commits the current text to lecture_notes.md) or Discard

This is a normal (non-frameless) QDialog - unlike the capture overlay, the
user needs to comfortably read/edit/resize it, so standard window chrome is
the right call here.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont


class NotePreviewDialog(QDialog):
    # Emitted with the (possibly hand-edited) note text the user wants saved.
    save_requested = pyqtSignal(str)
    # Emitted with the new instructions text when Regenerate is clicked.
    regenerate_requested = pyqtSignal(str)
    # Emitted if the user discards (button or closing the window).
    discarded = pyqtSignal()

    def __init__(self, note_text: str, instructions: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("LecLens — Review Note")
        self.setMinimumSize(640, 460)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._resolved = False  # guards against double-emitting on close

        layout = QVBoxLayout(self)

        label = QLabel("Generated note — edit anything you like before saving:")
        layout.addWidget(label)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(note_text)
        self.text_edit.setFont(QFont("Monospace", 10))
        layout.addWidget(self.text_edit, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        regen_row = QHBoxLayout()
        self.instr_edit = QLineEdit(instructions)
        self.instr_edit.setPlaceholderText(
            "Instructions for regeneration, e.g. \"add a different example\""
        )
        self.regen_button = QPushButton("Regenerate")
        self.regen_button.clicked.connect(self._on_regenerate)
        regen_row.addWidget(self.instr_edit, stretch=1)
        regen_row.addWidget(self.regen_button)
        layout.addLayout(regen_row)

        button_row = QHBoxLayout()
        self.discard_button = QPushButton("Discard")
        self.discard_button.clicked.connect(self._on_discard)
        self.save_button = QPushButton("Save to lecture_notes.md")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        button_row.addStretch(1)
        button_row.addWidget(self.discard_button)
        button_row.addWidget(self.save_button)
        layout.addLayout(button_row)

    # ---------- external API (called from main.py on the GUI thread) ----------
    def set_note_text(self, text: str):
        self.text_edit.setPlainText(text)

    def set_busy(self, busy: bool, message: str = ""):
        """Disable inputs and show a status message while a regenerate call
        is in flight. Call with busy=False (and no message) when it returns."""
        self.regen_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.instr_edit.setEnabled(not busy)
        self.status_label.setText(message)

    def show_error(self, message: str):
        self.status_label.setStyleSheet("color: #d9534f;")
        self.status_label.setText(message)

    # ---------- internal handlers ----------
    def _on_regenerate(self):
        self.regenerate_requested.emit(self.instr_edit.text().strip())

    def _on_save(self):
        self._resolved = True
        self.save_requested.emit(self.text_edit.toPlainText())
        self.close()

    def _on_discard(self):
        self._resolved = True
        self.discarded.emit()
        self.close()

    def closeEvent(self, event):
        # Closing via the window's [x] button with nothing yet resolved
        # counts as a discard, same as clicking the Discard button.
        if not self._resolved:
            self._resolved = True
            self.discarded.emit()
        super().closeEvent(event)
