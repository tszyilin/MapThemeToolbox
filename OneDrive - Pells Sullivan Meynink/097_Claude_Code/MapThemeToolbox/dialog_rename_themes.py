# -*- coding: utf-8 -*-
"""Rename Map Themes — manual editable table OR CSV import (two tabs)."""

import csv
import io

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QAbstractItemView, QTabWidget, QWidget,
    QFileDialog, QFrame
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class RenameThemesDialog(QDialog):
    def __init__(self, themes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rename Map Themes")
        self.setMinimumSize(560, 440)
        self._themes = sorted(themes)
        self._renames = {}

        layout = QVBoxLayout()

        # ── Tab widget ────────────────────────────────────────────────────────
        self.tabs = QTabWidget()

        # Tab 1 — Manual
        self.tabs.addTab(self._build_manual_tab(), "✏  Manual Edit")

        # Tab 2 — CSV import
        self.tabs.addTab(self._build_csv_tab(), "📂  Import from CSV")

        layout.addWidget(self.tabs)

        # ── Bottom buttons (shared) ───────────────────────────────────────────
        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Renames")
        self.apply_btn.setStyleSheet("font-weight:bold;")
        self.apply_btn.clicked.connect(self._on_apply)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.apply_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self.setLayout(layout)

    # ── Tab 1: manual ─────────────────────────────────────────────────────────

    def _build_manual_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel(
            "Edit the <b>New Name</b> column, then click <b>Apply Renames</b>.<br>"
            "Leave a row unchanged to keep its current name."
        ))

        self.table = QTableWidget(len(self._themes), 2)
        self.table.setHorizontalHeaderLabels(["Current Name", "New Name"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.SelectedClicked |
            QAbstractItemView.EditKeyPressed
        )
        for row, name in enumerate(self._themes):
            cur = QTableWidgetItem(name)
            cur.setFlags(cur.flags() & ~Qt.ItemIsEditable)
            cur.setBackground(QColor("#f0f0f0"))
            self.table.setItem(row, 0, cur)
            self.table.setItem(row, 1, QTableWidgetItem(name))
        layout.addWidget(self.table)

        reset_btn = QPushButton("↺ Reset All")
        reset_btn.clicked.connect(self._on_reset)
        layout.addWidget(reset_btn, alignment=Qt.AlignLeft)

        return w

    # ── Tab 2: CSV import ─────────────────────────────────────────────────────

    def _build_csv_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel(
            "Upload a CSV with columns <b>current_name</b> and <b>new_name</b>.<br>"
            "Rows whose <i>current_name</i> doesn't match a project theme are skipped."
        ))

        # Format hint box
        hint = QFrame()
        hint.setStyleSheet("background:#f8f9fa; border:1px solid #dee2e6; border-radius:4px; padding:4px;")
        hl = QVBoxLayout(hint)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.addWidget(QLabel("<b>Expected CSV format:</b>"))
        hl.addWidget(QLabel('<code>current_name,new_name<br>'
                            '007_sunny_day,Sunny Day<br>'
                            '008_night_CL,Night Scene</code>'))
        layout.addWidget(hint)

        # Browse button + status
        browse_row = QHBoxLayout()
        self.browse_btn = QPushButton("📂  Browse CSV…")
        self.browse_btn.clicked.connect(self._browse_csv)
        self.csv_label = QLabel("No file selected.")
        self.csv_label.setStyleSheet("color:#666;")
        browse_row.addWidget(self.browse_btn)
        browse_row.addWidget(self.csv_label, 1)
        layout.addLayout(browse_row)

        # Preview table (read-only)
        layout.addWidget(QLabel("<b>Preview (matched rows only):</b>"))
        self.csv_table = QTableWidget(0, 3)
        self.csv_table.setHorizontalHeaderLabels(["Current Name", "New Name", "Status"])
        self.csv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.csv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.csv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.csv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.csv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.csv_table)

        self._csv_renames = {}   # {old: new} parsed from CSV

        return w

    def _browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV files (*.csv *.txt)"
        )
        if not path:
            return

        self._csv_renames = {}
        self.csv_table.setRowCount(0)

        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fields = [c.strip().lower() for c in (reader.fieldnames or [])]

                if "current_name" not in fields or "new_name" not in fields:
                    QMessageBox.critical(self, "CSV Error",
                        "CSV must have columns named 'current_name' and 'new_name'.")
                    return

                theme_set = set(self._themes)
                rows = []
                for row in reader:
                    old = row.get("current_name", "").strip()
                    new = row.get("new_name", "").strip()
                    if not old:
                        continue
                    matched = old in theme_set
                    rows.append((old, new, matched))

        except Exception as e:
            QMessageBox.critical(self, "Read Error", f"Could not read CSV:\n{e}")
            return

        # Populate preview table
        self.csv_table.setRowCount(len(rows))
        for r, (old, new, matched) in enumerate(rows):
            self.csv_table.setItem(r, 0, QTableWidgetItem(old))
            self.csv_table.setItem(r, 1, QTableWidgetItem(new))
            status_item = QTableWidgetItem("✔ Match" if matched else "✘ Not found")
            status_item.setForeground(QColor("#155724" if matched else "#721c24"))
            status_item.setBackground(QColor("#d4edda" if matched else "#f8d7da"))
            self.csv_table.setItem(r, 2, status_item)
            if matched and new and new != old:
                self._csv_renames[old] = new

        matched_count = sum(1 for _, _, m in rows if m)
        self.csv_label.setText(
            f"{path.split('/')[-1]}  —  {len(rows)} row(s), {matched_count} matched"
        )
        self.csv_label.setStyleSheet("color:#155724;" if matched_count else "color:#721c24;")

    # ── Apply (works for both tabs) ───────────────────────────────────────────

    def _on_reset(self):
        for row, name in enumerate(self._themes):
            self.table.item(row, 1).setText(name)

    def _on_apply(self):
        active = self.tabs.currentIndex()

        if active == 0:
            # Manual tab
            renames, new_names = {}, []
            for row, old in enumerate(self._themes):
                new = self.table.item(row, 1).text().strip()
                if not new:
                    QMessageBox.warning(self, "Empty Name", f"Row {row+1}: name cannot be empty.")
                    return
                new_names.append(new)
                if new != old:
                    renames[old] = new
            if len(new_names) != len(set(new_names)):
                QMessageBox.warning(self, "Duplicate Names",
                                    "Two or more themes would share the same name.")
                return
            if not renames:
                QMessageBox.information(self, "No Changes", "No names were changed.")
                return
            self._renames = renames

        else:
            # CSV tab
            if not self._csv_renames:
                QMessageBox.information(self, "Nothing to Apply",
                    "No matched renames found. Please load a valid CSV first.")
                return
            self._renames = self._csv_renames

        self.accept()

    def renames(self):
        return self._renames
