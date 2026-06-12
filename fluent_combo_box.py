"""Windows 11 Fluent Design ComboBox for PySide6.

A fully custom combobox that does **not** use `QComboBox`.  Instead, it
combines a custom ``QWidget`` button with a frameless popup dropdown
list (same technique as ``FluentContextMenu``), giving pixel-perfect
rounded corners, smooth hover highlights, and reliable styling in
small layouts.

Why not QComboBox?
------------------
``QComboBox``'s internal popup is a ``QFrame`` with its own window handle.
QSS ``border-radius`` bleeds at the corners, hover highlights are
unreliable, and the popup size / position are hard to control --
especially when the combobox is small or embedded in a tight layout.

Architecture
------------
-   **FluentComboBox** (``QWidget``) -- the visible button showing the
    current value and a chevron arrow.  Painted entirely with QPainter.
-   **_ComboPopup** (``QWidget``) -- frameless translucent dropdown.
    Same shadow, rounded-rect, and hover-pill rendering as
    ``_MenuPopup`` from the context menu.
-   **_ComboItemWidget** -- one selectable row with optional icon, hover
    pill, and selected-indicator.
-   **_ComboSearchField** -- optional search / filter field at the top
    of the popup.

Features
--------
-   Pixel-perfect rounded corners (pure QPainter).
-   Soft drop shadow.
-   Smooth hover highlight per item.
-   Optional search / filter for long lists.
-   Icons per item.
-   Separators.
-   Placeholder text.
-   Light / dark theme via a single ``dark_mode`` bool.
-   ``current_index`` / ``current_text`` / ``current_data`` properties.
-   ``currentIndexChanged`` and ``currentTextChanged`` signals.
-   Drop-in replacement API similar to ``QComboBox``.
"""

import time
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fluent_context_menu import FluentContextMenu


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Theme:
    """Immutable colour / metric bundle for all combo box sub-widgets."""

    # -- Button (the combobox itself) --
    button_bg: QColor
    button_bg_hover: QColor
    button_bg_pressed: QColor
    button_border: QColor
    button_border_focus: QColor
    button_text: QColor
    button_placeholder: QColor
    button_arrow: QColor

    # -- Popup --
    popup_bg: QColor
    popup_border: QColor
    shadow_color: QColor

    # -- Items --
    item_text: QColor
    item_text_disabled: QColor
    item_hover_bg: QColor
    item_pressed_bg: QColor
    item_selected_indicator: QColor

    # -- Separator --
    separator_color: QColor

    # -- Search field --
    search_bg: QColor
    search_text: QColor
    search_placeholder: QColor
    search_border: QColor

    # -- Icon --
    icon_color: QColor

    # -- Checkbox --
    checkbox_bg: QColor
    checkbox_bg_checked: QColor
    checkbox_border: QColor
    checkbox_check_mark: QColor
    checkbox_text: QColor
    checkbox_hover_bg: QColor

    # -- Warning (invalid prefix/suffix) --
    warning: QColor

    # -- Metrics --
    border_radius: int = 6
    popup_border_radius: int = 8
    shadow_radius: int = 12
    item_height: int = 32
    item_radius: int = 4
    item_h_pad: int = 12
    icon_size: int = 16
    font_size: int = 13
    button_height: int = 32


DARK = _Theme(
    button_bg=QColor(38, 40, 44),
    button_bg_hover=QColor(51, 53, 59),
    button_bg_pressed=QColor(33, 35, 38),
    button_border=QColor(64, 67, 74),
    button_border_focus=QColor(56, 113, 225),
    button_text=QColor(209, 211, 217),
    button_placeholder=QColor(95, 98, 105),
    button_arrow=QColor(159, 162, 168),
    popup_bg=QColor(38, 40, 44),
    popup_border=QColor(64, 67, 74),
    shadow_color=QColor(0, 0, 0, 100),
    item_text=QColor(209, 211, 217),
    item_text_disabled=QColor(76, 79, 86),
    item_hover_bg=QColor(51, 53, 59),
    item_pressed_bg=QColor(38, 40, 44),
    item_selected_indicator=QColor(56, 113, 225),
    separator_color=QColor(64, 67, 74),
    search_bg=QColor(25, 26, 28),
    search_text=QColor(209, 211, 217),
    search_placeholder=QColor(95, 98, 105),
    search_border=QColor(64, 67, 74),
    icon_color=QColor(209, 211, 217),
    checkbox_bg=QColor(25, 26, 28),
    checkbox_bg_checked=QColor(56, 113, 225),
    checkbox_border=QColor(95, 98, 105),
    checkbox_check_mark=QColor(255, 255, 255),
    checkbox_text=QColor(159, 162, 168),
    checkbox_hover_bg=QColor(51, 53, 59),
    warning=QColor(194, 128, 19),
)

LIGHT = _Theme(
    button_bg=QColor(255, 255, 255),
    button_bg_hover=QColor(237, 239, 242),
    button_bg_pressed=QColor(233, 234, 238),
    button_border=QColor(209, 211, 217),
    button_border_focus=QColor(56, 113, 225),
    button_text=QColor(0, 0, 0),
    button_placeholder=QColor(159, 162, 168),
    button_arrow=QColor(115, 118, 124),
    popup_bg=QColor(255, 255, 255),
    popup_border=QColor(233, 234, 238),
    shadow_color=QColor(0, 0, 0, 50),
    item_text=QColor(0, 0, 0),
    item_text_disabled=QColor(159, 162, 168),
    item_hover_bg=QColor(233, 234, 238),
    item_pressed_bg=QColor(221, 223, 228),
    item_selected_indicator=QColor(56, 113, 225),
    separator_color=QColor(233, 234, 238),
    search_bg=QColor(255, 255, 255),
    search_text=QColor(0, 0, 0),
    search_placeholder=QColor(159, 162, 168),
    search_border=QColor(209, 211, 217),
    icon_color=QColor(0, 0, 0),
    checkbox_bg=QColor(255, 255, 255),
    checkbox_bg_checked=QColor(56, 113, 225),
    checkbox_border=QColor(195, 197, 203),
    checkbox_check_mark=QColor(255, 255, 255),
    checkbox_text=QColor(95, 98, 105),
    checkbox_hover_bg=QColor(237, 239, 242),
    warning=QColor(165, 105, 6),
)


# ---------------------------------------------------------------------------
# Item data model
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ComboItemDef:
    """Data object for one combobox entry."""

    text: str = ""
    icon: Optional[QIcon] = None
    data: Any = None
    enabled: bool = True
    is_separator: bool = False


# ---------------------------------------------------------------------------
# _ComboSeparatorWidget
# ---------------------------------------------------------------------------

class _ComboSeparatorWidget(QWidget):
    """Thin horizontal separator inside the dropdown."""

    def __init__(self, theme: _Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxSeparator")
        self._theme = theme
        self.setFixedHeight(9)

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self._theme.separator_color, 1.0))
        y = self.height() / 2.0
        pad = self._theme.item_h_pad
        p.drawLine(int(pad), int(y), int(self.width() - pad), int(y))
        p.end()


# ---------------------------------------------------------------------------
# _ComboItemWidget -- one selectable row
# ---------------------------------------------------------------------------

class _ComboItemWidget(QWidget):
    """Dropdown item with hover pill, selected indicator, and optional icon."""

    clicked = Signal(int)  # emits the item index

    _ICON_COLUMN_WIDTH = 28
    _SELECTED_BAR_WIDTH = 3
    _SELECTED_BAR_HEIGHT = 16

    def __init__(
        self,
        index: int,
        item_def: ComboItemDef,
        theme: _Theme,
        is_selected: bool = False,
        has_any_icons: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxItem")
        self._index = index
        self._def = item_def
        self._theme = theme
        self._is_selected = is_selected
        self._has_any_icons = has_any_icons
        self._hovered = False
        self._pressed = False

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(theme.item_height)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if item_def.enabled
            else Qt.CursorShape.ArrowCursor
        )
        self.setEnabled(item_def.enabled)

    @property
    def index(self) -> int:
        """The item index this widget represents."""
        return self._index

    @property
    def is_hovered(self) -> bool:
        return self._hovered

    @is_hovered.setter
    def is_hovered(self, value: bool) -> None:
        self._hovered = value

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.setFixedHeight(theme.item_height)
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        t = self._theme
        f = QFont(self.font())
        f.setPixelSize(t.font_size)
        fm = QFontMetrics(f)

        width = t.item_h_pad + self._SELECTED_BAR_WIDTH + 8
        if self._has_any_icons:
            width += self._ICON_COLUMN_WIDTH
        width += fm.horizontalAdvance(self._def.text)
        width += t.item_h_pad

        return QSize(max(width, 120), t.item_height)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Hover / pressed pill background
        if self.isEnabled() and (self._hovered or self._pressed):
            bg = t.item_pressed_bg if self._pressed else t.item_hover_bg
            p.setBrush(bg)
            p.setPen(Qt.PenStyle.NoPen)
            pill = QRectF(4, 0, self.width() - 8, self.height())
            p.drawRoundedRect(pill, t.item_radius, t.item_radius)

        text_col = t.item_text if self.isEnabled() else t.item_text_disabled
        x = t.item_h_pad

        # Selected indicator (vertical bar on the left)
        if self._is_selected:
            bar_x = 6
            bar_y = (self.height() - self._SELECTED_BAR_HEIGHT) / 2.0
            p.setBrush(t.item_selected_indicator)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(
                QRectF(bar_x, bar_y, self._SELECTED_BAR_WIDTH, self._SELECTED_BAR_HEIGHT),
                1.5, 1.5,
            )

        x += self._SELECTED_BAR_WIDTH + 8

        # Icon column (reserved even when this item has no icon, for alignment)
        if self._has_any_icons:
            if self._def.icon is not None and not self._def.icon.isNull():
                pm = self._def.icon.pixmap(QSize(t.icon_size, t.icon_size))
                icon_x = x + (self._ICON_COLUMN_WIDTH - t.icon_size) // 2
                icon_y = (self.height() - t.icon_size) // 2
                p.drawPixmap(icon_x, icon_y, pm)
            x += self._ICON_COLUMN_WIDTH

        # Text label
        font = QFont(p.font())
        font.setPixelSize(t.font_size)
        if self._is_selected:
            font.setBold(True)
        p.setFont(font)
        p.setPen(text_col)
        label_rect = QRectF(x, 0, self.width() - x - t.item_h_pad, self.height())
        p.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, self._def.text)

        p.end()

    def enterEvent(self, _event) -> None:  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self.isEnabled() and self.rect().contains(event.position().toPoint()):
                self.clicked.emit(self._index)


# ---------------------------------------------------------------------------
# Shared Fluent context menu for QLineEdit subclasses
# ---------------------------------------------------------------------------

def _show_lineedit_fluent_menu(edit: QLineEdit, global_pos, theme: "_Theme") -> None:
    """Build and show a Fluent context menu with standard QLineEdit actions."""
    dark = theme.popup_bg.lightness() < 128
    menu = FluentContextMenu(dark_mode=dark)
    has_sel = edit.hasSelectedText()
    can_paste = bool(QApplication.clipboard().text())

    if not edit.isReadOnly():
        menu.add_item(
            "Undo", shortcut="Ctrl+Z",
            callback=edit.undo, enabled=edit.isUndoAvailable(),
        )
        menu.add_item(
            "Redo", shortcut="Ctrl+Y",
            callback=edit.redo, enabled=edit.isRedoAvailable(),
        )
        menu.add_separator()
        menu.add_item(
            "Cut", shortcut="Ctrl+X",
            callback=edit.cut, enabled=has_sel,
        )
    menu.add_item(
        "Copy", shortcut="Ctrl+C",
        callback=edit.copy, enabled=has_sel,
    )
    if not edit.isReadOnly():
        menu.add_item(
            "Paste", shortcut="Ctrl+V",
            callback=edit.paste, enabled=can_paste,
        )
        menu.add_item(
            "Delete",
            callback=edit.del_, enabled=has_sel,
        )
    menu.add_separator()
    menu.add_item(
        "Select All", shortcut="Ctrl+A",
        callback=edit.selectAll, enabled=bool(edit.text()),
    )
    menu.show_at(global_pos)


# ---------------------------------------------------------------------------
# _ComboSearchField
# ---------------------------------------------------------------------------

class _ComboSearchField(QLineEdit):
    """Styled search field for the dropdown popup.

    Uses QPalette for text colours and a custom paintEvent for the
    rounded border, avoiding hardcoded QSS.
    """

    def __init__(self, theme: _Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxSearch")
        self._theme = theme
        self.setPlaceholderText("Suchen...")
        self.setClearButtonEnabled(True)
        self.setFrame(False)
        self.setTextMargins(8, 4, 8, 4)
        self._apply_theme()

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self._apply_theme()
        self.update()

    def _apply_theme(self) -> None:
        """Apply theme colours via QPalette and font size via QFont."""
        t = self._theme
        pal = self.palette()
        # Transparent base so our custom paintEvent background shows through
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, t.search_text)
        pal.setColor(QPalette.ColorRole.PlaceholderText, t.search_placeholder)
        self.setPalette(pal)
        font = self.font()
        font.setPixelSize(t.font_size)
        self.setFont(font)

    def paintEvent(self, event) -> None:  # noqa: N802
        # Draw rounded background + border before QLineEdit paints text
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(t.search_bg)
        p.setPen(QPen(t.search_border, 1.0))
        p.drawRoundedRect(rect, 4, 4)
        p.end()
        # Let QLineEdit paint text, cursor, clear button on top
        super().paintEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        _show_lineedit_fluent_menu(self, event.globalPos(), self._theme)


# ---------------------------------------------------------------------------
# _PopupEditField -- edit line inside the popup (editable mode)
# ---------------------------------------------------------------------------

class _PopupEditField(QLineEdit):
    """Edit field shown inside the popup dropdown for editable combos.

    Combines the rounded border painting of _ComboSearchField with the
    ghost suffix autocomplete painting of the old _GhostLineEdit.

    Overrides event() to intercept Tab before Qt's focus system
    consumes it, forwarding it to the parent popup.
    """

    tab_pressed = Signal()

    def __init__(self, theme: _Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxPopupEdit")
        self._theme = theme
        self._ghost_suffix: str = ""
        self.setFrame(False)
        self.setClearButtonEnabled(True)
        self.setTextMargins(8, 4, 8, 4)
        self._apply_theme()

    @property
    def ghost_suffix(self) -> str:
        return self._ghost_suffix

    @ghost_suffix.setter
    def ghost_suffix(self, value: str) -> None:
        if self._ghost_suffix != value:
            self._ghost_suffix = value
            self.update()

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self._apply_theme()
        self.update()

    def _apply_theme(self) -> None:
        t = self._theme
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, t.search_text)
        pal.setColor(QPalette.ColorRole.PlaceholderText, t.search_placeholder)
        self.setPalette(pal)
        font = self.font()
        font.setPixelSize(t.font_size)
        self.setFont(font)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        _show_lineedit_fluent_menu(self, event.globalPos(), self._theme)

    def event(self, ev: QEvent) -> bool:  # noqa: N802
        # Intercept Tab before Qt's focus system consumes it
        if ev.type() == QEvent.Type.KeyPress:
            key_ev: QKeyEvent = ev  # type: ignore[assignment]
            if key_ev.key() == Qt.Key.Key_Tab:
                self.tab_pressed.emit()
                return True
        return super().event(ev)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        # Forward navigation keys to the parent popup so it can handle
        # hover movement (Up/Down) and item selection / freetext confirm (Enter)
        if key in (
            Qt.Key.Key_Up, Qt.Key.Key_Down,
            Qt.Key.Key_Return, Qt.Key.Key_Enter,
        ):
            popup = self.parent()
            if popup is not None:
                popup.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Rounded border background
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(t.search_bg)
        p.setPen(QPen(t.search_border, 1.0))
        p.drawRoundedRect(rect, 4, 4)
        p.end()

        # Let QLineEdit paint text, cursor, clear button
        super().paintEvent(event)

        # Draw ghost suffix after the typed text
        if not self._ghost_suffix or self.hasSelectedText():
            return

        # Use cursorRect to find where the cursor sits -- this accounts
        # for text margins, scroll offset, and clear-button space.
        cursor_r = self.cursorRect()
        ghost_x = cursor_r.right() + 1

        avail_w = self.contentsRect().right() - ghost_x
        if avail_w <= 0:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont(self.font())
        font.setPixelSize(t.font_size)
        p.setFont(font)
        fm = QFontMetrics(font)

        elided = fm.elidedText(
            self._ghost_suffix, Qt.TextElideMode.ElideRight, int(avail_w),
        )
        ghost_rect = QRectF(ghost_x, 0, avail_w, self.height())
        p.setPen(t.search_placeholder)
        p.drawText(ghost_rect, Qt.AlignmentFlag.AlignVCenter, elided)
        p.end()


# ---------------------------------------------------------------------------
# _ComboCheckBox -- custom-painted checkbox
# ---------------------------------------------------------------------------

class _ComboCheckBox(QWidget):
    """Custom QPainter-painted checkbox widget (no QCheckBox, no QSS)."""

    toggled = Signal(bool)

    _BOX_SIZE = 16
    _BOX_RADIUS = 3

    def __init__(
        self,
        label: str,
        theme: _Theme,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxCheckBox")
        self._label = label
        self._theme = theme
        self._checked = False
        self._hovered = False

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)

    @property
    def checked(self) -> bool:
        return self._checked

    @checked.setter
    def checked(self, value: bool) -> None:
        if self._checked != value:
            self._checked = value
            self.update()

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        box_x = 8
        box_y = (self.height() - self._BOX_SIZE) / 2.0
        box_rect = QRectF(box_x, box_y, self._BOX_SIZE, self._BOX_SIZE)

        if self._checked:
            # Filled box
            p.setBrush(t.checkbox_bg_checked)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(box_rect, self._BOX_RADIUS, self._BOX_RADIUS)

            # Check mark (two lines forming a checkmark)
            p.setPen(QPen(t.checkbox_check_mark, 1.8))
            cx = box_x + self._BOX_SIZE / 2.0
            cy = box_y + self._BOX_SIZE / 2.0
            p.drawLine(
                int(cx - 4), int(cy),
                int(cx - 1), int(cy + 3),
            )
            p.drawLine(
                int(cx - 1), int(cy + 3),
                int(cx + 4), int(cy - 3),
            )
        else:
            # Empty box with border
            bg = t.checkbox_hover_bg if self._hovered else t.checkbox_bg
            p.setBrush(bg)
            p.setPen(QPen(t.checkbox_border, 1.0))
            p.drawRoundedRect(box_rect, self._BOX_RADIUS, self._BOX_RADIUS)

        # Label text
        font = QFont(p.font())
        font.setPixelSize(t.font_size - 1)
        p.setFont(font)
        p.setPen(t.checkbox_text)
        text_x = box_x + self._BOX_SIZE + 8
        text_rect = QRectF(text_x, 0, self.width() - text_x - 8, self.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, self._label)
        p.end()

    def enterEvent(self, _event) -> None:  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hovered = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self.rect().contains(event.position().toPoint()):
                self._checked = not self._checked
                self.update()
                self.toggled.emit(self._checked)


# ---------------------------------------------------------------------------
# _FlipButtonWidget -- small button to flip popup above/below
# ---------------------------------------------------------------------------

class _FlipButtonWidget(QWidget):
    """Small clickable bar with a chevron to flip the popup direction."""

    clicked = Signal()

    def __init__(
        self,
        theme: _Theme,
        points_up: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxFlip")
        self._theme = theme
        self._points_up = points_up
        self._hovered = False
        self.setFixedHeight(22)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        self.update()

    @property
    def points_up(self) -> bool:
        return self._points_up

    @points_up.setter
    def points_up(self, value: bool) -> None:
        self._points_up = value
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Hover background pill
        if self._hovered:
            p.setBrush(t.item_hover_bg)
            p.setPen(Qt.PenStyle.NoPen)
            pill = QRectF(4, 0, self.width() - 8, self.height())
            p.drawRoundedRect(pill, t.item_radius, t.item_radius)

        # Chevron arrow
        cx = self.width() / 2
        cy = self.height() / 2
        p.setPen(QPen(t.item_text, 1.4))
        if self._points_up:
            p.drawLine(int(cx - 5), int(cy + 2), int(cx), int(cy - 2))
            p.drawLine(int(cx), int(cy - 2), int(cx + 5), int(cy + 2))
        else:
            p.drawLine(int(cx - 5), int(cy - 2), int(cx), int(cy + 2))
            p.drawLine(int(cx), int(cy + 2), int(cx + 5), int(cy - 2))

        p.end()

    def enterEvent(self, _event) -> None:  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hovered = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()


# ---------------------------------------------------------------------------
# _ComboPopup -- the dropdown container
# ---------------------------------------------------------------------------

class _ComboPopup(QWidget):
    """Frameless translucent dropdown popup."""

    SHADOW_MARGIN = 12
    MAX_VISIBLE_ITEMS = 10  # Max items shown before scrolling kicks in

    item_selected = Signal(int)
    closed = Signal()
    flip_requested = Signal()  # Emitted when user clicks the flip button
    edit_confirmed = Signal(str)  # Emitted when user confirms text in edit field
    edit_text_changed = Signal(str)  # Emitted when edit field text changes
    ghost_accept_requested = Signal()  # Emitted when user presses Tab on edit field

    def __init__(
        self,
        theme: _Theme,
        searchable: bool = False,
        editable: bool = False,
        show_flip_buttons: bool = False,
        no_focus_steal: bool = False,
        invalid_prefixes: str = "",
        invalid_suffixes: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBoxPopup")
        self._theme = theme
        self._searchable = searchable
        self._editable = editable
        self._show_flip_buttons = show_flip_buttons
        self._invalid_prefixes = invalid_prefixes
        self._invalid_suffixes = invalid_suffixes
        self._item_widgets: List[Union[_ComboItemWidget, _ComboSeparatorWidget]] = []
        self._search_field: Optional[_ComboSearchField] = None
        self._edit_field: Optional[_PopupEditField] = None
        self._warning_label: Optional[QLabel] = None
        self._checkbox: Optional[_ComboCheckBox] = None
        self._search_as_edit: bool = False  # Whether checkbox is checked
        self._all_item_rows: List[
            Tuple[Union[_ComboItemWidget, _ComboSeparatorWidget], ComboItemDef]
        ] = []
        self._keyword_filter: bool = False
        self._is_above: bool = False  # Whether popup is currently above button
        self._button_ref: Optional[QWidget] = None  # For dynamic re-layout
        self._flip_top: Optional[_FlipButtonWidget] = None
        self._flip_bottom: Optional[_FlipButtonWidget] = None

        # Tracks whether the current hover was set by keyboard (Up/Down).
        # Reset to False on mouse enter so passive mouse hover does not
        # steal Enter from the edit field in editable mode.
        self._kb_navigated: bool = False

        if no_focus_steal:
            # Tool window stays open without stealing focus from the
            # inline search field.  Click-outside-to-close is handled
            # by the owning FluentComboBox via an app event filter.
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.NoDropShadowWindowHint
            )
            self.setAttribute(
                Qt.WidgetAttribute.WA_ShowWithoutActivating, True,
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.Popup
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.NoDropShadowWindowHint
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        m = self.SHADOW_MARGIN
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(m, m + 4, m, m + 4)
        self._layout.setSpacing(0)

        # Top flip button (shown when popup is below the combobox)
        if show_flip_buttons:
            self._flip_top = _FlipButtonWidget(theme, points_up=False, parent=self)
            # noinspection PyUnresolvedReferences
            self._flip_top.clicked.connect(self._on_flip)
            self._layout.addWidget(self._flip_top)
            self._flip_top.setVisible(False)

        # Editable mode: edit field + warning label + checkbox above search field
        if editable:
            self._edit_field = _PopupEditField(theme, self)
            self._edit_field.setFixedHeight(32)
            self._layout.addWidget(self._edit_field)
            self._layout.addSpacing(2)
            # noinspection PyUnresolvedReferences
            self._edit_field.textEdited.connect(self._on_edit_text_changed_internal)
            # noinspection PyUnresolvedReferences
            self._edit_field.tab_pressed.connect(self.ghost_accept_requested.emit)

            # Warning label for invalid prefix / suffix (hidden by default)
            if invalid_prefixes or invalid_suffixes:
                self._warning_label = QLabel(self)
                self._warning_label.setObjectName("fluentComboBoxAffixWarning")
                self._warning_label.setFixedHeight(18)
                self._warning_label.setContentsMargins(
                    _ComboPopup.SHADOW_MARGIN + 8, 0, 0, 0,
                )
                warn_font = QFont(self._warning_label.font())
                warn_font.setPixelSize(max(theme.font_size - 1, 10))
                self._warning_label.setFont(warn_font)
                pal = self._warning_label.palette()
                pal.setColor(QPalette.ColorRole.WindowText, theme.warning)
                self._warning_label.setPalette(pal)
                self._warning_label.setVisible(False)
                self._layout.addWidget(self._warning_label)

            self._checkbox = _ComboCheckBox(
                "Auch als Suche verwenden", theme, self,
            )
            self._checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._layout.addWidget(self._checkbox)
            self._layout.addSpacing(2)
            # noinspection PyUnresolvedReferences
            self._checkbox.toggled.connect(self._on_search_checkbox_toggled)

        if searchable:
            self._search_field = _ComboSearchField(theme, self)
            self._search_field.setFixedHeight(28)
            # In editable mode, Tab must stay on the edit field for ghost accept
            if editable:
                self._search_field.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            self._layout.addWidget(self._search_field)
            self._layout.addSpacing(4)
            # noinspection PyUnresolvedReferences
            self._search_field.textChanged.connect(self._on_filter)

        # Items container inside a scroll area
        self._items_container = QWidget(self)
        self._items_container.setObjectName("fluentComboBoxItemsContainer")
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("fluentComboBoxScroll")
        self._scroll.setWidget(self._items_container)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Transparent background -- the popup paints its own background
        self._scroll.viewport().setAutoFillBackground(False)
        self._items_container.setAutoFillBackground(False)
        self._layout.addWidget(self._scroll)

        # Bottom flip button (shown when popup is above the combobox)
        if show_flip_buttons:
            self._flip_bottom = _FlipButtonWidget(theme, points_up=True, parent=self)
            # noinspection PyUnresolvedReferences
            self._flip_bottom.clicked.connect(self._on_flip)
            self._layout.addWidget(self._flip_bottom)
            self._flip_bottom.setVisible(False)

    # -- Public accessors for FluentComboBox -----------------------------------

    @property
    def is_above(self) -> bool:
        """Whether the popup is currently displayed above the button."""
        return self._is_above

    @property
    def item_widgets(
        self,
    ) -> List[Union["_ComboItemWidget", "_ComboSeparatorWidget"]]:
        """All item/separator widgets in the popup."""
        return self._item_widgets

    def hide_search_field(self) -> None:
        """Hide the search field (used when editable mode provides its own)."""
        if self._search_field is not None:
            self._search_field.setVisible(False)

    def apply_filter(self, text: str) -> None:
        """Filter visible items by text (public entry point)."""
        self._on_filter(text)

    def update_scroll_height(self, filtering: bool = False) -> None:
        """Recalculate scroll area height to fit visible items."""
        self._update_scroll_height(filtering)

    @property
    def edit_field(self) -> Optional[_PopupEditField]:
        """Read-only access to the popup edit field (editable mode only)."""
        return self._edit_field

    def set_edit_text(self, text: str) -> None:
        """Pre-fill the edit field and select all text."""
        if self._edit_field is not None:
            self._edit_field.setText(text)
            self._edit_field.setCursorPosition(len(text))
            self._update_affix_warning(text)

    def focus_edit(self) -> None:
        """Focus the edit field (editable mode)."""
        if self._edit_field is not None:
            self._edit_field.setFocus()

    def restore_checkbox_state(self, checked: bool) -> None:
        """Restore persisted checkbox state on popup rebuild."""
        if self._checkbox is not None:
            self._checkbox.checked = checked
            self._search_as_edit = checked
            # Apply the visibility state
            if self._search_field is not None:
                self._search_field.setVisible(not checked)

    # -- Widget management ---------------------------------------------------

    def add_widget(
        self,
        w: Union["_ComboItemWidget", "_ComboSeparatorWidget"],
        item_def: Optional[ComboItemDef] = None,
    ) -> None:
        self._items_layout.addWidget(w)
        self._item_widgets.append(w)
        if item_def is not None:
            self._all_item_rows.append((w, item_def))
        # Track mouse hover on items to reset keyboard navigation flag
        if isinstance(w, _ComboItemWidget):
            w.installEventFilter(self)

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:  # noqa: N802
        """Reset keyboard navigation flag when mouse enters an item."""
        if event.type() == QEvent.Type.Enter and isinstance(obj, _ComboItemWidget):
            self._kb_navigated = False
        return super().eventFilter(obj, event)

    def set_theme(self, theme: _Theme) -> None:
        self._theme = theme
        if self._edit_field is not None:
            self._edit_field.set_theme(theme)
        if self._checkbox is not None:
            self._checkbox.set_theme(theme)
        if self._search_field is not None:
            self._search_field.set_theme(theme)
        if self._flip_top is not None:
            self._flip_top.set_theme(theme)
        if self._flip_bottom is not None:
            self._flip_bottom.set_theme(theme)
        for w in self._item_widgets:
            if isinstance(w, (_ComboItemWidget, _ComboSeparatorWidget)):
                w.set_theme(theme)
        self.update()

    def reposition(self, button: QWidget, force_above: Optional[bool] = None) -> None:
        """Position the popup relative to the button widget.

        Args:
            button:      The FluentComboBox widget.
            force_above: If None (default), auto-detect based on
                         available screen space.  If True, force above;
                         if False, force below.
        """
        self._button_ref = button  # Keep reference for dynamic re-layout
        self.adjustSize()

        global_below = button.mapToGlobal(QPoint(0, button.height()))
        global_above_top = button.mapToGlobal(QPoint(0, 0))

        screen = QApplication.screenAt(global_below)
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()

        x = global_below.x() - self.SHADOW_MARGIN

        # Decide direction
        if force_above is not None:
            go_above = force_above
        else:
            # Auto: prefer below, go above if not enough space
            y_below = global_below.y() + 2
            go_above = (y_below + self.height() > avail.bottom())

        if go_above:
            y = global_above_top.y() - self.height() + self.SHADOW_MARGIN - 2
            self._is_above = True
        else:
            y = global_below.y() + 2
            self._is_above = False

        # Horizontal clamping
        if x + self.width() > avail.right():
            x = avail.right() - self.width()
        x = max(x, avail.left())

        self.move(x, y)
        self._update_flip_buttons()

    def focus_search(self) -> None:
        """Focus the search field if present."""
        if self._search_field is not None:
            self._search_field.setFocus()
            self._search_field.clear()

    def _update_flip_buttons(self) -> None:
        """Show the flip button at the connecting edge (closest to combobox).

        - Popup below combobox: flip button at top (arrow up = flip above).
        - Popup above combobox: flip button at bottom (arrow down = flip below).
        """
        if not self._show_flip_buttons:
            return
        if self._flip_top is not None:
            # Top button visible when popup is BELOW (connecting edge = top)
            self._flip_top.setVisible(not self._is_above)
            self._flip_top.points_up = True  # Arrow up = "move me above"
        if self._flip_bottom is not None:
            # Bottom button visible when popup is ABOVE (connecting edge = bottom)
            self._flip_bottom.setVisible(self._is_above)
            self._flip_bottom.points_up = False  # Arrow down = "move me below"

    def _on_flip(self) -> None:
        """Handle flip button click."""
        self.flip_requested.emit()

    def _relayout(self) -> None:
        """Resize the popup to fit visible content and reposition."""
        self._update_scroll_height(filtering=True)
        self.adjustSize()

        # Reposition if we have a button reference
        if self._button_ref is not None:
            force = True if self._is_above else False
            self.reposition(self._button_ref, force_above=force)

    def _update_scroll_height(self, filtering: bool = False) -> None:
        """Set the scroll area height to fit visible items, capped at MAX.

        Args:
            filtering: If True, use actual widget visibility (some items
                       may be hidden by the search filter).  If False
                       (default / initial build), count all items because
                       the popup hasn't been shown yet and isVisible()
                       would return False for every widget.
        """
        t = self._theme
        item_count = 0
        sep_count = 0

        if filtering:
            # During active filtering, check real visibility
            for w in self._item_widgets:
                if not w.isVisible():
                    continue
                if isinstance(w, _ComboSeparatorWidget):
                    sep_count += 1
                else:
                    item_count += 1
        else:
            # Initial build or reposition: count everything that was added
            for w in self._item_widgets:
                if isinstance(w, _ComboSeparatorWidget):
                    sep_count += 1
                else:
                    item_count += 1

        if item_count == 0 and sep_count == 0:
            self._scroll.setFixedHeight(t.item_height)
            return

        total_h = item_count * t.item_height + sep_count * 9
        max_h = self.MAX_VISIBLE_ITEMS * t.item_height
        self._scroll.setFixedHeight(min(total_h, max_h))

    # -- Filter logic --------------------------------------------------------

    @staticmethod
    def _matches_tokens(tokens: List[str], item_text_lower: str) -> bool:
        """Check if all tokens appear in item text in order.

        Each token must be found after the previous one's match position,
        so "0 10 b" matches "0 bis 10 bar" and "0 ... 10 bar" but not
        "10 bar 0".
        """
        pos = 0
        for token in tokens:
            idx = item_text_lower.find(token, pos)
            if idx < 0:
                return False
            pos = idx + len(token)
        return True

    @staticmethod
    def _matches_keywords(tokens: List[str], item_text_lower: str) -> bool:
        """Unordered keyword matching with tolerance.

        Each token is checked independently as a substring (any order).
        For 3+ tokens, allows one token to not match so that a single
        typo does not hide an otherwise correct result.
        """
        hits = sum(1 for t in tokens if t in item_text_lower)
        if hits == len(tokens):
            return True
        if len(tokens) >= 3 and hits >= len(tokens) - 1:
            return True
        return False

    def _on_filter(self, text: str) -> None:
        text_lower = text.lower()
        tokens = text_lower.split()
        for w, item_def in self._all_item_rows:
            if item_def.is_separator:
                w.setVisible(not text_lower)
            elif self._keyword_filter and len(tokens) > 1:
                w.setVisible(
                    self._matches_keywords(tokens, item_def.text.lower()),
                )
            elif len(tokens) <= 1:
                # Single token or empty: simple substring match (fast path)
                w.setVisible(text_lower in item_def.text.lower())
            else:
                w.setVisible(self._matches_tokens(tokens, item_def.text.lower()))

        # Dynamically resize and reposition the popup so it shrinks/grows
        # to match the visible items instead of leaving a huge empty area
        self._relayout()

    # -- Editable mode internal handlers -------------------------------------

    def _on_search_checkbox_toggled(self, checked: bool) -> None:
        """Toggle between combined edit+filter and separate search bar."""
        self._search_as_edit = checked
        if self._search_field is not None:
            self._search_field.setVisible(not checked)
            if not checked:
                # Separate mode: clear search filter to show all items
                self._search_field.clear()
                self._on_filter("")
            else:
                # Combined mode: use edit field text as filter
                if self._edit_field is not None:
                    self._on_filter(self._edit_field.text())
        self._relayout()

    def _on_edit_text_changed_internal(self, text: str) -> None:
        """Handle text changes in the popup edit field."""
        self.edit_text_changed.emit(text)
        self._update_affix_warning(text)
        # If checkbox is checked, also filter items
        if self._search_as_edit:
            self._on_filter(text)

    def _update_affix_warning(self, text: str) -> None:
        """Show or hide the affix warning label based on current text."""
        if self._warning_label is None:
            return
        was_visible = self._warning_label.isVisible()
        if not text:
            self._warning_label.setVisible(False)
            if was_visible:
                self._relayout()
            return
        msg = ""
        if self._invalid_prefixes and text[0] in self._invalid_prefixes:
            msg = f"Ungültiges Präfix '{text[0]}'"
        elif self._invalid_suffixes and text[-1] in self._invalid_suffixes:
            msg = f"Ungültiges Suffix '{text[-1]}'"
        if msg:
            self._warning_label.setText(msg)
            self._warning_label.setVisible(True)
        else:
            self._warning_label.setVisible(False)
        if was_visible != self._warning_label.isVisible():
            self._relayout()

    # -- Painting (shadow + rounded rect) ------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._theme
        m = self.SHADOW_MARGIN
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft drop shadow (concentric rounded rects with fading alpha)
        base_a = t.shadow_color.alpha()
        for i in range(m):
            frac = (m - i) / m
            a = int(base_a * frac * frac)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(
                t.shadow_color.red(), t.shadow_color.green(),
                t.shadow_color.blue(), a,
            ))
            inset = m - i
            rect = QRectF(
                inset, inset + 2,
                self.width() - 2 * inset,
                self.height() - 2 * inset - 2,
            )
            p.drawRoundedRect(rect, t.popup_border_radius + i * 0.5,
                              t.popup_border_radius + i * 0.5)

        # Background panel
        bg = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        p.setBrush(t.popup_bg)
        p.setPen(QPen(t.popup_border, 1.0))
        p.drawRoundedRect(bg, t.popup_border_radius, t.popup_border_radius)
        p.end()

    # -- Keyboard navigation -------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return

        # Editable mode: intercept Tab and Enter
        if self._editable:
            if key == Qt.Key.Key_Tab:
                self.ghost_accept_requested.emit()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Block confirm when affix validation fails
                if (self._warning_label is not None
                        and self._warning_label.isVisible()):
                    return
                # Only select a hovered item if the user explicitly
                # navigated to it with Up/Down.  Passive mouse hover
                # must not steal Enter from the edit field.
                if self._kb_navigated:
                    items = [w for w in self._item_widgets
                             if isinstance(w, _ComboItemWidget) and w.isVisible()]
                    cur = next((i for i, w in enumerate(items) if w.is_hovered), -1)
                    if 0 <= cur < len(items) and items[cur].isEnabled():
                        # noinspection PyUnresolvedReferences
                        items[cur].clicked.emit(items[cur].index)
                        return
                if self._edit_field is not None:
                    self.edit_confirmed.emit(self._edit_field.text())
                return

        items = [w for w in self._item_widgets
                 if isinstance(w, _ComboItemWidget) and w.isVisible()]
        if not items:
            return

        cur = next((i for i, w in enumerate(items) if w.is_hovered), -1)

        if key == Qt.Key.Key_Down:
            new_idx = (cur + 1) % len(items)
            self._set_hover(items, new_idx)
            self._kb_navigated = True
        elif key == Qt.Key.Key_Up:
            new_idx = (cur - 1) % len(items)
            self._set_hover(items, new_idx)
            self._kb_navigated = True
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if 0 <= cur < len(items) and items[cur].isEnabled():
                # noinspection PyUnresolvedReferences
                items[cur].clicked.emit(items[cur].index)
        else:
            super().keyPressEvent(event)

    @staticmethod
    def _set_hover(items: List[_ComboItemWidget], idx: int) -> None:
        for i, w in enumerate(items):
            w.is_hovered = (i == idx)
            w.update()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# FluentComboBox -- public API
# ---------------------------------------------------------------------------

class FluentComboBox(QWidget):
    """Windows 11 Fluent-Design combobox -- no QComboBox, fully custom.

    Light / dark theme is selected via the ``dark_mode`` flag (constructor
    argument or property).  Setting it rebuilds the popup and repaints.

    Signals:
        currentIndexChanged(int): Emitted when the selected index changes.
        currentTextChanged(str):  Emitted when the selected text changes.
        editTextChanged(str):     Emitted when the user types in editable mode.

    Args:
        searchable:   If True, the dropdown includes a search field.
        editable:     If True, clicking the button opens a popup with
                      an edit field at the top.  The edit field supports
                      ghost autocomplete (Tab to accept) and optional
                      combined search (via checkbox).  The button itself
                      is display-only, showing the confirmed value.
                      When editable is True, searchable is implied.
        placeholder:  Placeholder text when no item is selected.
        display_mode: If True, the combobox shows the selected value
                      but disables the dropdown and all interaction.  The
                      visual style stays normal (not greyed out).
        parent:       Optional parent widget.

    Example::

        combo = FluentComboBox(editable=True)
        combo.add_item("Option A")
        combo.add_item("Option B", icon=my_icon)
        combo.add_item("Option C", data={"key": "val"})
        combo.currentIndexChanged.connect(on_changed)
    """

    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)
    editTextChanged = Signal(str)

    def __init__(
        self,
        searchable: bool = False,
        editable: bool = False,
        placeholder: str = "",
        display_mode: bool = False,
        search_mode: bool = False,
        item_factory=None,
        dark_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentComboBox")
        self._dark_mode = dark_mode
        self._editable = editable
        self._search_mode = search_mode
        # Editable implies searchable popup filtering
        self._searchable = searchable or editable
        self._placeholder = placeholder
        self._display_mode = display_mode
        self._items: List[ComboItemDef] = []
        self._current_index: int = -1
        self._popup: Optional[_ComboPopup] = None

        self._hovered = False
        self._pressed = False
        self._opened = False
        self._popup_close_time: float = 0.0  # Timestamp to suppress reopen

        # Prefix / suffix validation
        self._invalid_prefixes: str = ""
        self._invalid_suffixes: str = ""

        # Editable mode state (edit field lives inside the popup now)
        self._confirmed_text: str = ""  # Authoritative edit value
        self._search_as_edit: bool = False  # Persists checkbox state across popup rebuilds

        self.setMouseTracking(True)
        self._update_cursor()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # Optional factory for custom item widgets in the popup
        self._item_factory = item_factory

        # Search mode: embed a QLineEdit as the visible widget
        self._search_field: Optional[_ComboSearchField] = None
        self._search_emits_text_changed: bool = False
        if search_mode:
            self._search_field = _ComboSearchField(self._theme_obj(), self)
            self._search_field.setObjectName("fluentComboBoxInlineSearch")
            if placeholder:
                self._search_field.setPlaceholderText(placeholder)
            self.setFocusProxy(self._search_field)
            self._search_field.textEdited.connect(
                self._on_search_mode_text_edited,
            )
            self._search_field.returnPressed.connect(
                self._on_search_mode_return,
            )
            self._search_field.installEventFilter(self)

    # -- Theme ---------------------------------------------------------------

    @property
    def dark_mode(self) -> bool:
        """Current theme flag.  Setting it rebuilds the popup and repaints."""
        return self._dark_mode

    @dark_mode.setter
    def dark_mode(self, value: bool) -> None:
        if self._dark_mode == value:
            return
        self._dark_mode = value
        self._invalidate()
        if self._search_mode and self._search_field is not None:
            self._search_field.set_theme(self._theme_obj())
        self.update()

    def _theme_obj(self) -> _Theme:
        """Return the colour bundle matching the active theme."""
        return DARK if self._dark_mode else LIGHT

    # -- Properties ----------------------------------------------------------

    @property
    def display_mode(self) -> bool:
        """Read-only display mode.  Shows the selected value but no dropdown.

        The widget keeps its normal visual style (not greyed out like
        setEnabled(False)), but clicking does nothing and the cursor
        changes to a normal arrow.
        """
        return self._display_mode

    @display_mode.setter
    def display_mode(self, value: bool) -> None:
        if self._display_mode != value:
            self._display_mode = value
            self._update_cursor()
            if value and self._opened and self._popup is not None:
                self._popup.close()
            self.update()

    @property
    def editable(self) -> bool:
        """Whether the user can type into the combobox."""
        return self._editable

    @property
    def edit_text(self) -> str:
        """The current text in the edit field (editable mode only).

        In non-editable mode, returns current_text.
        """
        if self._editable:
            return self._confirmed_text
        return self.current_text

    @edit_text.setter
    def edit_text(self, value: str) -> None:
        if self._editable:
            self._confirmed_text = value
            self.update()
            # Sync popup edit field if open
            if self._popup is not None and self._opened:
                self._popup.set_edit_text(value)

    @property
    def placeholder(self) -> str:
        return self._placeholder

    @placeholder.setter
    def placeholder(self, value: str) -> None:
        self._placeholder = value
        self.update()

    # -- Prefix / suffix validation -------------------------------------------

    def set_invalid_prefixes(self, chars: Sequence[str]) -> None:
        """Set characters that are invalid as first character of the text.

        Args:
            chars: Iterable of single-character strings, e.g. ``["_", "-"]``.
        """
        self._invalid_prefixes = "".join(chars)
        self.update()

    def set_invalid_suffixes(self, chars: Sequence[str]) -> None:
        """Set characters that are invalid as last character of the text.

        Args:
            chars: Iterable of single-character strings, e.g. ``["_", "-"]``.
        """
        self._invalid_suffixes = "".join(chars)
        self.update()

    @property
    def has_affix_warning(self) -> bool:
        """True when the current text starts or ends with an invalid char."""
        text = self.edit_text if self._editable else self.current_text
        if not text:
            return False
        if self._invalid_prefixes and text[0] in self._invalid_prefixes:
            return True
        if self._invalid_suffixes and text[-1] in self._invalid_suffixes:
            return True
        return False

    @property
    def affix_warning_message(self) -> str:
        """Human-readable warning describing which affix rule is violated."""
        text = self.edit_text if self._editable else self.current_text
        if not text:
            return ""
        if self._invalid_prefixes and text[0] in self._invalid_prefixes:
            return f"Darf nicht mit '{text[0]}' beginnen"
        if self._invalid_suffixes and text[-1] in self._invalid_suffixes:
            return f"Darf nicht mit '{text[-1]}' enden"
        return ""

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        self.set_current_index(value)

    @property
    def current_text(self) -> str:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index].text
        return ""

    @property
    def current_data(self) -> Any:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index].data
        return None

    @property
    def current_icon(self) -> Optional[QIcon]:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index].icon
        return None

    @property
    def count(self) -> int:
        return len([i for i in self._items if not i.is_separator])

    @property
    def search_text(self) -> str:
        """Read the inline search field text (search_mode only)."""
        if self._search_field is not None:
            return self._search_field.text()
        return ""

    @search_text.setter
    def search_text(self, value: str) -> None:
        """Set the inline search field text (search_mode only)."""
        if self._search_field is not None:
            self._search_field.setText(value)

    def set_search_emits_text_changed(self, enabled: bool) -> None:
        """Enable emitting editTextChanged from search_mode typing.

        By default, search_mode typing only drives the popup filter.
        Enable this to also emit editTextChanged so external consumers
        can react to each keystroke (e.g. debounced server-side search).
        """
        self._search_emits_text_changed = enabled

    def show_search_popup(self) -> None:
        """Open the popup showing all current items without filtering.

        Use this after externally populating items (e.g. server-side
        search results) when _search_emits_text_changed is enabled.
        """
        if not self._items:
            return
        popup = self._ensure_popup()
        popup.apply_filter("")  # show all items unfiltered
        popup.reposition(self)
        if not self._opened:
            popup.show()
            self._opened = True
            self.update()
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)

    # -- Item management -----------------------------------------------------

    def add_item(
        self,
        text: str,
        *,
        icon: Optional[QIcon] = None,
        data: Any = None,
        enabled: bool = True,
    ) -> ComboItemDef:
        """Add an item. Returns the ComboItemDef for reference."""
        d = ComboItemDef(text=text, icon=icon, data=data, enabled=enabled)
        self._items.append(d)
        self._invalidate()
        # Auto-select first item if none selected
        if not self._search_mode and self._current_index == -1 and enabled:
            self._current_index = len(self._items) - 1
            self._sync_edit_to_selection()
            self.update()
        return d

    def add_items(self, texts: List[str]) -> None:
        """Add multiple text-only items."""
        for t in texts:
            self.add_item(t)

    def add_separator(self) -> None:
        """Add a visual separator."""
        self._items.append(ComboItemDef(is_separator=True))
        self._invalidate()

    def insert_item(self, index: int, text: str, **kwargs) -> ComboItemDef:
        """Insert an item at the given index."""
        d = ComboItemDef(text=text, **kwargs)
        self._items.insert(index, d)
        self._invalidate()
        if self._current_index >= index:
            self._current_index += 1
        if self._current_index == -1 and d.enabled:
            self._current_index = index
        self.update()
        return d

    def remove_item(self, index: int) -> None:
        """Remove item at index."""
        real_idx = self._real_index(index)
        if real_idx is None:
            return
        self._items.pop(real_idx)
        self._invalidate()
        if self._current_index == real_idx:
            self._current_index = -1
            self.update()
            self.currentIndexChanged.emit(-1)
            self.currentTextChanged.emit("")
        elif self._current_index > real_idx:
            self._current_index -= 1

    def clear(self) -> None:
        """Remove all items."""
        self._items.clear()
        self._current_index = -1
        self._confirmed_text = ""
        self._invalidate()
        self.update()
        self.currentIndexChanged.emit(-1)
        self.currentTextChanged.emit("")

    def load_items(self, items: List[ComboItemDef]) -> None:
        """Batch-load items, replacing any existing ones.

        More efficient than repeated add_item() calls since it only
        invalidates the popup once at the end.
        """
        self._items = list(items)
        self._current_index = -1
        self._invalidate()
        self.update()

    def item_text(self, index: int) -> str:
        """Get text of item at index."""
        real_idx = self._real_index(index)
        if real_idx is not None:
            return self._items[real_idx].text
        return ""

    def item_data(self, index: int) -> Any:
        """Get user data of item at index."""
        real_idx = self._real_index(index)
        if real_idx is not None:
            return self._items[real_idx].data
        return None

    def set_current_index(self, index: int) -> None:
        """Programmatically select an item by index."""
        if index == self._current_index:
            return
        if index < 0 or index >= len(self._items):
            self._current_index = -1
        else:
            self._current_index = index
        self._sync_edit_to_selection()
        self.update()
        self.currentIndexChanged.emit(self._current_index)
        self.currentTextChanged.emit(self.current_text)

    def set_current_text(self, text: str) -> None:
        """Select the first item matching text."""
        for i, d in enumerate(self._items):
            if d.text == text and not d.is_separator:
                self.set_current_index(i)
                return

    def find_text(self, text: str) -> int:
        """Return the index of the first item with text, or -1."""
        for i, d in enumerate(self._items):
            if d.text == text and not d.is_separator:
                return i
        return -1

    def find_data(self, data: Any) -> int:
        """Return the index of the first item with data, or -1."""
        for i, d in enumerate(self._items):
            if d.data == data and not d.is_separator:
                return i
        return -1

    # -- Size ----------------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802
        t = self._theme_obj()
        f = QFont(self.font())
        f.setPixelSize(t.font_size)
        fm = QFontMetrics(f)

        max_w = 0
        for d in self._items:
            if not d.is_separator:
                max_w = max(max_w, fm.horizontalAdvance(d.text))

        width = t.item_h_pad + max_w + 32 + t.item_h_pad  # 32 for arrow area
        has_icons = any(d.icon is not None for d in self._items if not d.is_separator)
        if has_icons:
            width += 28
        return QSize(max(width, 120), t.button_height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # Allow the widget to shrink below button_height in tight layouts.
        # sizeHint still returns the preferred button_height.
        return QSize(60, 20)

    # -- Painting (the button) -----------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._search_mode:
            return  # Inline QLineEdit paints itself
        t = self._theme_obj()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background -- display_mode ignores hover / pressed states
        if self._display_mode:
            bg = t.button_bg
        elif self._pressed:
            bg = t.button_bg_pressed
        elif self._hovered:
            bg = t.button_bg_hover
        else:
            bg = t.button_bg

        show_focus = not self._display_mode and (self._opened or self.hasFocus())
        warning = self.has_affix_warning

        if warning:
            border_col = t.warning
        elif show_focus:
            border_col = t.button_border_focus
        else:
            border_col = t.button_border

        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(bg)
        p.setPen(QPen(border_col, 1.5 if warning else 1.0))
        p.drawRoundedRect(rect, t.border_radius, t.border_radius)

        # Bottom accent line (Win11 style) when focused / opened / warning
        if show_focus or warning:
            accent_y = self.height() - 1.0
            accent_rect = QRectF(t.border_radius, accent_y - 2,
                                 self.width() - 2 * t.border_radius, 2)
            accent_color = t.warning if warning else t.button_border_focus
            p.setBrush(accent_color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(accent_rect, 1, 1)

        x = t.item_h_pad

        # Current icon
        current = self._current_item()
        if current is not None and current.icon is not None and not current.icon.isNull():
            pm = current.icon.pixmap(QSize(t.icon_size, t.icon_size))
            icon_y = (self.height() - t.icon_size) // 2
            p.drawPixmap(x, icon_y, pm)
            x += t.icon_size + 8

        # Text or placeholder
        # In display_mode there is no chevron, so use item_h_pad as right
        # margin (symmetric with the left side) to avoid covering the border.
        arrow_space = t.item_h_pad if self._display_mode else 28
        v_pad = 2  # vertical padding so text stays inside the rounded border
        font = QFont(p.font())
        font.setPixelSize(t.font_size)
        p.setFont(font)

        text_rect = QRectF(x, v_pad, self.width() - x - arrow_space,
                           self.height() - 2 * v_pad)

        if self._editable:
            # Editable mode: display confirmed text or placeholder
            if self._confirmed_text:
                p.setPen(t.button_text)
                fm = QFontMetrics(font)
                elided = fm.elidedText(self._confirmed_text,
                                       Qt.TextElideMode.ElideRight,
                                       int(text_rect.width()))
                p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, elided)
            else:
                p.setPen(t.button_placeholder)
                p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter,
                           self._placeholder)
        elif current is not None:
            p.setPen(t.button_text)
            fm = QFontMetrics(font)
            elided = fm.elidedText(current.text, Qt.TextElideMode.ElideRight,
                                   int(text_rect.width()))
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, elided)
        else:
            p.setPen(t.button_placeholder)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter,
                       self._placeholder)

        # Chevron arrow (hidden in display_mode)
        if not self._display_mode:
            arrow_x = self.width() - 18
            arrow_y = self.height() / 2
            p.setPen(QPen(t.button_arrow, 1.5))
            if self._opened:
                # Up chevron
                p.drawLine(int(arrow_x - 4), int(arrow_y + 2),
                           int(arrow_x), int(arrow_y - 2))
                p.drawLine(int(arrow_x), int(arrow_y - 2),
                           int(arrow_x + 4), int(arrow_y + 2))
            else:
                # Down chevron
                p.drawLine(int(arrow_x - 4), int(arrow_y - 2),
                           int(arrow_x), int(arrow_y + 2))
                p.drawLine(int(arrow_x), int(arrow_y + 2),
                           int(arrow_x + 4), int(arrow_y - 2))

        p.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._search_mode and self._search_field is not None:
            self._search_field.setGeometry(0, 0, self.width(), self.height())

    # -- Mouse interaction ---------------------------------------------------

    def enterEvent(self, _event) -> None:  # noqa: N802
        if not self._display_mode:
            self._hovered = True
            self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._search_mode or self._display_mode:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._search_mode or self._display_mode:
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self._toggle_popup()
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._search_mode or self._display_mode:
            return
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle_popup()
        elif not self._editable and key == Qt.Key.Key_Down:
            self._move_selection(1)
        elif not self._editable and key == Qt.Key.Key_Up:
            self._move_selection(-1)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Scroll through items with mouse wheel.

        Disabled in editable and search modes (scrolling through items
        while typing is unexpected).
        """
        if self._search_mode or self._display_mode or self._editable:
            return
        delta = event.angleDelta().y()
        if delta > 0:
            self._move_selection(-1)
        elif delta < 0:
            self._move_selection(1)

    # -- Popup management ----------------------------------------------------

    def _toggle_popup(self) -> None:
        if self._display_mode:
            return
        if self._opened and self._popup is not None:
            self._popup.close()
            self.clearFocus()
            return

        # Qt's Popup flag closes the popup before the button sees the
        # click.  If the popup *just* closed (<200ms ago), this click
        # was intended to close it -- suppress the reopen and clear focus.
        if time.monotonic() - self._popup_close_time < 0.20:
            self.clearFocus()
            return

        self._show_popup()

    def _show_popup(self, force_above: Optional[bool] = None) -> None:
        popup = self._ensure_popup()
        popup.reposition(self, force_above=force_above)
        popup.show()

        if self._editable:
            popup.set_edit_text(self._confirmed_text)
            popup.focus_edit()
            popup.restore_checkbox_state(self._search_as_edit)
        elif self._searchable:
            popup.focus_search()
        else:
            popup.setFocus()

        self._opened = True
        self.update()

    def _on_popup_closed(self) -> None:
        self._opened = False
        self._popup_close_time = time.monotonic()
        if self._search_mode:
            # Remove app-level event filter for click-outside-to-close
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        else:
            self.clearFocus()
        self.update()

    def _on_flip_requested(self) -> None:
        """Flip the popup to the opposite side of the button."""
        if self._popup is None:
            return
        new_above = not self._popup.is_above
        self._popup.reposition(self, force_above=new_above)
        self._popup.show()

    def _on_item_selected(self, index: int) -> None:
        if self._popup is not None:
            self._popup.close()
        old = self._current_index
        self._current_index = index
        # In editable mode, also update confirmed text
        if self._editable and 0 <= index < len(self._items):
            self._confirmed_text = self._items[index].text
        self._sync_edit_to_selection()
        self.update()
        if old != index:
            self.currentIndexChanged.emit(index)
            self.currentTextChanged.emit(self.current_text)

        # Search mode: reset selection and clear text after signal delivery
        if self._search_mode:
            self._current_index = -1
            if self._search_field is not None:
                self._search_field.clear()

    def _move_selection(self, direction: int) -> None:
        """Move selection up or down by one non-separator, enabled item."""
        if not self._items:
            return
        start = self._current_index
        idx = start
        for _ in range(len(self._items)):
            idx = (idx + direction) % len(self._items)
            d = self._items[idx]
            if not d.is_separator and d.enabled:
                self._on_item_selected(idx)
                return

    # -- Editable mode (popup-based) -----------------------------------------

    def _on_popup_edit_confirmed(self, text: str) -> None:
        """Handle confirmed text from the popup edit field."""
        self._confirmed_text = text

        # Close popup
        if self._opened and self._popup is not None:
            self._popup.close()

        # If the typed text matches an item exactly, select it
        idx = self.find_text(text)
        if idx >= 0:
            old = self._current_index
            self._current_index = idx
            self.update()
            if old != idx:
                self.currentIndexChanged.emit(idx)
                self.currentTextChanged.emit(self.current_text)
        else:
            # Freetext
            self._current_index = -1
            self.update()
            self.currentIndexChanged.emit(-1)
            self.currentTextChanged.emit(text)

        self.clearFocus()

    def _on_popup_edit_text_changed(self, text: str) -> None:
        """Handle text changes from the popup edit field."""
        self.editTextChanged.emit(text)
        self._update_popup_ghost(text)

    def _on_popup_ghost_accept(self) -> None:
        """Accept ghost autocomplete in the popup edit field (Tab key)."""
        if self._popup is None or self._popup.edit_field is None:
            return
        edit = self._popup.edit_field
        ghost = edit.ghost_suffix
        if not ghost:
            return
        full_text = edit.text() + ghost
        edit.setText(full_text)
        edit.ghost_suffix = ""

    def _update_popup_ghost(self, typed: str) -> None:
        """Find the best autocomplete match and update popup edit ghost."""
        if self._popup is None or self._popup.edit_field is None:
            return
        edit = self._popup.edit_field

        if not typed:
            edit.ghost_suffix = ""
            return

        typed_lower = typed.lower()
        for d in self._items:
            if d.is_separator or not d.enabled:
                continue
            if d.text.lower().startswith(typed_lower):
                edit.ghost_suffix = d.text[len(typed):]
                return

        edit.ghost_suffix = ""

    def _on_checkbox_toggled(self, checked: bool) -> None:
        """Persist checkbox state when toggled inside the popup."""
        self._search_as_edit = checked

    def _sync_edit_to_selection(self) -> None:
        """Sync the confirmed text to the current selection."""
        if not self._editable:
            return
        current = self._current_item()
        if current is not None:
            self._confirmed_text = current.text

    # -- Search mode handlers ------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802
        """Forward keyboard navigation and handle click-outside-to-close."""
        # Inline search field: forward Up/Down/Escape to popup
        if obj is self._search_field and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                if self._popup is not None and self._opened:
                    self._popup.keyPressEvent(event)
                return True
            if key == Qt.Key.Key_Escape:
                if self._popup is not None and self._opened:
                    self._popup.close()
                return True

        # App-level: close popup when clicking outside
        if (self._search_mode and self._opened and self._popup is not None
                and event.type() == QEvent.Type.MouseButtonPress):
            target = obj
            is_inside = (
                target is self._search_field
                or target is self._popup
                or (isinstance(target, QWidget)
                    and self._popup.isAncestorOf(target))
            )
            if not is_inside:
                self._popup.close()

        return super().eventFilter(obj, event)

    def _on_search_mode_text_edited(self, text: str) -> None:
        """Handle typing in the inline search field."""
        if self._search_emits_text_changed:
            self.editTextChanged.emit(text)
            # In external-search mode, popup is managed by the consumer
            # via show_search_popup(). Only close on short/empty text.
            if len(text) < 2:
                if self._popup is not None and self._opened:
                    self._popup.close()
                    self._opened = False
            return

        if len(text) < 2:
            if self._popup is not None and self._opened:
                self._popup.close()
            return
        popup = self._ensure_popup()
        popup.apply_filter(text)
        if not self._opened:
            popup.reposition(self)
            popup.show()
            self._opened = True
            self.update()
            # Install app-level event filter for click-outside-to-close
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)

    def _on_search_mode_return(self) -> None:
        """Select the keyboard-hovered item, or the first visible item."""
        if self._popup is None or not self._opened:
            return
        items = [
            w for w in self._popup.item_widgets
            if isinstance(w, _ComboItemWidget)
            and w.isVisible() and w.isEnabled()
        ]
        if not items:
            return
        # If the user navigated with arrow keys, select the hovered item
        if self._popup._kb_navigated:
            hovered = next((w for w in items if w.is_hovered), None)
            if hovered is not None:
                # noinspection PyUnresolvedReferences
                hovered.clicked.emit(hovered.index)
                return
        # Otherwise fall back to the first visible item
        # noinspection PyUnresolvedReferences
        items[0].clicked.emit(items[0].index)

    # -- Internal ------------------------------------------------------------

    def _update_cursor(self) -> None:
        """Set cursor based on mode."""
        if self._display_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _current_item(self) -> Optional[ComboItemDef]:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return None

    def _real_index(self, visible_index: int) -> Optional[int]:
        """Map a visible (non-separator) index to the real _items index."""
        count = 0
        for i, d in enumerate(self._items):
            if not d.is_separator:
                if count == visible_index:
                    return i
                count += 1
        return None

    def _invalidate(self) -> None:
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None

    def _ensure_popup(self) -> _ComboPopup:
        if self._popup is not None:
            self._popup.set_theme(self._theme_obj())
            # Update selected states
            for w in self._popup.item_widgets:
                if isinstance(w, _ComboItemWidget):
                    w.set_selected(w.index == self._current_index)
            return self._popup

        t = self._theme_obj()

        # Show flip buttons when the list is long enough that it might
        # need to be repositioned
        non_sep_count = sum(1 for d in self._items if not d.is_separator)
        show_flip = non_sep_count > 8

        popup = _ComboPopup(
            t,
            searchable=self._searchable and not self._search_mode,
            editable=self._editable,
            show_flip_buttons=show_flip,
            no_focus_steal=self._search_mode,
            invalid_prefixes=self._invalid_prefixes,
            invalid_suffixes=self._invalid_suffixes,
        )
        if self._search_mode:
            popup._keyword_filter = True

        has_icons = any(
            d.icon is not None and not d.icon.isNull()
            for d in self._items
            if not d.is_separator
        )

        # Match popup width to button width (minimum)
        min_popup_w = self.width() + 2 * _ComboPopup.SHADOW_MARGIN

        for i, item_def in enumerate(self._items):
            if item_def.is_separator:
                w = _ComboSeparatorWidget(t, popup)
                popup.add_widget(w, item_def)
            elif self._item_factory is not None:
                w = self._item_factory(i, item_def, t, popup)
                # noinspection PyUnresolvedReferences
                w.clicked.connect(self._on_item_selected)
                popup.add_widget(w, item_def)
            else:
                w = _ComboItemWidget(
                    index=i,
                    item_def=item_def,
                    theme=t,
                    is_selected=(i == self._current_index),
                    has_any_icons=has_icons,
                    parent=popup,
                )
                # noinspection PyUnresolvedReferences
                w.clicked.connect(self._on_item_selected)
                popup.add_widget(w, item_def)

        popup.setMinimumWidth(min_popup_w)
        # noinspection PyUnresolvedReferences
        popup.closed.connect(self._on_popup_closed)
        # noinspection PyUnresolvedReferences
        popup.flip_requested.connect(self._on_flip_requested)

        # Wire editable mode signals
        if self._editable:
            # noinspection PyUnresolvedReferences
            popup.edit_confirmed.connect(self._on_popup_edit_confirmed)
            # noinspection PyUnresolvedReferences
            popup.edit_text_changed.connect(self._on_popup_edit_text_changed)
            # noinspection PyUnresolvedReferences
            popup.ghost_accept_requested.connect(self._on_popup_ghost_accept)
            if popup._checkbox is not None:
                # noinspection PyUnresolvedReferences
                popup._checkbox.toggled.connect(self._on_checkbox_toggled)

        # Set initial scroll height based on item count so the popup
        # has the correct size before the first reposition/show
        popup.update_scroll_height()

        self._popup = popup
        return popup
