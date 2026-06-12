"""FluentSpinBox / FluentDoubleSpinBox -- Fluent Design spin boxes for PySide6.

Drop-in replacements for ``QSpinBox`` and ``QDoubleSpinBox`` with the same
public API.  Built from scratch as composite QWidgets (an internal line edit
plus custom up/down chevron buttons) to avoid the native QAbstractSpinBox
chrome that is hard to theme consistently.

Usage::

    spin = FluentSpinBox(dark_mode=True, parent=self)
    spin.setRange(0, 100)
    spin.setValue(42)
    spin.valueChanged.connect(on_value_changed)

    dspin = FluentDoubleSpinBox(dark_mode=True, parent=self)
    dspin.setRange(0.0, 1.0)
    dspin.setSingleStep(0.1)
    dspin.setDecimals(2)

Features
--------
-   Custom rounded border, hover + focus states, Win11 bottom accent line.
-   Chevron up/down buttons with hover/press feedback and press-and-hold
    auto-repeat.
-   Mouse-wheel and Up/Down key stepping; prefix/suffix; special value text;
    wrapping.
-   ``display_mode`` -- transparent, read-only, label-like view state.
-   Light / dark theme via a single ``dark_mode`` bool.
-   No external dependencies beyond PySide6 >= 6.7.

License
-------
MIT -- see LICENSE file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import (
    QEvent,
    QRectF,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPalette,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractSpinBox, QHBoxLayout, QWidget


# ---------------------------------------------------------------------------
# Theme colour bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Theme:
    """Immutable colour bundle for spin box states."""

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
# Constants
# ---------------------------------------------------------------------------

_BUTTON_WIDTH = 24
_BUTTON_GAP = 2
_ARROW_SIZE = 5
_REPEAT_DELAY_MS = 500
_REPEAT_INTERVAL_MS = 50


# ---------------------------------------------------------------------------
# Internal line edit (no border -- the parent draws it)
# ---------------------------------------------------------------------------

class _InternalLineEdit(QWidget):
    """Minimal internal text editor for the spin box.

    A thin wrapper that renders text without drawing its own border.  The
    parent spin box owns the outer border and background.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit, QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._edit = QLineEdit(self)
        self._edit.setObjectName("fluentSpinBoxInput")
        self._edit.setFrame(False)
        self._edit.setReadOnly(True)
        self._edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._edit.setCursor(Qt.CursorShape.ArrowCursor)
        self._edit.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none; }"
        )
        self._edit.setTextMargins(6, 0, 2, 0)
        layout.addWidget(self._edit)

    @property
    def edit(self):
        return self._edit

    def text(self) -> str:
        return self._edit.text()

    def setText(self, text: str) -> None:  # noqa: N802
        self._edit.setText(text)

    def setAlignment(self, a) -> None:  # noqa: N802
        self._edit.setAlignment(a)

    def apply_palette(self, text_color: QColor) -> None:
        pal = self._edit.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, text_color)
        self._edit.setPalette(pal)


# ---------------------------------------------------------------------------
# Base spin box widget
# ---------------------------------------------------------------------------

class _FluentSpinBoxBase(QWidget):
    """Base class for FluentSpinBox and FluentDoubleSpinBox.

    Implements the shared rendering, button logic, and event handling.
    Subclasses define the value type, validation, and text conversion.
    """

    # Subclasses re-declare with correct type
    valueChanged = Signal(int)
    textChanged = Signal(str)

    # -- StepEnabled flags (mirror QAbstractSpinBox) --
    StepNone = QAbstractSpinBox.StepEnabledFlag.StepNone
    StepUpEnabled = QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
    StepDownEnabled = QAbstractSpinBox.StepEnabledFlag.StepDownEnabled

    def __init__(
        self,
        dark_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentSpinBox")

        self._dark_mode: bool = dark_mode
        self._display_mode: bool = False
        self._hovered: bool = False
        self._up_hovered: bool = False
        self._down_hovered: bool = False
        self._up_pressed: bool = False
        self._down_pressed: bool = False
        self._wrapping: bool = False
        self._read_only: bool = False
        self._keyboard_tracking: bool = True
        self._prefix: str = ""
        self._suffix: str = ""
        self._special_value_text: str = ""
        self._accelerated: bool = False
        self._correctionMode: QAbstractSpinBox.CorrectionMode = (
            QAbstractSpinBox.CorrectionMode.CorrectToPreviousValue
        )

        # Repeat timer for press-and-hold
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setInterval(_REPEAT_INTERVAL_MS)
        self._repeat_timer.timeout.connect(self._on_repeat_tick)
        self._repeat_direction: int = 0  # +1 = up, -1 = down

        # Layout: line edit takes available space, buttons are painted on top
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, _BUTTON_WIDTH * 2 + _BUTTON_GAP, 0)
        layout.setSpacing(0)

        self._line_edit = _InternalLineEdit(self)
        layout.addWidget(self._line_edit)

        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)

        self._apply_theme()
        self.setMinimumHeight(28)

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
        """When True the widget is non-interactive (view mode)."""
        return self._display_mode

    @display_mode.setter
    def display_mode(self, value: bool) -> None:
        if self._display_mode == value:
            return
        self._display_mode = value
        if value:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        else:
            self.unsetCursor()
            self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.update()

    # -- QAbstractSpinBox compatible API ------------------------------------

    def prefix(self) -> str:
        return self._prefix

    def setPrefix(self, prefix: str) -> None:  # noqa: N802
        self._prefix = prefix
        self._update_display()
        self._update_fixed_width()

    def suffix(self) -> str:
        return self._suffix

    def setSuffix(self, suffix: str) -> None:  # noqa: N802
        self._suffix = suffix
        self._update_display()
        self._update_fixed_width()

    def specialValueText(self) -> str:  # noqa: N802
        return self._special_value_text

    def setSpecialValueText(self, text: str) -> None:  # noqa: N802
        self._special_value_text = text
        self._update_display()
        self._update_fixed_width()

    def wrapping(self) -> bool:
        return self._wrapping

    def setWrapping(self, wrapping: bool) -> None:  # noqa: N802
        self._wrapping = wrapping

    def isReadOnly(self) -> bool:  # noqa: N802
        return self._read_only

    def setReadOnly(self, read_only: bool) -> None:  # noqa: N802
        self._read_only = read_only
        self.update()

    def keyboardTracking(self) -> bool:  # noqa: N802
        return self._keyboard_tracking

    def setKeyboardTracking(self, tracking: bool) -> None:  # noqa: N802
        self._keyboard_tracking = tracking

    def isAccelerated(self) -> bool:  # noqa: N802
        return self._accelerated

    def setAccelerated(self, accelerated: bool) -> None:  # noqa: N802
        self._accelerated = accelerated

    def correctionMode(self) -> QAbstractSpinBox.CorrectionMode:  # noqa: N802
        return self._correctionMode

    def setCorrectionMode(self, mode: QAbstractSpinBox.CorrectionMode) -> None:  # noqa: N802
        self._correctionMode = mode

    def setAlignment(self, alignment) -> None:  # noqa: N802
        self._line_edit.setAlignment(alignment)

    def clear(self) -> None:
        self._set_value_to_minimum()

    def stepUp(self) -> None:  # noqa: N802
        self.stepBy(1)

    def stepDown(self) -> None:  # noqa: N802
        self.stepBy(-1)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self._line_edit.edit.setEnabled(enabled)
        self.update()

    # -- Abstract interface (subclasses implement) --------------------------

    def stepBy(self, steps: int) -> None:  # noqa: N802
        raise NotImplementedError

    def stepEnabled(self) -> QAbstractSpinBox.StepEnabledFlag:  # noqa: N802
        raise NotImplementedError

    def _update_display(self) -> None:
        raise NotImplementedError

    def _set_value_to_minimum(self) -> None:
        raise NotImplementedError

    # -- Size hints ---------------------------------------------------------

    def _compute_text_width(self) -> int:
        """Compute the width needed for the longest possible display text."""
        raise NotImplementedError

    def _update_fixed_width(self) -> None:
        """Recalculate and apply the fixed width based on content."""
        text_w = self._compute_text_width()
        buttons_w = _BUTTON_WIDTH * 2 + _BUTTON_GAP
        padding = 20  # left/right margins inside the line edit
        w = text_w + buttons_w + padding
        self.setFixedWidth(w)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        h = max(28, fm.height() + 12)
        text_w = self._compute_text_width()
        buttons_w = _BUTTON_WIDTH * 2 + _BUTTON_GAP
        w = text_w + buttons_w + 20
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    # -- Button geometry ----------------------------------------------------

    def _up_button_rect(self) -> QRectF:
        bw = _BUTTON_WIDTH
        bh = self.height() - 6
        x = self.width() - bw - 3
        y = 3
        return QRectF(x, y, bw, bh)

    def _down_button_rect(self) -> QRectF:
        bw = _BUTTON_WIDTH
        bh = self.height() - 6
        x = self.width() - bw * 2 - _BUTTON_GAP - 3
        y = 3
        return QRectF(x, y, bw, bh)

    def _hit_test_button(self, pos) -> int:
        """Return +1 for up, -1 for down, 0 for no button hit."""
        if self._up_button_rect().contains(pos.x(), pos.y()):
            return 1
        if self._down_button_rect().contains(pos.x(), pos.y()):
            return -1
        return 0

    # -- Theme helpers ------------------------------------------------------

    def _apply_theme(self) -> None:
        t = self._theme_obj()
        self._line_edit.apply_palette(t.text)

    # -- Repeat timer -------------------------------------------------------

    def _start_repeat(self, direction: int) -> None:
        self._repeat_direction = direction
        self._repeat_timer.start(_REPEAT_DELAY_MS)

    def _stop_repeat(self) -> None:
        self._repeat_timer.stop()
        self._repeat_direction = 0

    def _on_repeat_tick(self) -> None:
        if self._repeat_direction != 0:
            self.stepBy(self._repeat_direction)
            # Switch to fast interval after initial delay
            if self._repeat_timer.interval() != _REPEAT_INTERVAL_MS:
                self._repeat_timer.setInterval(_REPEAT_INTERVAL_MS)

    # -- Qt events ----------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._display_mode or self._read_only:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Up:
            self.stepUp()
            event.accept()
        elif key == Qt.Key.Key_Down:
            self.stepDown()
            event.accept()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.FontChange:
            self._line_edit.edit.setFont(self.font())
            self._update_fixed_width()
        super().changeEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._up_hovered = False
        self._down_hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        hit = self._hit_test_button(event.pos())
        self._up_hovered = hit == 1
        self._down_hovered = hit == -1
        if hit != 0 and not self._display_mode and not self._read_only:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._display_mode or self._read_only:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        hit = self._hit_test_button(event.pos())
        if hit == 1:
            self._up_pressed = True
            self.stepUp()
            self._start_repeat(1)
            self.update()
            event.accept()
        elif hit == -1:
            self._down_pressed = True
            self.stepDown()
            self._start_repeat(-1)
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._up_pressed = False
            self._down_pressed = False
            self._stop_repeat()
            self.update()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._display_mode or self._read_only:
            event.ignore()
            return
        if not self.hasFocus():
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta > 0:
            self.stepUp()
        elif delta < 0:
            self.stepDown()
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self._theme_obj()
        focused = self.hasFocus()
        enabled = self.isEnabled()

        # Determine border/bg
        if not enabled:
            bg = t.bg
            border_color = t.border
            border_width = 1.0
        elif self._display_mode:
            # In display mode, skip border/bg -- text still visible via the
            # internal line edit (read-only, transparent background).
            # No buttons drawn either.
            return
        elif focused:
            bg = t.bg
            border_color = t.border_focus
            border_width = 1.5
        elif self._hovered:
            bg = t.bg_hover
            border_color = t.border_hover
            border_width = 1.0
        else:
            bg = t.bg
            border_color = t.border
            border_width = 1.0

        inset = border_width / 2
        rect = QRectF(
            inset, inset,
            self.width() - 2 * inset,
            self.height() - 2 * inset,
        )
        r = t.border_radius

        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        p.fillPath(path, bg)

        # Border
        p.setPen(QPen(border_color, border_width))
        p.drawPath(path)

        # Bottom accent when focused
        if focused:
            accent_h = 2.0
            accent_margin = r + inset
            p.fillRect(
                QRectF(
                    accent_margin,
                    self.height() - accent_h,
                    self.width() - 2 * accent_margin,
                    accent_h,
                ),
                t.border_focus,
            )

        # Draw up/down buttons
        if not self._display_mode:
            self._paint_button(
                p, self._up_button_rect(), up=True,
                hovered=self._up_hovered, pressed=self._up_pressed,
                enabled=enabled and bool(
                    self.stepEnabled() & self.StepUpEnabled
                ),
                theme=t,
            )
            self._paint_button(
                p, self._down_button_rect(), up=False,
                hovered=self._down_hovered, pressed=self._down_pressed,
                enabled=enabled and bool(
                    self.stepEnabled() & self.StepDownEnabled
                ),
                theme=t,
            )

        p.end()

    def _paint_button(
        self, p: QPainter, rect: QRectF, *,
        up: bool, hovered: bool, pressed: bool, enabled: bool, theme: _Theme,
    ) -> None:
        """Paint a single up or down arrow button."""
        r = 4.0

        # Button background on hover/press
        if pressed and enabled:
            btn_bg = QColor(theme.text)
            btn_bg.setAlphaF(0.1)
            btn_path = QPainterPath()
            btn_path.addRoundedRect(rect, r, r)
            p.fillPath(btn_path, btn_bg)
        elif hovered and enabled:
            btn_bg = QColor(theme.text)
            btn_bg.setAlphaF(0.05)
            btn_path = QPainterPath()
            btn_path.addRoundedRect(rect, r, r)
            p.fillPath(btn_path, btn_bg)

        # Arrow
        arrow_color = QColor(theme.text)
        if not enabled:
            arrow_color.setAlphaF(0.3)
        elif pressed:
            arrow_color.setAlphaF(0.8)

        cx = rect.center().x()
        cy = rect.center().y()
        sz = _ARROW_SIZE

        p.setPen(QPen(arrow_color, 1.5, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if up:
            # Chevron pointing up
            p.drawLine(
                int(cx - sz), int(cy + sz * 0.4),
                int(cx), int(cy - sz * 0.4),
            )
            p.drawLine(
                int(cx), int(cy - sz * 0.4),
                int(cx + sz), int(cy + sz * 0.4),
            )
        else:
            # Chevron pointing down
            p.drawLine(
                int(cx - sz), int(cy - sz * 0.4),
                int(cx), int(cy + sz * 0.4),
            )
            p.drawLine(
                int(cx), int(cy + sz * 0.4),
                int(cx + sz), int(cy - sz * 0.4),
            )


# ---------------------------------------------------------------------------
# FluentSpinBox (int)
# ---------------------------------------------------------------------------

class FluentSpinBox(_FluentSpinBoxBase):
    """Fluent-styled integer spin box -- QSpinBox API compatible.

    Signals
    -------
    valueChanged(int)
        Emitted when the value changes.
    textChanged(str)
        Emitted when the display text changes.
    """

    valueChanged = Signal(int)
    textChanged = Signal(str)

    def __init__(
        self,
        dark_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(dark_mode, parent)
        self.setObjectName("fluentSpinBox")

        self._value: int = 0
        self._minimum: int = 0
        self._maximum: int = 99
        self._single_step: int = 1

        self._update_display()
        self._update_fixed_width()

    # -- QSpinBox API -------------------------------------------------------

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802
        value = max(self._minimum, min(self._maximum, value))
        if value == self._value:
            return
        self._value = value
        self._update_display()
        self.valueChanged.emit(value)
        self.textChanged.emit(self._line_edit.text())

    def minimum(self) -> int:
        return self._minimum

    def setMinimum(self, minimum: int) -> None:  # noqa: N802
        self._minimum = minimum
        if self._maximum < minimum:
            self._maximum = minimum
        if self._value < minimum:
            self.setValue(minimum)
        self._update_fixed_width()
        self.update()

    def maximum(self) -> int:
        return self._maximum

    def setMaximum(self, maximum: int) -> None:  # noqa: N802
        self._maximum = maximum
        if self._minimum > maximum:
            self._minimum = maximum
        if self._value > maximum:
            self.setValue(maximum)
        self._update_fixed_width()
        self.update()

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self._minimum = minimum
        self._maximum = maximum
        self.setValue(max(minimum, min(maximum, self._value)))
        self._update_fixed_width()

    def singleStep(self) -> int:  # noqa: N802
        return self._single_step

    def setSingleStep(self, step: int) -> None:  # noqa: N802
        self._single_step = step

    def cleanText(self) -> str:  # noqa: N802
        """Return the text without prefix/suffix."""
        return str(self._value)

    def textFromValue(self, value: int) -> str:  # noqa: N802
        """Convert an integer value to display text.

        Override this for custom formatting.
        """
        return str(value)

    def valueFromText(self, text: str) -> int:  # noqa: N802
        """Convert display text to an integer value.

        Override this for custom parsing.
        """
        cleaned = text.strip()
        if self._prefix and cleaned.startswith(self._prefix):
            cleaned = cleaned[len(self._prefix):]
        if self._suffix and cleaned.endswith(self._suffix):
            cleaned = cleaned[:-len(self._suffix)]
        try:
            return int(cleaned.strip())
        except ValueError:
            return self._value

    # -- Internal overrides -------------------------------------------------

    def stepBy(self, steps: int) -> None:  # noqa: N802
        new_val = self._value + steps * self._single_step
        if self._wrapping:
            val_range = self._maximum - self._minimum + 1
            if val_range > 0:
                new_val = self._minimum + (
                    (new_val - self._minimum) % val_range
                )
        else:
            new_val = max(self._minimum, min(self._maximum, new_val))
        self.setValue(new_val)

    def stepEnabled(self) -> QAbstractSpinBox.StepEnabledFlag:  # noqa: N802
        flags = self.StepNone
        if self._wrapping or self._value < self._maximum:
            flags |= self.StepUpEnabled
        if self._wrapping or self._value > self._minimum:
            flags |= self.StepDownEnabled
        return flags

    def _compute_text_width(self) -> int:
        fm = QFontMetrics(self.font())
        # Measure the widest possible text (min and max with prefix/suffix)
        candidates = [
            self._prefix + self.textFromValue(self._minimum) + self._suffix,
            self._prefix + self.textFromValue(self._maximum) + self._suffix,
        ]
        if self._special_value_text:
            candidates.append(self._special_value_text)
        return max(fm.horizontalAdvance(c) for c in candidates)

    def _update_display(self) -> None:
        if (
            self._special_value_text
            and self._value == self._minimum
        ):
            self._line_edit.setText(self._special_value_text)
        else:
            text = self._prefix + self.textFromValue(self._value) + self._suffix
            self._line_edit.setText(text)

    def _set_value_to_minimum(self) -> None:
        self.setValue(self._minimum)


# ---------------------------------------------------------------------------
# FluentDoubleSpinBox (float)
# ---------------------------------------------------------------------------

class FluentDoubleSpinBox(_FluentSpinBoxBase):
    """Fluent-styled floating-point spin box -- QDoubleSpinBox API compatible.

    Signals
    -------
    valueChanged(float)
        Emitted when the value changes.
    textChanged(str)
        Emitted when the display text changes.
    """

    valueChanged = Signal(float)
    textChanged = Signal(str)

    def __init__(
        self,
        dark_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(dark_mode, parent)
        self.setObjectName("fluentDoubleSpinBox")

        self._value: float = 0.0
        self._minimum: float = 0.0
        self._maximum: float = 99.99
        self._single_step: float = 1.0
        self._decimals: int = 2

        self._update_display()
        self._update_fixed_width()

    # -- QDoubleSpinBox API -------------------------------------------------

    def value(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:  # noqa: N802
        value = max(self._minimum, min(self._maximum, value))
        value = round(value, self._decimals)
        if value == self._value:
            return
        self._value = value
        self._update_display()
        self.valueChanged.emit(value)
        self.textChanged.emit(self._line_edit.text())

    def minimum(self) -> float:
        return self._minimum

    def setMinimum(self, minimum: float) -> None:  # noqa: N802
        self._minimum = minimum
        if self._maximum < minimum:
            self._maximum = minimum
        if self._value < minimum:
            self.setValue(minimum)
        self._update_fixed_width()
        self.update()

    def maximum(self) -> float:
        return self._maximum

    def setMaximum(self, maximum: float) -> None:  # noqa: N802
        self._maximum = maximum
        if self._minimum > maximum:
            self._minimum = maximum
        if self._value > maximum:
            self.setValue(maximum)
        self._update_fixed_width()
        self.update()

    def setRange(self, minimum: float, maximum: float) -> None:  # noqa: N802
        self._minimum = minimum
        self._maximum = maximum
        self.setValue(max(minimum, min(maximum, self._value)))
        self._update_fixed_width()

    def singleStep(self) -> float:  # noqa: N802
        return self._single_step

    def setSingleStep(self, step: float) -> None:  # noqa: N802
        self._single_step = step

    def decimals(self) -> int:
        return self._decimals

    def setDecimals(self, decimals: int) -> None:  # noqa: N802
        self._decimals = max(0, decimals)
        self._value = round(self._value, self._decimals)
        self._update_display()
        self._update_fixed_width()

    def cleanText(self) -> str:  # noqa: N802
        return self._format_value(self._value)

    def textFromValue(self, value: float) -> str:  # noqa: N802
        """Convert a float value to display text.

        Override this for custom formatting.
        """
        return self._format_value(value)

    def valueFromText(self, text: str) -> float:  # noqa: N802
        """Convert display text to a float value.

        Override this for custom parsing.
        """
        cleaned = text.strip()
        if self._prefix and cleaned.startswith(self._prefix):
            cleaned = cleaned[len(self._prefix):]
        if self._suffix and cleaned.endswith(self._suffix):
            cleaned = cleaned[:-len(self._suffix)]
        # Support comma as decimal separator (common in European locales)
        cleaned = cleaned.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return self._value

    # -- Internal overrides -------------------------------------------------

    def stepBy(self, steps: int) -> None:  # noqa: N802
        new_val = self._value + steps * self._single_step
        new_val = round(new_val, self._decimals)
        if self._wrapping:
            val_range = self._maximum - self._minimum
            if val_range > 0:
                new_val = self._minimum + (
                    (new_val - self._minimum) % val_range
                )
        else:
            new_val = max(self._minimum, min(self._maximum, new_val))
        self.setValue(new_val)

    def stepEnabled(self) -> QAbstractSpinBox.StepEnabledFlag:  # noqa: N802
        flags = self.StepNone
        if self._wrapping or self._value < self._maximum:
            flags |= self.StepUpEnabled
        if self._wrapping or self._value > self._minimum:
            flags |= self.StepDownEnabled
        return flags

    def _format_value(self, value: float) -> str:
        return f"{value:.{self._decimals}f}"

    def _compute_text_width(self) -> int:
        fm = QFontMetrics(self.font())
        candidates = [
            self._prefix + self.textFromValue(self._minimum) + self._suffix,
            self._prefix + self.textFromValue(self._maximum) + self._suffix,
        ]
        if self._special_value_text:
            candidates.append(self._special_value_text)
        return max(fm.horizontalAdvance(c) for c in candidates)

    def _update_display(self) -> None:
        if (
            self._special_value_text
            and self._value == self._minimum
        ):
            self._line_edit.setText(self._special_value_text)
        else:
            text = (
                self._prefix
                + self.textFromValue(self._value)
                + self._suffix
            )
            self._line_edit.setText(text)

    def _set_value_to_minimum(self) -> None:
        self.setValue(self._minimum)
