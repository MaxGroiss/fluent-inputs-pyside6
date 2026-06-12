"""FluentLineEdit -- QLineEdit with a display/edit mode toggle and Fluent border.

Visually transitions between two states:

    Edit mode (display_mode=False, default):
        Rounded border, hover highlight, blue focus accent, editable cursor.

    Display mode (display_mode=True):
        No border, transparent background, arrow cursor, read-only.
        Looks and behaves like a plain label.

Right-clicking shows a Fluent-styled context menu (cut / copy / paste / ...)
instead of the native Qt one -- requires ``fluent_context_menu.py`` next to
this file.

Usage::

    edit = FluentLineEdit(dark_mode=True, parent=self)

    edit.display_mode = True   # label-like
    edit.display_mode = False  # full editable field

Features
--------
-   Custom rounded border, hover + focus states, Win11 bottom accent line.
-   ``display_mode`` -- transparent, read-only, label-like view state.
-   Optional invalid prefix/suffix warning border.
-   Fluent-styled right-click menu (bundled ``FluentContextMenu``).
-   Light / dark theme via a single ``dark_mode`` bool.
-   No external dependencies beyond PySide6 >= 6.7.

License
-------
MIT -- see LICENSE file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPalette
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from fluent_context_menu import FluentContextMenu


# ---------------------------------------------------------------------------
# Theme colour bundles
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Theme:
    """Immutable colour bundle for FluentLineEdit states."""

    bg: QColor
    bg_hover: QColor
    border: QColor
    border_hover: QColor
    border_focus: QColor
    text: QColor
    placeholder: QColor
    warning: QColor

    border_radius: int = 5


DARK = _Theme(
    bg=QColor(38, 40, 44),
    bg_hover=QColor(51, 53, 59),
    border=QColor(64, 67, 74),
    border_hover=QColor(76, 79, 86),
    border_focus=QColor(56, 113, 225),
    text=QColor(209, 211, 217),
    placeholder=QColor(95, 98, 105),
    warning=QColor(194, 128, 19),
)

LIGHT = _Theme(
    bg=QColor(255, 255, 255),
    bg_hover=QColor(237, 239, 242),
    border=QColor(209, 211, 217),
    border_hover=QColor(181, 183, 189),
    border_focus=QColor(56, 113, 225),
    text=QColor(0, 0, 0),
    placeholder=QColor(159, 162, 168),
    warning=QColor(165, 105, 6),
)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class FluentLineEdit(QLineEdit):
    """Theme-aware QLineEdit with a display / edit mode toggle.

    Args:
        dark_mode: ``True`` for dark theme, ``False`` for light.  Can be
                   changed at any time via the ``dark_mode`` property.
        parent:    Optional parent widget.

    In **edit mode** the widget draws a rounded border (hover + focus states
    included).  In **display mode** it becomes visually transparent and
    read-only -- indistinguishable from a plain QLabel.

    All rendering is done with QPainter before delegating to the native
    QLineEdit paint path (text, cursor, clear button).
    """

    def __init__(
        self,
        dark_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentLineEdit")

        self._dark_mode: bool = dark_mode
        self._display_mode: bool = False
        self._hovered: bool = False
        self._invalid_prefixes: str = ""
        self._invalid_suffixes: str = ""

        # Disable native frame so we own the border entirely.
        self.setFrame(False)
        # Enable hover events so enterEvent / leaveEvent fire reliably.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        # Internal text padding.
        self.setTextMargins(8, 0, 8, 0)

        # When this widget lives inside a QSS-styled parent, Qt replaces the
        # platform style with QStyleSheetStyle for all descendants. Even with
        # no matching rule, QStyleSheetStyle::drawPrimitive(PE_PanelLineEdit)
        # is called inside super().paintEvent() and redraws an opaque
        # background on top of our custom QPainter work, hiding the border.
        # Declaring transparent background + no border here tells
        # QStyleSheetStyle to draw nothing, so our paintEvent controls all
        # visual output.
        self.setStyleSheet("QLineEdit { background: transparent; border: none; }")

        self._apply_theme()

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
            self.update()

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
            self.setReadOnly(True)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        else:
            self.unsetCursor()
            self.setReadOnly(False)
            self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.update()

    # -- Prefix / suffix validation -----------------------------------------

    def set_invalid_prefixes(self, chars: Sequence[str]) -> None:
        """Set characters that are invalid as the first character.

        Args:
            chars: Iterable of single-character strings, e.g. ``["_", "-"]``.
        """
        self._invalid_prefixes = "".join(chars)
        self.update()

    def set_invalid_suffixes(self, chars: Sequence[str]) -> None:
        """Set characters that are invalid as the last character.

        Args:
            chars: Iterable of single-character strings, e.g. ``["_", "-"]``.
        """
        self._invalid_suffixes = "".join(chars)
        self.update()

    @property
    def has_affix_warning(self) -> bool:
        """True when the current text starts or ends with an invalid char."""
        text = self.text()
        if not text:
            return False
        if self._invalid_prefixes and text[0] in self._invalid_prefixes:
            return True
        if self._invalid_suffixes and text[-1] in self._invalid_suffixes:
            return True
        return False

    # -- Context menu -------------------------------------------------------

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Show a Fluent-styled context menu with standard edit actions."""
        menu = FluentContextMenu(dark_mode=self._dark_mode)
        has_sel = self.hasSelectedText()
        can_paste = bool(QApplication.clipboard().text())

        if not self.isReadOnly():
            menu.add_item(
                "Undo", shortcut="Ctrl+Z",
                callback=self.undo, enabled=self.isUndoAvailable(),
            )
            menu.add_item(
                "Redo", shortcut="Ctrl+Y",
                callback=self.redo, enabled=self.isRedoAvailable(),
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
            menu.add_item(
                "Delete",
                callback=self.del_, enabled=has_sel,
            )
        menu.add_separator()
        menu.add_item(
            "Select All", shortcut="Ctrl+A",
            callback=self.selectAll, enabled=bool(self.text()),
        )
        menu.show_at(event.globalPos())

    # -- Theme helpers ------------------------------------------------------

    def _apply_theme(self) -> None:
        """Push text / placeholder colours into the QPalette.

        Sets the Base role to fully transparent (alpha=0) so our custom
        paintEvent background shows through instead of the native fill.
        """
        t = self._theme_obj()
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, t.text)
        pal.setColor(QPalette.ColorRole.PlaceholderText, t.placeholder)
        self.setPalette(pal)

    # -- Qt events ----------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw the custom background and border, then delegate to QLineEdit.

        In display mode nothing is drawn here -- the transparent palette Base
        and read-only state produce a label-like appearance without any
        additional painting.
        """
        if not self._display_mode:
            t = self._theme_obj()
            focused = self.hasFocus()
            warning = self.has_affix_warning

            bg = t.bg_hover if self._hovered else t.bg

            if warning:
                border_color = t.warning
                border_width = 1.5
            elif focused:
                border_color = t.border_focus
                border_width = 1.5
            elif self._hovered:
                border_color = t.border_hover
                border_width = 1.0
            else:
                border_color = t.border
                border_width = 1.0

            # Inset by half pen width so stroke sits fully inside the rect.
            inset = border_width / 2
            rect = QRectF(
                inset,
                inset,
                self.width() - 2 * inset,
                self.height() - 2 * inset,
            )

            p = QPainter(self)
            if not p.isActive():
                # Paint engine not available (can happen transiently on
                # Windows when QStyleSheetStyle reconfigures the widget).
                super().paintEvent(event)
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Rounded background fill
            path = QPainterPath()
            path.addRoundedRect(rect, t.border_radius, t.border_radius)
            p.fillPath(path, bg)

            # Border stroke
            p.setPen(QPen(border_color, border_width))
            p.drawPath(path)

            # Win11-style bottom accent line when focused or warning
            if focused or warning:
                accent_h = 2.0
                accent_margin = t.border_radius + inset
                accent_color = t.warning if warning else t.border_focus
                p.fillRect(
                    QRectF(
                        accent_margin,
                        self.height() - accent_h,
                        self.width() - 2 * accent_margin,
                        accent_h,
                    ),
                    accent_color,
                )

            p.end()

        # Delegate to QLineEdit: draws text, cursor, selection, clear button.
        super().paintEvent(event)
