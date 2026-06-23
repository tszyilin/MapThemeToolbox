# -*- coding: utf-8 -*-
"""
Auto-Save Settings dialog.  QGIS 3.22+ and QGIS 4.x.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QCheckBox, QSpinBox, QPushButton,
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont

from .compat import WinNoHelpBtn, AlignLeft, AlignVCenter


class AutoSaveDialog(QDialog):

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Save Settings")
        self.setMinimumWidth(360)
        self.setWindowFlags(self.windowFlags() & ~WinNoHelpBtn)
        self._mgr = manager

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        self._chk = QCheckBox("Enable Auto-Save")
        font = QFont(); font.setBold(True)
        self._chk.setFont(font)
        self._chk.setChecked(manager.enabled)
        self._chk.toggled.connect(self._refresh_ui)
        layout.addWidget(self._chk)

        form = QFormLayout(); form.setContentsMargins(0, 0, 0, 0)
        self._spin = QSpinBox()
        self._spin.setRange(10, 3600); self._spin.setValue(manager.interval)
        self._spin.setSuffix("  seconds"); self._spin.setMinimumWidth(150)
        self._spin.setToolTip("Minimum 10 s, maximum 3600 s (1 hour)")
        form.addRow("Save every:", self._spin)
        layout.addLayout(form)

        preset_row = QHBoxLayout(); preset_row.addWidget(QLabel("Quick:"))
        for label, secs in [("30 s", 30), ("1 min", 60), ("5 min", 300), ("15 min", 900)]:
            btn = QPushButton(label); btn.setMaximumWidth(58)
            btn.clicked.connect(lambda _, s=secs: self._spin.setValue(s))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        self._chk_startup = QCheckBox("Show this dialog when QGIS starts")
        self._chk_startup.setChecked(manager.show_on_start)
        self._chk_startup.setToolTip(
            "When ticked, this dialog opens automatically every time QGIS loads.")
        layout.addWidget(self._chk_startup)

        self._lbl_status = QLabel()
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setMinimumHeight(56)
        self._lbl_status.setAlignment(AlignLeft | AlignVCenter)
        layout.addWidget(self._lbl_status)

        btn_row = QHBoxLayout()
        self._btn_apply = QPushButton("✔  Apply")
        self._btn_apply.setDefault(True)
        self._btn_apply.setToolTip("Apply the settings above")
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_now = QPushButton("💾  Save Now")
        self._btn_now.setToolTip("Save the QGIS project immediately")
        self._btn_now.clicked.connect(self._on_save_now)
        btn_close = QPushButton("Close"); btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_apply); btn_row.addWidget(self._btn_now)
        btn_row.addStretch(); btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_status)
        self._tick.start()
        self._refresh_ui(manager.enabled)

    def _refresh_ui(self, enabled):
        self._spin.setEnabled(enabled)
        self._update_status()

    def _update_status(self):
        mgr = self._mgr
        if mgr.enabled:
            remaining = mgr.timer_remaining()
            lines = []
            if remaining is not None:
                mins, secs = divmod(remaining, 60)
                countdown = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                lines.append(f"🟢  Active — next save in <b>{countdown}</b>")
            else:
                lines.append("🟢  Active")
            if mgr.last_save:
                lines.append(f"Last saved: &nbsp;<b>{mgr.last_save}</b>")
            self._lbl_status.setText("<br>".join(lines))
            self._lbl_status.setStyleSheet(
                "background:#d4edda; border:1px solid #c3e6cb; color:#155724; "
                "border-radius:5px; padding:8px; font-size:11px;")
        else:
            self._lbl_status.setText("🔴  Auto-Save is <b>disabled</b>.")
            self._lbl_status.setStyleSheet(
                "background:#f8d7da; border:1px solid #f5c6cb; color:#721c24; "
                "border-radius:5px; padding:8px; font-size:11px;")

    def _on_apply(self):
        self._mgr.apply(
            enabled=self._chk.isChecked(),
            interval=self._spin.value(),
            show_on_start=self._chk_startup.isChecked()
        )
        self._update_status()

    def _on_save_now(self):
        self._mgr.save_now(); self._update_status()

    def closeEvent(self, event):
        self._tick.stop(); super().closeEvent(event)
