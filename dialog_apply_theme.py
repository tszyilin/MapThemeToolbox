# -*- coding: utf-8 -*-
"""
Theme Presenter — dockable panel for applying map themes with one click.

Implemented as a QDockWidget so it can be docked, floated, and tabbed
alongside other panels (Profile Tool, TUFLOW Viewer, etc.).

Grouping: themes whose names contain '/' are nested under a collapsible
group header.  E.g. "Phase1/Overview" appears as:
    ▶ Phase1
        Overview

Operations available:
  • Click theme  — apply instantly to canvas
  • Add          — create new theme from current canvas state
  • Rename       — rename the selected theme
  • Replace      — overwrite selected theme with current canvas state
  • Delete       — delete the selected theme
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QTreeWidget, QTreeWidgetItem,
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
        hdr = QLabel("Click a theme to apply it.  Use <b>Group/Theme</b> names to create groups.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet("color:#555; font-size:10px; padding-bottom:2px;")
        layout.addWidget(hdr)

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Filter themes…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Theme tree
        self._list = QTreeWidget()
        self._list.setHeaderHidden(True)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setAlternatingRowColors(True)
        self._list.setIndentation(16)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        # ── Action buttons (2×2 grid) ─────────────────────────────────────────
        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)

        self._btn_add     = QPushButton("➕  Add")
        self._btn_rename  = QPushButton("✏️  Rename")
        self._btn_replace = QPushButton("🔄  Replace")
        self._btn_delete  = QPushButton("🗑  Delete")

        self._btn_add.setToolTip("Create a new theme from the current canvas state\n"
                                 "Tip: name it 'Group/Theme' to place it in a group")
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
        """Return the full theme name of the selected leaf item, or None."""
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.UserRole)   # None for group headers

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
            placeholder = QTreeWidgetItem(self._list, ["  (no themes in project)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsEnabled)
            placeholder.setForeground(0, QColor("#999"))
            return

        bold = QFont()
        bold.setBold(True)

        group_bold = QFont()
        group_bold.setBold(True)
        group_bold.setPointSize(group_bold.pointSize())   # keep default size

        groups = {}   # group_name -> QTreeWidgetItem

        for name in themes:
            # ── parse optional group prefix ───────────────────────────────────
            if '/' in name:
                slash       = name.index('/')
                group_name  = name[:slash].strip()
                leaf_label  = name[slash + 1:].strip()
            else:
                group_name  = None
                leaf_label  = name

            # ── ensure group header exists ────────────────────────────────────
            if group_name is not None:
                if group_name not in groups:
                    grp = QTreeWidgetItem(self._list, [f"  📁  {group_name}"])
                    grp.setFont(0, group_bold)
                    grp.setForeground(0, QColor("#1a5276"))
                    grp.setExpanded(True)
                    grp.setFlags(grp.flags() & ~Qt.ItemIsSelectable)
                    groups[group_name] = grp
                parent = groups[group_name]
            else:
                parent = self._list.invisibleRootItem()

            # ── leaf item ─────────────────────────────────────────────────────
            item = QTreeWidgetItem(parent, [f"  {leaf_label}"])
            item.setData(0, Qt.UserRole, name)   # full name stored here

            if name == self._current_theme:
                item.setFont(0, bold)
                item.setForeground(0, QColor("#155724"))
                item.setBackground(0, QColor("#d4edda"))

            if name == selected:
                self._list.setCurrentItem(item)

        self._filter(self._search.text())

    def _filter(self, text):
        text = text.strip().casefold()
        root = self._list.invisibleRootItem()

        for i in range(root.childCount()):
            top = root.child(i)
            full_name = top.data(0, Qt.UserRole)

            if full_name is not None:
                # Root-level leaf (no group)
                top.setHidden(bool(text) and text not in full_name.casefold())
            else:
                # Group header — hide if ALL children are hidden
                any_visible = False
                for j in range(top.childCount()):
                    leaf      = top.child(j)
                    leaf_name = (leaf.data(0, Qt.UserRole) or "").casefold()
                    hidden    = bool(text) and text not in leaf_name
                    leaf.setHidden(hidden)
                    if not hidden:
                        any_visible = True
                top.setHidden(not any_visible)

    # ── Apply (click) ─────────────────────────────────────────────────────────

    def _on_item_clicked(self, item, column):
        name = item.data(0, Qt.UserRole)
        if not name:
            return   # group header clicked — ignore
        self._tc().applyTheme(name, self._root(), self._model())
        self.iface.mapCanvas().refresh()
        self._current_theme = name
        self._status.setText(f"✅  Applied: <b>{name}</b>")
        self._populate()

    # ── Add ───────────────────────────────────────────────────────────────────

    def _on_add(self):
        tc   = self._tc()
        root = self._root()

        name, ok = QInputDialog.getText(
            self, "Add Theme",
            "New theme name:\n"
            "• Type  Group/ThemeName  to place it in a group\n"
            "• Saved from the current canvas state"
        )
        name = name.strip()
        if not ok or not name:
            return
        if name in tc.mapThemes():
            QMessageBox.warning(self, "Already Exists",
                                f"A theme named '{name}' already exists.")
            return

        state = tc.createThemeFromCurrentState(root, self._model())
        tc.insert(name, state)
        self._status.setText(f"➕  Created: <b>{name}</b>  (from current canvas)")
        self._populate()

    # ── Rename ────────────────────────────────────────────────────────────────

    def _on_rename(self):
        old = self._require_selection()
        if not old:
            return
        tc = self._tc()
        new, ok = QInputDialog.getText(self, "Rename Theme",
                                       "New name:\n"
                                       "• Use  Group/ThemeName  to move into a group",
                                       text=old)
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
