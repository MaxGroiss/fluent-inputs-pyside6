"""Interactive demo / screenshot gallery for the Fluent input controls.

Run directly::

    python demo.py

Shows every widget in this repo:

*   **FluentLineEdit** -- edit mode and display (label-like) mode.
*   **FluentTextEdit** -- multi-line, edit and display mode.
*   **FluentSpinBox / FluentDoubleSpinBox** -- chevron steppers.
*   **FluentComboBox** -- basic, searchable, and editable variants.

Right-click any text field for the bundled Fluent context menu.  Toggle
the *Dark Mode* checkbox to switch every control between light and dark
for screenshots.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from fluent_combo_box import FluentComboBox
from fluent_line_edit import FluentLineEdit
from fluent_spin_box import FluentDoubleSpinBox, FluentSpinBox
from fluent_text_edit import FluentTextEdit


class DemoWindow(QMainWindow):
    """Showcases all Fluent input controls together."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fluent Inputs - Demo")
        self.resize(820, 640)
        self._dark = False
        self._themed: list = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Master dark-mode control
        ctrl = QHBoxLayout()
        self._toggle = QCheckBox("Dark Mode")
        self._toggle.toggled.connect(self._on_theme)
        ctrl.addWidget(self._toggle)
        ctrl.addStretch()
        root.addLayout(ctrl)

        cols = QHBoxLayout()
        cols.setSpacing(12)

        # -- Left column: line edit, spin boxes -----------------------------
        left = QVBoxLayout()
        left.setSpacing(12)

        grp_le = QGroupBox("FluentLineEdit")
        le_form = QFormLayout(grp_le)
        le_edit = FluentLineEdit()
        le_edit.setText("Editable field")
        le_disp = FluentLineEdit()
        le_disp.setText("Display mode (label-like)")
        le_disp.display_mode = True
        le_warn = FluentLineEdit()
        le_warn.setPlaceholderText("Type a leading underscore...")
        le_warn.set_invalid_prefixes(["_", "-"])
        le_form.addRow("Edit:", le_edit)
        le_form.addRow("Display:", le_disp)
        le_form.addRow("Affix rule:", le_warn)
        self._themed.extend((le_edit, le_disp, le_warn))
        left.addWidget(grp_le)

        grp_sp = QGroupBox("FluentSpinBox / FluentDoubleSpinBox")
        sp_form = QFormLayout(grp_sp)
        spin = FluentSpinBox()
        spin.setRange(0, 100)
        spin.setValue(42)
        spin.setSuffix(" %")
        dspin = FluentDoubleSpinBox()
        dspin.setRange(0.0, 10.0)
        dspin.setSingleStep(0.25)
        dspin.setValue(3.14)
        sp_form.addRow("Integer:", spin)
        sp_form.addRow("Double:", dspin)
        self._themed.extend((spin, dspin))
        left.addWidget(grp_sp)
        left.addStretch()
        cols.addLayout(left, 1)

        # -- Right column: combo boxes, text edit ---------------------------
        right = QVBoxLayout()
        right.setSpacing(12)

        grp_cb = QGroupBox("FluentComboBox")
        cb_form = QFormLayout(grp_cb)
        fruits = ["Apple", "Banana", "Cherry", "Date", "Elderberry",
                  "Fig", "Grape", "Honeydew", "Kiwi", "Lemon"]
        basic = FluentComboBox()
        basic.add_items(fruits)
        searchable = FluentComboBox(searchable=True)
        searchable.add_items(fruits)
        editable = FluentComboBox(editable=True, placeholder="Type or pick...")
        editable.add_items(fruits)
        cb_form.addRow("Basic:", basic)
        cb_form.addRow("Searchable:", searchable)
        cb_form.addRow("Editable:", editable)
        self._themed.extend((basic, searchable, editable))
        right.addWidget(grp_cb)

        grp_te = QGroupBox("FluentTextEdit")
        te_lay = QVBoxLayout(grp_te)
        te = FluentTextEdit()
        te.setPlaceholderText("Multi-line editable text. Right-click for the menu.")
        te.setFixedHeight(110)
        te_lay.addWidget(te)
        self._themed.append(te)
        right.addWidget(grp_te)
        right.addStretch()
        cols.addLayout(right, 1)

        root.addLayout(cols)

        self._status = QLabel("Right-click any text field for the Fluent context menu")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status)

        self._apply_app_theme()

    # -- Theme switching -----------------------------------------------------

    def _on_theme(self, checked: bool) -> None:
        self._dark = checked
        for w in self._themed:
            w.dark_mode = checked
        self._apply_app_theme()

    def _apply_app_theme(self) -> None:
        if self._dark:
            self.setStyleSheet("""
                QMainWindow { background: #1e1e1e; }
                QGroupBox { color: #e4e4e4; border: 1px solid #3d3d3d; border-radius: 8px; margin-top: 12px; padding-top: 16px; font-size: 13px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
                QCheckBox { color: #e4e4e4; font-size: 13px; }
                QLabel { color: #b0b0b0; font-size: 13px; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow { background: #f3f3f3; }
                QGroupBox { color: #1a1a1a; border: 1px solid #e0e0e0; border-radius: 8px; margin-top: 12px; padding-top: 16px; font-size: 13px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
                QCheckBox { color: #1a1a1a; font-size: 13px; }
                QLabel { color: #555; font-size: 13px; }
            """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())
