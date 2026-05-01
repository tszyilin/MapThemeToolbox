# -*- coding: utf-8 -*-
"""
Theme Presenter — dockable panel for applying map themes with one click.

Implemented as a QDockWidget so it can be docked, floated, and tabbed
alongside other panels (Profile Tool, TUFLOW Viewer, etc.).

Operations available:
  • Click theme  — apply instantly to canvas
  • Add          — create new empty theme (all layers off)
  • Rename       — rename the selected theme
  • Replace      — overwrite selected theme with current canvas state
  • Delete       — delete the selected theme
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QAbstractItemView,
    QInputDialog, QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import QgsProject


class ThemePresenterDock(QDockWidget):

    def __init__(self, iface, parent=None):
        super().__init__("Theme Presenter", parent)
        self.iface          = iface
        self._current_theme = None

        self.setAllowedAreas(
            Qt.LeftDockWidgetArea |
            Qt.RightDockWidgetArea |
            Qt.BottomDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable |
            QDockWidget.DockWidgetClosable
        )

        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Hint
        hdr = QLabel("Click a theme to apply it instantly.")
        hdr.setStyleSheet("color:#555; font-size:10px; padding-bottom:2px;")
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

        # ── Action buttons (2×2 grid) ─────────────────────────────────────────
        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)

        self._btn_add     = QPushButton("➕  Add")
        self._btn_rename  = QPushButton("✏️  Rename")
        self._btn_replace = QPushButton("🔄  Replace")
        self._btn_delete  = QPushButton("🗑  Delete")

        self._btn_add.setToolTip("Create a new empty theme (all layers off)")
        self._btn_rename.setToolTip("Rename the selected theme")
        self._btn_replace.setToolTip("Overwrite selected theme with current canvas state")
        self._btn_delete.setToolTip("Delete the selected theme")

        self._btn_delete.setStyleSheet("color:#c0392b;")

        self._btn_add.clicked.connect(self._on_add)
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_replace.clicked.connect(self._on_replace)
        self._btn_delete.clicked.connect(self._on_delete)

        btn_grid.addWidget(self._btn_add,     0, 0)
        btn_grid.addWidget(self._btn_rename,  0, 1)
        btn_grid.addWidget(self._btn_replace, 1, 0)
        btn_grid.addWidget(self._btn_delete,  1, 1)
        layout.addLayout(btn_grid)

        # Active theme banner
        self._status = QLabel("No theme applied yet.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "background:#d4edda; color:#155724; border:1px solid #c3e6cb; "
            "border-radius:4px; padding:5px; font-size:10px;"
        )
        layout.addWidget(self._status)

        # Refresh button
        refresh_btn = QPushButton("↻  Refresh List")
        refresh_btn.setToolTip("Reload theme list from project")
        refresh_btn.clicked.connect(self._populate)
        layout.addWidget(refresh_btn)

        self.setWidget(container)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tc(self):
        return QgsProject.instance().mapThemeCollection()

    def _root(self):
        return QgsProject.instance().layerTreeRoot()

    def _model(self):
        return self.iface.layerTreeView().layerTreeModel()

    def _selected_theme(self):
        """Return the name of the currently selected list item, or None."""
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _require_selection(self):
        name = self._selected_theme()
        if not name:
            QMessageBox.warning(self, "No Theme Selected",
                                "Please click a theme in the list first.")
        return name

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self):
        selected = self._selected_theme()   # remember selection across refresh
        self._list.clear()
        tc     = self._tc()
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
            if name == self._current_theme:
                item.setFont(bold)
                item.setForeground(QColor("#155724"))
                item.setBackground(QColor("#d4edda"))
            self._list.addItem(item)
            if name == selected:
                self._list.setCurrentItem(item)

        self._filter(self._search.text())

    def _filter(self, text):
        text = text.strip().casefold()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = (item.data(Qt.UserRole) or "").casefold()
            item.setHidden(bool(text) and text not in name)

    # ── Apply (click) ─────────────────────────────────────────────────────────

    def _on_theme_clicked(self, item):
        name = item.data(Qt.UserRole)
        if not name:
            return
        self._tc().applyTheme(name, self._root(), self._model())
        self.iface.mapCanvas().refresh()
        self._current_theme = name
        self._status.setText(f"✅  Applied: <b>{name}</b>")
        self._populate()

    # ── Add ───────────────────────────────────────────────────────────────────

    def _on_add(self):
        tc   = self._tc()
        root = self._root()

        # If no theme is currently active the canvas shows a custom/unsaved
        # state — capture it directly.  If a theme is active, create empty.
        use_current = self._current_theme is None

        if use_current:
            hint = "New theme name:\n(will be created from the current canvas state)"
        else:
            hint = "New theme name:\n(will be created with all layers turned off)"

        name, ok = QInputDialog.getText(self, "Add Theme", hint)
        name = name.strip()
        if not ok or not name:
            return
        if name in tc.mapThemes():
            QMessageBox.warning(self, "Already Exists",
                                f"A theme named '{name}' already exists.")
            return

        if use_current:
            # Capture whatever is currently shown on the canvas
            state = tc.createThemeFromCurrentState(root, self._model())
        else:
            # Create empty — turn all layers off, capture, then restore
            all_nodes = root.findLayers()
            saved     = {n.layerId(): n.itemVisibilityChecked() for n in all_nodes}
            for n in all_nodes:
                n.setItemVisibilityChecked(False)
            state = tc.createThemeFromCurrentState(root, self._model())
            for n in all_nodes:
                n.setItemVisibilityChecked(saved.get(n.layerId(), True))

        tc.insert(name, state)
        src = "current canvas" if use_current else "empty"
        self._status.setText(f"➕  Created: <b>{name}</b>  ({src})")
        self._populate()

    # ── Rename ────────────────────────────────────────────────────────────────

    def _on_rename(self):
        old = self._require_selection()
        if not old:
            return
        tc = self._tc()
        new, ok = QInputDialog.getText(self, "Rename Theme",
                                       "New name:", text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        if new in tc.mapThemes():
            QMessageBox.warning(self, "Already Exists",
                                f"A theme named '{new}' already exists.")
            return
        tc.insert(new, tc.mapThemeState(old))
        tc.removeMapTheme(old)
        if self._current_theme == old:
            self._current_theme = new
            self._status.setText(f"✅  Applied: <b>{new}</b>")
        self._populate()

    # ── Replace ───────────────────────────────────────────────────────────────

    def _on_replace(self):
        name = self._require_selection()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Replace Theme",
            f"Overwrite <b>{name}</b> with the current canvas state?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        tc    = self._tc()
        state = tc.createThemeFromCurrentState(self._root(), self._model())
        tc.update(name, state)
        self._status.setText(f"🔄  Replaced: <b>{name}</b>")
        self._populate()

    # ── Delete ────────────────────────────────────────────────────────────────

    def _on_delete(self):
        name = self._require_selection()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Theme",
            f"Delete theme <b>{name}</b>? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._tc().removeMapTheme(name)
        if self._current_theme == name:
            self._current_theme = None
            self._status.setText("No theme applied yet.")
        self._populate()
