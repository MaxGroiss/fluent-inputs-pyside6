"""Windows 11 Fluent Design Custom Context Menu for PySide6.

A fully custom, high-performance context menu that does **not** use ``QMenu``.
Instead, it is built from a frameless, translucent ``QWidget`` popup with
``QPainter``-drawn rounded corners, soft drop shadow, and individually
hover-tracked item widgets.  This avoids all the well-known QSS artefact
and event-handling issues that plague ``QMenu`` when you try to give it a
modern look.

Architecture
------------
*   **_MenuPopup** -- lightweight top-level ``QWidget`` (frameless, translucent
    background, ``Popup`` window type so it auto-closes on outside click).
    Handles ``paintEvent`` to draw the rounded-rect background + shadow.
*   **_MenuItemWidget** -- small ``QWidget`` per row.  Tracks mouse enter/leave
    to paint the Windows 11 pill-shaped hover highlight.  Emits ``clicked``.
*   **_SeparatorWidget** -- thin horizontal line.
*   **FluentContextMenu** -- public API.  Collects item definitions, builds
    the popup lazily on first show, and manages attach/detach via the
    standard ``customContextMenuRequested`` signal on target widgets.

Icons
-----
Pass any ``QIcon`` -- including SVG -- to ``add_item(icon=...)``.  For SVG
files simply use ``QIcon("path/to/file.svg")``.  You can also create icons
from raw SVG strings using the helper ``svg_to_icon()`` provided in this
module.  Icons are automatically rendered at the correct size (16x16) and
respect the current theme via optional ``color`` parameter on the icon helper.

Return Values / Reacting to Clicks
-----------------------------------
There are **three** complementary patterns -- use whichever fits best:

1.  **Callback** (fire-and-forget)::

        menu.add_item("Save", callback=lambda: doc.save())

2.  **Signal** (observer pattern)::

        menu.action_triggered.connect(on_action)
        # on_action receives (item_text: str, item_def: MenuItemDef)

3.  **ItemDef reference** (stateful / checkable items)::

        grid_item = menu.add_item("Show Grid", checkable=True, checked=True)
        # Later, after user interacts:
        if grid_item.checked:
            enable_grid()

Features
--------
-   Pixel-perfect rounded corners (pure QPainter -- no QSS artefacts).
-   Soft, configurable drop shadow painted inside the translucent margin.
-   Smooth hover highlight with rounded-rect pill shape.
-   Full SVG / QIcon support with optional theme-aware colorisation.
-   Light / dark theme via simple ``dark_mode`` bool (constructor or property).
-   Icons, keyboard-shortcut labels, disabled state, checkable items.
-   Radio-button groups via ``exclusive_group`` (one checked at a time).
-   Submenus (nested ``FluentContextMenu``).
-   Attach to **any** ``QWidget`` with one call.
-   Correct popup lifecycle: auto-close on outside click, Escape key,
    and clicking an item.  Reopens reliably every time.
-   Keyboard navigation (Up / Down / Enter / Escape).
-   No external dependencies beyond PySide6 >= 6.7.

License
-------
MIT -- see LICENSE file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, List, Optional

from PySide6.QtCore import (
    QByteArray,
    QObject,
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
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# SVG icon helper
# ---------------------------------------------------------------------------

def svg_to_icon(
    svg_string: str,
    size: int = 16,
    color: Optional[QColor] = None,
) -> QIcon:
    """Create a ``QIcon`` from a raw SVG string.

    This is a convenience for embedding small SVG icons directly in Python
    source without needing external ``.svg`` files.

    Args:
        svg_string: Complete SVG markup (``<svg ...>...</svg>``).
        size:       Pixel size for the rendered pixmap (square).
        color:      If given, every ``stroke="currentColor"`` and
                    ``fill="currentColor"`` in the SVG is replaced with
                    this colour before rendering.  Handy for making a
                    single-colour icon adapt to light / dark themes.

    Returns:
        A ``QIcon`` ready to pass to ``add_item(icon=...)``.
    """
    svg_bytes = svg_string.encode("utf-8")

    if color is not None:
        hex_col = color.name()
        svg_bytes = (
            svg_bytes
            .replace(b'stroke="currentColor"', f'stroke="{hex_col}"'.encode())
            .replace(b'fill="currentColor"', f'fill="{hex_col}"'.encode())
            .replace(b"stroke='currentColor'", f"stroke='{hex_col}'".encode())
            .replace(b"fill='currentColor'", f"fill='{hex_col}'".encode())
        )

    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Theme:
    """Immutable colour / metric bundle for one theme variant."""

    popup_bg: QColor
    popup_border: QColor

    item_text: QColor
    item_text_disabled: QColor
    item_shortcut: QColor
    item_hover_bg: QColor
    item_pressed_bg: QColor
    item_check_color: QColor

    separator_color: QColor
    shadow_color: QColor

    icon_color: QColor  # For theme-aware icon colorisation

    border_radius: int = 8
    shadow_radius: int = 16
    item_height: int = 32
    item_radius: int = 4
    item_h_pad: int = 12
    icon_size: int = 16
    font_size: int = 13
    shortcut_font_size: int = 12


DARK = _Theme(
    popup_bg=QColor(43, 43, 43),
    popup_border=QColor(60, 60, 60),
    item_text=QColor(228, 228, 228),
    item_text_disabled=QColor(110, 110, 110),
    item_shortcut=QColor(154, 154, 154),
    item_hover_bg=QColor(61, 61, 61),
    item_pressed_bg=QColor(51, 51, 51),
    item_check_color=QColor(76, 194, 255),
    separator_color=QColor(60, 60, 60),
    shadow_color=QColor(0, 0, 0, 100),
    icon_color=QColor(228, 228, 228),
)

LIGHT = _Theme(
    popup_bg=QColor(249, 249, 249),
    popup_border=QColor(229, 229, 229),
    item_text=QColor(26, 26, 26),
    item_text_disabled=QColor(160, 160, 160),
    item_shortcut=QColor(110, 110, 110),
    item_hover_bg=QColor(235, 235, 235),
    item_pressed_bg=QColor(224, 224, 224),
    item_check_color=QColor(0, 95, 184),
    separator_color=QColor(229, 229, 229),
    shadow_color=QColor(0, 0, 0, 50),
    icon_color=QColor(26, 26, 26),
)


# ---------------------------------------------------------------------------
# Item data model (public as MenuItemDef)
# ---------------------------------------------------------------------------

class _ItemKind(Enum):
    ACTION = auto()
    SEPARATOR = auto()
    SUBMENU = auto()


@dataclass(slots=True)
class MenuItemDef:
    """Public data object representing one menu entry.

    Returned by ``FluentContextMenu.add_item()`` so callers can inspect or
    mutate state (e.g. ``item.checked``) after the menu has been shown.

    Attributes:
        text:            Display label.
        shortcut:        Human-readable shortcut string (display only).
        icon:            Optional ``QIcon`` (supports SVG).
        callback:        Slot called on click.
        enabled:         Whether the item is interactive.
        checkable:       Whether a check indicator is shown.
        checked:         Current check state.
        exclusive_group: Optional group name.  Checkable items that share
                         the same group behave like radio buttons -- only
                         one can be checked at a time and it never toggles
                         back off.
    """

    kind: _ItemKind = _ItemKind.ACTION
    text: str = ""
    shortcut: str = ""
    icon: Optional[QIcon] = None
    callback: Optional[Callable[[], None]] = None
    enabled: bool = True
    checkable: bool = False
    checked: bool = False
    exclusive_group: Optional[str] = None
    submenu: Optional["FluentContextMenu"] = None


# ---------------------------------------------------------------------------
# _SeparatorWidget -- thin horizontal rule
# ---------------------------------------------------------------------------

class _SeparatorWidget(QWidget):
    """A 1 px horizontal line with vertical padding."""

    def __init__(self, theme: _Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("menuSeparator")
        self._theme = theme
        self.setFixedHeight(9)

    def set_theme(self, theme: _Theme) -> None:
        """Apply a new theme without recreating the widget."""
        self._theme = theme
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self._theme.separator_color, 1.0))
        y = self.height() / 2.0
        p.drawLine(
            int(self._theme.item_h_pad), int(y),
            int(self.width() - self._theme.item_h_pad), int(y),
        )
        p.end()


# ---------------------------------------------------------------------------
# _MenuItemWidget -- one clickable row
# ---------------------------------------------------------------------------

class _MenuItemWidget(QWidget):
    """Custom-painted menu item with icon, label, shortcut, and hover pill."""

    clicked = Signal()

    # Fixed left margin reserved for icons / check indicators so that
    # labels align consistently whether an icon is present or not.
    _ICON_COLUMN_WIDTH = 28

    def __init__(
        self,
        item_def: MenuItemDef,
        theme: _Theme,
        has_any_icons: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("menuItem")
        self._def = item_def
        self._theme = theme
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

    # -- hover state (used by _MenuPopup for keyboard navigation) -----------

    @property
    def is_hovered(self) -> bool:
        """Whether this item is currently hovered."""
        return self._hovered

    @is_hovered.setter
    def is_hovered(self, value: bool) -> None:
        self._hovered = value

    # -- theme hot-swap ------------------------------------------------------

    def set_theme(self, theme: _Theme) -> None:
        """Apply a new theme without recreating the widget."""
        self._theme = theme
        self.setFixedHeight(theme.item_height)
        self.update()

    # -- size hint for proper popup width ------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802
        """Calculate the minimum width needed for this item's content."""
        t = self._theme

        f = QFont(self.font())
        f.setPixelSize(t.font_size)
        fm = QFontMetrics(f)

        width = t.item_h_pad
        if self._has_any_icons or self._def.checkable:
            width += self._ICON_COLUMN_WIDTH
        width += fm.horizontalAdvance(self._def.text)
        if self._def.shortcut:
            sf = QFont(self.font())
            sf.setPixelSize(t.shortcut_font_size)
            sfm = QFontMetrics(sf)
            width += 32 + sfm.horizontalAdvance(self._def.shortcut)
        if self._def.kind == _ItemKind.SUBMENU:
            width += 20
        width += t.item_h_pad

        return QSize(max(width, 180), t.item_height)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Hover / pressed pill
        if self.isEnabled() and (self._hovered or self._pressed):
            bg = t.item_pressed_bg if self._pressed else t.item_hover_bg
            p.setBrush(bg)
            p.setPen(Qt.PenStyle.NoPen)
            pill = QRectF(4, 0, self.width() - 8, self.height())
            p.drawRoundedRect(pill, t.item_radius, t.item_radius)

        text_col = t.item_text if self.isEnabled() else t.item_text_disabled
        x = t.item_h_pad

        # Icon column (fixed width for alignment)
        if self._has_any_icons or self._def.checkable:
            if self._def.checkable and self._def.checked:
                p.setPen(QPen(t.item_check_color, 2.0))
                cx = x + 6
                cy = self.height() / 2
                p.drawLine(int(cx), int(cy), int(cx + 4), int(cy + 4))
                p.drawLine(int(cx + 4), int(cy + 4), int(cx + 10), int(cy - 4))
            elif self._def.icon is not None and not self._def.icon.isNull():
                pm = self._def.icon.pixmap(QSize(t.icon_size, t.icon_size))
                icon_x = x + (self._ICON_COLUMN_WIDTH - t.icon_size) // 2
                icon_y = (self.height() - t.icon_size) // 2
                p.drawPixmap(icon_x, icon_y, pm)
            x += self._ICON_COLUMN_WIDTH

        # Label
        font = QFont(p.font())
        font.setPixelSize(t.font_size)
        p.setFont(font)
        p.setPen(text_col)
        label_right = self.width() - t.item_h_pad
        if self._def.shortcut:
            sf = QFont(font)
            sf.setPixelSize(t.shortcut_font_size)
            sfm = QFontMetrics(sf)
            label_right -= sfm.horizontalAdvance(self._def.shortcut) + 24
        if self._def.kind == _ItemKind.SUBMENU:
            label_right -= 16
        label_rect = QRectF(x, 0, label_right - x, self.height())
        p.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, self._def.text)

        # Shortcut
        if self._def.shortcut:
            sfont = QFont(font)
            sfont.setPixelSize(t.shortcut_font_size)
            p.setFont(sfont)
            p.setPen(t.item_shortcut if self.isEnabled() else t.item_text_disabled)
            sc_rect = QRectF(0, 0, self.width() - t.item_h_pad, self.height())
            p.drawText(
                sc_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                self._def.shortcut,
            )

        # Submenu arrow
        if self._def.kind == _ItemKind.SUBMENU:
            arrow_x = self.width() - t.item_h_pad - 6
            arrow_y = self.height() / 2
            p.setPen(QPen(text_col, 1.4))
            p.drawLine(
                int(arrow_x), int(arrow_y - 4),
                int(arrow_x + 4), int(arrow_y),
            )
            p.drawLine(
                int(arrow_x + 4), int(arrow_y),
                int(arrow_x), int(arrow_y + 4),
            )

        p.end()

    # -- mouse interaction ---------------------------------------------------

    def enterEvent(self, _event) -> None:  # noqa: N802
        # Clear stale hover on siblings.  This fixes ghost highlights that
        # can linger when a submenu popup stole mouse tracking and the
        # ``leaveEvent`` for the previous row never fired.
        parent = self.parentWidget()
        if parent is not None:
            for child in parent.children():
                if (
                    child is not self
                    and isinstance(child, _MenuItemWidget)
                    and child._hovered
                ):
                    child._hovered = False
                    child.update()
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
                if self._def.checkable:
                    if self._def.exclusive_group:
                        # Radio behaviour: always check, never toggle off.
                        self._def.checked = True
                    else:
                        self._def.checked = not self._def.checked
                self.clicked.emit()


def _set_hover(items: List[_MenuItemWidget], idx: int) -> None:
    """Set the hover state on exactly one item in a list."""
    for i, w in enumerate(items):
        w.is_hovered = (i == idx)
        w.update()


# ---------------------------------------------------------------------------
# _MenuPopup -- the translucent popup container
# ---------------------------------------------------------------------------

class _MenuPopup(QWidget):
    """Frameless translucent popup with QPainter-drawn rounded rect + shadow.

    ``Qt.WindowType.Popup`` ensures auto-close on outside click / Escape.
    """

    SHADOW_MARGIN = 12

    closed = Signal()

    def __init__(self, theme: _Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("menuPopup")
        self._theme = theme
        self._item_widgets: List[QWidget] = []

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

    def add_widget(self, w: QWidget) -> None:
        """Add a menu item or separator widget to the popup layout."""
        self._layout.addWidget(w)
        if isinstance(w, (_MenuItemWidget, _SeparatorWidget)):
            self._item_widgets.append(w)

    def set_theme(self, theme: _Theme) -> None:
        """Apply a new theme to the popup and all child widgets."""
        self._theme = theme
        for w in self._item_widgets:
            if isinstance(w, (_MenuItemWidget, _SeparatorWidget)):
                w.set_theme(theme)
        self.update()

    def reposition(self, global_pos: QPoint) -> None:
        """Move the popup on-screen at *global_pos*, clamping to screen."""
        screen = QApplication.screenAt(global_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()

        self.adjustSize()
        x, y = global_pos.x(), global_pos.y()

        if x + self.width() > avail.right():
            x = avail.right() - self.width()
        if y + self.height() > avail.bottom():
            y = avail.bottom() - self.height()
        x = max(x, avail.left())
        y = max(y, avail.top())

        self.move(x - self.SHADOW_MARGIN, y - self.SHADOW_MARGIN)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._theme
        m = self.SHADOW_MARGIN
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft drop shadow (concentric rounded rects, quadratic falloff).
        # Much faster than QGraphicsDropShadowEffect which rasterises the
        # entire widget into an offscreen pixmap.
        base_a = t.shadow_color.alpha()
        for i in range(m):
            frac = (m - i) / m
            a = int(base_a * frac * frac)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(
                t.shadow_color.red(),
                t.shadow_color.green(),
                t.shadow_color.blue(), a,
            ))
            inset = m - i
            rect = QRectF(
                inset, inset + 2,
                self.width() - 2 * inset,
                self.height() - 2 * inset - 2,
            )
            p.drawRoundedRect(
                rect, t.border_radius + i * 0.5, t.border_radius + i * 0.5,
            )

        # Background rounded rect
        bg = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        p.setBrush(t.popup_bg)
        p.setPen(QPen(t.popup_border, 1.0))
        p.drawRoundedRect(bg, t.border_radius, t.border_radius)
        p.end()

    # -- keyboard navigation -------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return

        items = [w for w in self._item_widgets if isinstance(w, _MenuItemWidget)]
        if not items:
            return

        cur = next((i for i, w in enumerate(items) if w.is_hovered), -1)

        if key == Qt.Key.Key_Down:
            _set_hover(items, (cur + 1) % len(items))
        elif key == Qt.Key.Key_Up:
            _set_hover(items, (cur - 1) % len(items))
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if 0 <= cur < len(items) and items[cur].isEnabled():
                items[cur].clicked.emit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# FluentContextMenu -- public API
# ---------------------------------------------------------------------------

class FluentContextMenu(QObject):
    """Windows 11 Fluent-Design context menu -- no QMenu, fully custom.

    Signals:
        action_triggered(str, MenuItemDef):
            Emitted after any item click with the item text **and** the
            ``MenuItemDef`` reference so you can inspect state like
            ``checked``.

    Args:
        dark_mode: ``True`` for dark theme, ``False`` for light.
                   Can be changed at any time via the ``dark_mode`` property.
        parent:    Optional parent for Qt ownership.

    Example -- callback pattern::

        menu = FluentContextMenu(dark_mode=True)
        menu.add_item("Save", icon=QIcon("save.svg"),
                       shortcut="Ctrl+S", callback=doc.save)
        menu.attach(editor)

    Example -- signal pattern::

        menu = FluentContextMenu()

        def on_action(text: str, item: MenuItemDef):
            print(f"{text} triggered, checked={item.checked}")

        menu.action_triggered.connect(on_action)
        menu.add_item("Bold", checkable=True)
        menu.attach(editor)

    Example -- reference pattern::

        grid = menu.add_item("Show Grid", checkable=True, checked=True)
        # ... later, after user interaction:
        if grid.checked:
            canvas.show_grid()

    Example -- radio group::

        menu.add_item("Small",  checkable=True, exclusive_group="size")
        menu.add_item("Medium", checkable=True, checked=True,
                       exclusive_group="size")
        menu.add_item("Large",  checkable=True, exclusive_group="size")
    """

    action_triggered = Signal(str, object)

    def __init__(
        self,
        dark_mode: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._dark_mode = dark_mode
        self._items: List[MenuItemDef] = []
        self._popup: Optional[_MenuPopup] = None
        self._attached: List[QWidget] = []

    # -- Properties ----------------------------------------------------------

    @property
    def dark_mode(self) -> bool:
        """Current theme flag.  Setting this invalidates the popup cache."""
        return self._dark_mode

    @dark_mode.setter
    def dark_mode(self, value: bool) -> None:
        if self._dark_mode != value:
            self._dark_mode = value
            self._invalidate()

    # -- Building the menu ---------------------------------------------------

    def add_item(
        self,
        text: str,
        *,
        callback: Optional[Callable[[], None]] = None,
        icon: Optional[QIcon] = None,
        shortcut: str = "",
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        exclusive_group: Optional[str] = None,
    ) -> MenuItemDef:
        """Add an action item.

        Args:
            text:      Display label.
            callback:  Slot called on click (receives no arguments).
            icon:      Optional ``QIcon``.  Use ``QIcon("file.svg")`` for SVG
                       or the ``svg_to_icon()`` helper for inline SVG strings.
            shortcut:  Display-only shortcut string (e.g. ``"Ctrl+X"``).
            enabled:   Whether the item is interactive.
            checkable: Show a check indicator.
            checked:   Initial check state.
            exclusive_group: Optional group name.  Checkable items sharing a
                       group behave like radio buttons -- exactly one stays
                       checked and clicking never toggles the active one off.

        Returns:
            A ``MenuItemDef`` reference.  You can read ``item.checked``
            at any time to get the current state.
        """
        d = MenuItemDef(
            kind=_ItemKind.ACTION, text=text, shortcut=shortcut,
            icon=icon, callback=callback, enabled=enabled,
            checkable=checkable, checked=checked,
            exclusive_group=exclusive_group,
        )
        self._items.append(d)
        self._invalidate()
        return d

    def add_separator(self) -> None:
        """Add a horizontal separator line."""
        self._items.append(MenuItemDef(kind=_ItemKind.SEPARATOR))
        self._invalidate()

    def add_submenu(
        self,
        text: str,
        *,
        icon: Optional[QIcon] = None,
    ) -> "FluentContextMenu":
        """Add a submenu entry and return the child ``FluentContextMenu``."""
        child = FluentContextMenu(dark_mode=self._dark_mode, parent=self)
        d = MenuItemDef(kind=_ItemKind.SUBMENU, text=text, icon=icon, submenu=child)
        self._items.append(d)
        self._invalidate()
        return child

    def clear(self) -> None:
        """Remove all items."""
        self._items.clear()
        self._invalidate()

    # -- Attach / detach -----------------------------------------------------

    def attach(self, widget: QWidget) -> None:
        """Attach this context menu to *widget* (right-click opens it)."""
        if widget not in self._attached:
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(self._on_request)
            self._attached.append(widget)

    def detach(self, widget: QWidget) -> None:
        """Remove the context menu from *widget*."""
        if widget in self._attached:
            try:
                widget.customContextMenuRequested.disconnect(self._on_request)
            except RuntimeError:
                pass
            self._attached.remove(widget)

    # -- Show ----------------------------------------------------------------

    def show_at(self, global_pos: QPoint) -> None:
        """Show the menu at *global_pos* (screen coordinates)."""
        popup = self._ensure_popup()
        popup.reposition(global_pos)
        popup.show()
        popup.setFocus()

    # -- Internal ------------------------------------------------------------

    def _on_request(self, local_pos: QPoint) -> None:
        widget = self.sender()
        if isinstance(widget, QWidget):
            self.show_at(widget.mapToGlobal(local_pos))

    def _invalidate(self) -> None:
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None

    def _theme_obj(self) -> _Theme:
        return DARK if self._dark_mode else LIGHT

    def _ensure_popup(self) -> _MenuPopup:
        if self._popup is not None:
            self._popup.set_theme(self._theme_obj())
            return self._popup

        t = self._theme_obj()
        popup = _MenuPopup(t)

        has_icons = any(
            d.icon is not None and not d.icon.isNull()
            for d in self._items
            if d.kind != _ItemKind.SEPARATOR
        )

        for item_def in self._items:
            if item_def.kind == _ItemKind.SEPARATOR:
                popup.add_widget(_SeparatorWidget(t, popup))
            else:
                w = _MenuItemWidget(
                    item_def, t, has_any_icons=has_icons, parent=popup,
                )
                if item_def.kind == _ItemKind.SUBMENU:
                    w.clicked.connect(
                        lambda _d=item_def, _p=popup: self._open_submenu(_d, _p)
                    )
                else:
                    w.clicked.connect(
                        lambda _d=item_def, _p=popup: self._trigger(_d, _p)
                    )
                popup.add_widget(w)

        self._popup = popup
        return popup

    def _trigger(self, item_def: MenuItemDef, popup: _MenuPopup) -> None:
        # Enforce exclusive group: uncheck the other members.
        if item_def.exclusive_group:
            for other in self._items:
                if (
                    other is not item_def
                    and other.exclusive_group == item_def.exclusive_group
                    and other.checkable
                ):
                    other.checked = False
        popup.close()
        self.action_triggered.emit(item_def.text, item_def)
        if item_def.callback is not None:
            item_def.callback()

    @staticmethod
    def _open_submenu(item_def: MenuItemDef, popup: _MenuPopup) -> None:
        if item_def.submenu is None:
            return
        right = popup.mapToGlobal(
            QPoint(popup.width() - _MenuPopup.SHADOW_MARGIN, 0),
        )
        item_def.submenu.show_at(right)
