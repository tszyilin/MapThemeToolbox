# -*- coding: utf-8 -*-
"""
Theme Presenter — apply any map theme with a single click.

Opens a persistent dialog listing all project themes.
Clicking a theme applies it instantly to the canvas.
A search box filters the list for projects with many themes.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QLineEdit,
    QPushButton, QAbstractItemView
)
from qgis.PyQt.QtCore import Qt, QSortFilterProxyModel, QStringListModel
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import QgsProject


class ApplyThemeDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface   = iface
        self.setWindowTitle("Theme Presenter")
        self.setMinimumSize(300, 450)
        # Stay on top but non-blocking so canvas is still interactive
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._current_theme = None
        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        hdr = QLabel("Click a theme to apply it instantly.")
        hdr.setStyleSheet("color:#555; font-size:10px; padding-bottom:4px;")
        layout.addWidget(hdr)

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Filter themes…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Theme list
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.itemClicked.connect(self._on_theme_clicked)
        self._list.setAlternatingRowColors(True)
        self._list.setSpacing(2)
        layout.addWidget(self._list)

        # Current theme label
        self._status = QLabel("No theme applied yet.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "background:#d4edda; color:#155724; border:1px solid #c3e6cb; "
            "border-radius:4px; padding:6px; font-size:10px;"
        )
        layout.addWidget(self._status)

        # Buttons row
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setFixedWidth(90)
        refresh_btn.setToolTip("Reload theme list from project")
        refresh_btn.clicked.connect(self._populate)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self):
        self._list.clear()
        tc     = QgsProject.instance().mapThemeCollection()
        themes = sorted(tc.mapThemes(), key=str.casefold)

        if not themes:
            item = QListWidgetItem("  (no themes in project)")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            item.setForeground(QColor("#999"))
            self._list.addItem(item)
            return

        bold = QFont()
        bold.setBold(True)

        for name in themes:
            item = QListWidgetItem(f"  {name}")
            item.setData(Qt.UserRole, name)
            item.setSizeHint(item.sizeHint().__class__(
                item.sizeHint().width(), 28))
            if name == self._current_theme:
                item.setFont(bold)
                item.setForeground(QColor("#155724"))
                item.setBackground(QColor("#d4edda"))
            self._list.addItem(item)

        self._filter(self._search.text())

    def _filter(self, text):
        text = text.strip().casefold()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = (item.data(Qt.UserRole) or "").casefold()
            item.setHidden(bool(text) and text not in name)

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _on_theme_clicked(self, item):
        name = item.data(Qt.UserRole)
        if not name:
            return

        tc    = QgsProject.instance().mapThemeCollection()
        root  = QgsProject.instance().layerTreeRoot()
        model = self.iface.layerTreeView().layerTreeModel()

        tc.applyTheme(name, root, model)
        self.iface.mapCanvas().refresh()

        self._current_theme = name
        self._status.setText(f"✅  Applied: <b>{name}</b>")
        self._populate()   # refresh to highlight active theme
