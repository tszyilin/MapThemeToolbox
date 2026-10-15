# -*- coding: utf-8 -*-
"""
Missing-layer summary shown after Refresh All Layer Sources.  QGIS 3.22+ and QGIS 4.x.
"""

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QApplication,
)

from .compat import (
    Interactive, Stretch, NoEditTriggers, SelectRows, ExtendedSelection, ElideMiddle,
)


def missing_reason(layer, exc=None):
    """Best-effort, human-readable reason a layer could not be reconnected."""
    if exc is not None:
        return f"Error: {exc}"
    file_part = layer.source().split('|')[0]
    if (os.sep in file_part or '/' in file_part or
            (len(file_part) > 1 and file_part[1] == ':')):
        if not os.path.exists(file_part):
            folder = os.path.dirname(file_part)
            if folder and not os.path.isdir(folder):
                return "Folder not reachable (server offline or path moved)"
            return "File not found"
    try:
        msg = layer.error().summary().strip()
    except Exception:
        msg = ""
    return msg or "Data source could not be opened"


class RefreshSummaryDialog(QDialog):
    COL_NAME   = 0
    COL_REASON = 1
    COL_SOURCE = 2

    def __init__(self, missing, reloaded, reconnected, skipped=0, parent=None):
        """missing: list of (layer_name, reason, source)."""
        super().__init__(parent)
        self.setWindowTitle("Refresh Layer Sources — Missing Layers")
        self.resize(900, 420)
        self.open_repair = False
        self._missing = missing

        layout = QVBoxLayout(self)

        parts = [f"Reloaded {reloaded} layer(s)"]
        if reconnected:
            parts.append(f"reconnected {reconnected}")
        if skipped:
            parts.append(f"{skipped} skipped (canceled)")
        head = QLabel(
            f"<b>{len(missing)} layer(s) are still unavailable.</b><br>"
            + ", ".join(parts) + "."
        )
        layout.addWidget(head)

        table = QTableWidget(len(missing), 3)
        table.setHorizontalHeaderLabels(["Layer Name", "Reason", "Source"])
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_NAME,   Interactive)
        hdr.setSectionResizeMode(self.COL_REASON, Interactive)
        hdr.setSectionResizeMode(self.COL_SOURCE, Stretch)
        table.setEditTriggers(NoEditTriggers)
        table.setSelectionBehavior(SelectRows)
        table.setSelectionMode(ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)              # wrapping overrides the elide mode
        table.setTextElideMode(ElideMiddle)   # keep the file name visible in long paths
        for row, (name, reason, source) in enumerate(missing):
            for col, text in ((self.COL_NAME, name), (self.COL_REASON, reason),
                              (self.COL_SOURCE, source)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(row, col, item)
        # Fit name/reason to their text but cap them, so Source keeps the rest
        table.resizeColumnsToContents()
        # (+24 px: widths are measured before the dialog is styled/shown)
        table.setColumnWidth(self.COL_NAME,   min(table.columnWidth(self.COL_NAME) + 24,   300))
        table.setColumnWidth(self.COL_REASON, min(table.columnWidth(self.COL_REASON) + 24, 340))
        layout.addWidget(table)

        hint = QLabel(
            "If the server was just offline, wait a moment and click Refresh again.  "
            "If the files have moved, use Repair Unavailable Layers to re-link them."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btn_copy = QPushButton("Copy list")
        btn_copy.setToolTip("Copy the table to the clipboard (paste into Excel or an email)")
        btn_copy.clicked.connect(self._copy)
        btns.addWidget(btn_copy)
        btns.addStretch()
        btn_repair = QPushButton("Open Repair Unavailable Layers…")
        btn_repair.clicked.connect(self._repair)
        btns.addWidget(btn_repair)
        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _copy(self):
        lines = ["Layer Name\tReason\tSource"]
        lines += ["\t".join(row) for row in self._missing]
        QApplication.clipboard().setText("\n".join(lines))

    def _repair(self):
        self.open_repair = True
        self.accept()
