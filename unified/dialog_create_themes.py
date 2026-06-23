# -*- coding: utf-8 -*-
"""
Create New Map Themes dialog.
Tab 1 — manually type theme names one by one.
Tab 2 — import from a CSV with a 'theme_name' column.

New themes are created from the CURRENT canvas visibility state.
The user is advised to set up visibility before clicking Create.
"""

import csv

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QAbstractItemView,
    QTabWidget, QWidget, QFileDialog, QLineEdit,
    QMessageBox, QFrame
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class CreateThemesDialog(QDialog):
    def __init__(self, existing_themes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Map Themes")
        self.setMinimumSize(480, 480)
        self._existing = set(existing_themes)
        self._names_to_create = []

        layout = QVBoxLayout()

        info = QLabel(
            "<b>Note:</b> Each new theme will be created with "
            "<b>all layers turned off</b>.<br>"
            "Use <i>Modify Theme Layers</i> to turn layers on after creation."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "background:#fff3cd; color:#856404; border:1px solid #ffc107; "
            "border-radius:4px; padding:6px;"
        )
        layout.addWidget(info)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_manual_tab(), "➕  Add One by One")
        self.tabs.addTab(self._build_csv_tab(),    "📂  Import from CSV")
        layout.addWidget(self.tabs)

        # Shared bottom buttons
        btns = QHBoxLayout()
        self.create_btn = QPushButton("✔  Create Themes")
        self.create_btn.setStyleSheet("font-weight:bold;")
        self.create_btn.clicked.connect(self._on_create)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.create_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self.setLayout(layout)

    # ── Tab 1: manual one-by-one ──────────────────────────────────────────────

    def _build_manual_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Type a theme name and press <b>Enter</b> or click <b>+ Add</b>:"))

        add_row = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("New theme name…")
        self.name_input.returnPressed.connect(self._add_manual)
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_manual)
        add_row.addWidget(self.name_input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        layout.addWidget(QLabel("Pending themes to create:"))
        self.manual_list = QListWidget()
        self.manual_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.manual_list)

        remove_btn = QPushButton("🗑  Remove Selected")
        remove_btn.clicked.connect(self._remove_manual)
        layout.addWidget(remove_btn, alignment=Qt.AlignLeft)

        return w

    def _add_manual(self):
        name = self.name_input.text().strip()
        if not name:
            return
        # Check duplicates in list
        existing_in_list = [
            self.manual_list.item(i).text()
            for i in range(self.manual_list.count())
        ]
        if name in existing_in_list:
            QMessageBox.warning(self, "Duplicate", f"'{name}' is already in the list.")
            return
        if name in self._existing:
            reply = QMessageBox.question(
                self, "Already Exists",
                f"A theme named '{name}' already exists in the project.\n"
                "Adding it will overwrite the existing theme. Continue?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        item = QListWidgetItem(name)
        if name in self._existing:
            item.setForeground(QColor("#856404"))
            item.setToolTip("Will overwrite existing theme")
        self.manual_list.addItem(item)
        self.name_input.clear()
        self.name_input.setFocus()

    def _remove_manual(self):
        for item in self.manual_list.selectedItems():
            self.manual_list.takeItem(self.manual_list.row(item))

    # ── Tab 2: CSV import ─────────────────────────────────────────────────────

    def _build_csv_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel(
            "Upload a CSV with a <b>theme_name</b> column.<br>"
            "Each row becomes a new theme with <b>all layers turned off</b>."
        ))

        hint = QFrame()
        hint.setStyleSheet(
            "background:#f8f9fa; border:1px solid #dee2e6; border-radius:4px;"
        )
        hl = QVBoxLayout(hint)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.addWidget(QLabel("<b>Expected CSV format:</b>"))
        hl.addWidget(QLabel("<code>theme_name<br>Sunny Day<br>Night Scene<br>Flood Scenario</code>"))
        layout.addWidget(hint)

        browse_row = QHBoxLayout()
        browse_btn = QPushButton("📂  Browse CSV…")
        browse_btn.clicked.connect(self._browse_csv)
        self.csv_status = QLabel("No file selected.")
        self.csv_status.setStyleSheet("color:#666;")
        browse_row.addWidget(browse_btn)
        browse_row.addWidget(self.csv_status, 1)
        layout.addLayout(browse_row)

        layout.addWidget(QLabel("<b>Preview:</b>"))
        self.csv_list = QListWidget()
        self.csv_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.csv_list)

        self._csv_names = []
        return w

    def _browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV files (*.csv *.txt)"
        )
        if not path:
            return

        self._csv_names = []
        self.csv_list.clear()

        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fields = [c.strip().lower() for c in (reader.fieldnames or [])]

                if "theme_name" not in fields:
                    QMessageBox.critical(self, "CSV Error",
                        "CSV must have a column named 'theme_name'.")
                    return

                for row in reader:
                    name = row.get("theme_name", "").strip()
                    if name:
                        self._csv_names.append(name)

        except Exception as e:
            QMessageBox.critical(self, "Read Error", f"Could not read CSV:\n{e}")
            return

        for name in self._csv_names:
            item = QListWidgetItem(name)
            if name in self._existing:
                item.setForeground(QColor("#856404"))
                item.setBackground(QColor("#fff3cd"))
                item.setToolTip("Will overwrite existing theme")
            self.csv_list.addItem(item)

        overwrites = sum(1 for n in self._csv_names if n in self._existing)
        self.csv_status.setText(
            f"{path.split('/')[-1]}  —  {len(self._csv_names)} theme(s)"
            + (f", {overwrites} will overwrite existing" if overwrites else "")
        )

    # ── Create ────────────────────────────────────────────────────────────────

    def _on_create(self):
        active = self.tabs.currentIndex()

        if active == 0:
            names = [
                self.manual_list.item(i).text()
                for i in range(self.manual_list.count())
            ]
        else:
            names = list(self._csv_names)

        if not names:
            QMessageBox.information(self, "Nothing to Create",
                "Please add at least one theme name.")
            return

        overwrites = [n for n in names if n in self._existing]
        msg = f"Create {len(names)} new theme(s) with all layers turned off?"
        if overwrites:
            msg += f"\n\n⚠ {len(overwrites)} will overwrite existing theme(s):\n"
            msg += "\n".join(f"  - {n}" for n in overwrites)

        reply = QMessageBox.question(
            self, "Confirm Create", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._names_to_create = names
        self.accept()

    def names_to_create(self):
        return self._names_to_create
