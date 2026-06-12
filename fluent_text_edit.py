"""FluentTextEdit -- QTextEdit with a display/edit mode toggle and Fluent border.

Visually transitions between two states:

    Edit mode (display_mode=False, default):
        Rounded border, hover highlight, blue focus accent, editable cursor.

    Display mode (display_mode=True):
        No border, transparent background, arrow cursor, read-only.
        Looks and behaves like a plain text label.

Unlike FluentLineEdit, this widget uses dynamic QSS for the border because
QTextEdit is a QAbstractScrollArea -- a custom ``QPainter(self)`` in
paintEvent conflicts with QStyleSheetStyle on Windows.

Right-clicking shows a Fluent-styled context menu instead of the native Qt
one -- requires ``fluent_context_menu.py`` next to this file.

Usage::

    edit = FluentTextEdit(dark_mode=True, parent=self)

    edit.display_mode = True   # label-like
    edit.display_mode = False  # full editable field

Features
--------
-   Rounded border via dynamic QSS, hover + focus states.
-   ``display_mode`` -- transparent, read-only, label-like view state.
-   ``editing_finished`` signal on focus-out.
-   Fluent-styled right-click menu (bundled ``FluentContextMenu``).
-   Light / dark theme via a single ``dark_mode`` bool.
-   No external dependencies beyond PySide6 >= 6.7.

License
-------
MIT -- see LICENSE file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget

from fluent_context_menu import FluentContextMenu


# ---------------------------------------------------------------------------
# Theme colour bundles
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Theme:
    """Immutable colour bundle for FluentTextEdit states."""

    bg: QColor
    bg_hover: QColor
    border: QColor
    border_hover: QColor
    border_focus: QColor
    text: QColor
    placeholder: QColor

    border_radius: int = 5


DARK = _Theme(
    bg=QColor(38, 40, 44),
    bg_hover=QColor(51, 53, 59),
    border=QColor(64, 67, 74),
    border_hover=QColor(76, 79, 86),
    border_focus=QColor(56, 113, 225),
    text=QColor(209, 211, 217),
    placeholder=QColor(95, 98, 105),
)

LIGHT = _Theme(
    bg=QColor(255, 255, 255),
    bg_hover=QColor(237, 239, 242),
    border=QColor(209, 211, 217),
    border_hover=QColor(181, 183, 189),
    border_focus=QColor(56, 113, 225),
    text=QColor(0, 0, 0),
    placeholder=QColor(159, 162, 168),
)


# ---------------------------------------------------------------------------
# QSS templates
# ---------------------------------------------------------------------------

_EDIT_QSS = """\
QTextEdit {{
    background: {bg};
    border: {bw}px solid {border};
    border-radius: {radius}px;
    padding: 4px;
}}"""

_DISPLAY_QSS = "QTextEdit { background: transparent; border: none; padding: 4px; }"


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class FluentTextEdit(QTextEdit):
    """Theme-aware QTextEdit with a display / edit mode toggle.

    Args:
        dark_mode: ``True`` for dark theme, ``False`` for light.  Can be
                   changed at any time via the ``dark_mode`` property.
        parent:    Optional parent widget.

    In **edit mode** the widget shows a rounded border (hover + focus
    states included) via dynamic QSS.  In **display mode** it becomes
    visually transparent and read-only.
    """

    editing_finished = Signal()

    def __init__(
        self,
        dark_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentTextEdit")

        self._dark_mode: bool = dark_mode
        self._display_mode: bool = False
        self._hovered: bool = False
        self._updating_style: bool = False

        # Disable native frame so we own the border entirely.
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        # Enable hover events so enterEvent / leaveEvent fire reliably.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

        # QTextEdit uses a QTextDocument internally; set document margins.
        self.document().setDocumentMargin(8)

        self._apply_theme()
        self._apply_border_style()

    # -- Theme --------------------------------------------------------------

    @property
    def dark_mode(self) -> bool:
        """Current theme flag.  Setting it re-themes and repaints."""
        return self._dark_mode

    @dark_mode.setter
    def dark_mode(self, value: bool) -> None:
        if self._dark_mode != value:
            self._dark_mode = value
            self._apply_theme()
            self._apply_border_style()

    def _theme_obj(self) -> _Theme:
        return DARK if self._dark_mode else LIGHT

    # -- display_mode property ----------------------------------------------

    @property
    def display_mode(self) -> bool:
        """When True the widget looks like a label and ignores input."""
        return self._display_mode

    @display_mode.setter
    def display_mode(self, value: bool) -> None:
        if self._display_mode == value:
            return
        self._display_mode = value
        if value:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.setReadOnly(True)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        else:
            self.unsetCursor()
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            self.setReadOnly(False)
            self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._apply_border_style()

    # -- Context menu -------------------------------------------------------

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Show a Fluent-styled context menu with standard edit actions."""
        menu = FluentContextMenu(dark_mode=self._dark_mode)
        has_sel = self.textCursor().hasSelection()
        can_paste = bool(QApplication.clipboard().text())

        if not self.isReadOnly():
            menu.add_item(
                "Undo", shortcut="Ctrl+Z",
                callback=self.undo, enabled=self.document().isUndoAvailable(),
            )
            menu.add_item(
                "Redo", shortcut="Ctrl+Y",
                callback=self.redo, enabled=self.document().isRedoAvailable(),
            )
            menu.add_separator()
            menu.add_item(
                "Cut", shortcut="Ctrl+X",
                callback=self.cut, enabled=has_sel,
            )
        menu.add_item(
            "Copy", shortcut="Ctrl+C",
            callback=self.copy, enabled=has_sel,
        )
        if not self.isReadOnly():
            menu.add_item(
                "Paste", shortcut="Ctrl+V",
                callback=self.paste, enabled=can_paste,
            )
        menu.add_separator()
        menu.add_item(
            "Select All", shortcut="Ctrl+A",
            callback=self.selectAll, enabled=bool(self.toPlainText()),
        )
        menu.show_at(event.globalPos())

    # -- Theme helpers ------------------------------------------------------

    def _apply_theme(self) -> None:
        """Push text / placeholder colours into the QPalette."""
        t = self._theme_obj()
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Text, t.text)
        pal.setColor(QPalette.ColorRole.PlaceholderText, t.placeholder)
        self.setPalette(pal)

    def _apply_border_style(self) -> None:
        """Set the QSS for the current display_mode / hover / focus state."""
        self._updating_style = True
        try:
            self._do_apply_border_style()
        finally:
            self._updating_style = False

    def _do_apply_border_style(self) -> None:
        if self._display_mode:
            self.setStyleSheet(_DISPLAY_QSS)
            return

        t = self._theme_obj()
        focused = self.hasFocus()

        if focused:
            border_color = t.border_focus
            border_width = 2
        elif self._hovered:
            border_color = t.border_hover
            border_width = 1
        else:
            border_color = t.border
            border_width = 1

        bg = t.bg_hover if self._hovered else t.bg

        self.setStyleSheet(_EDIT_QSS.format(
            bg=bg.name(),
            bw=border_width,
            border=border_color.name(),
            radius=t.border_radius,
        ))

    # -- Qt events ----------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        if not self._display_mode:
            self._apply_border_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        if not self._display_mode:
            self._apply_border_style()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        if not self._display_mode:
            self._apply_border_style()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        if not self._display_mode:
            self._apply_border_style()
            self.editing_finished.emit()
        super().focusOutEvent(event)
