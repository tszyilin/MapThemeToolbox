# -*- coding: utf-8 -*-
"""
Theme Presenter — dockable panel for applying map themes with one click.

Grouping and order are stored in QgsProject custom variables:
  mtt_theme_groups  →  {theme_name: group_name}
  mtt_theme_order   →  [theme_name, ...]  (display order)

The actual QGIS theme names are NEVER changed.

Drag-and-drop:
  • Drag within a group  — reorder
  • Drag to a different group header  — move to that group
  • Drag to blank space / root level  — ungroup

Buttons:
  Add | Rename | Replace | Delete | Create Group | Ungroup
"""

import json

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QGridLayout,
    QLabel, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QAbstractItemView,
    QInputDialog, QMessageBox,
    QDialog, QDialogButtonBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import QgsProject

GROUP_VAR = "mtt_theme_groups"   # {theme_name: group_name}
ORDER_VAR = "mtt_theme_order"    # [theme_name, ...]

# Extra data role to store the group name on group-header items
GROUP_NAME_ROLE = Qt.UserRole + 1


# ── Drag-and-drop tree ────────────────────────────────────────────────────────

class ThemeTree(QTreeWidget):
    """
    QTreeWidget that supports drag-and-drop for reordering and regrouping.
    After every drop it calls dock._rebuild_from_tree() to persist the change.
    """

    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self._dock = dock
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def startDrag(self, supported_actions):
        """Block dragging of group-header items (they have no UserRole name)."""
        item = self.currentItem()
        if item is None or item.data(0, Qt.UserRole) is None:
            return
        super().startDrag(supported_actions)

    def dropEvent(self, event):
        """
        Block dropping a theme ONTO another theme leaf (would nest it).
        Otherwise let Qt move the item, then rebuild metadata from the new tree.
        """
        target    = self.itemAt(event.pos())
        indicator = self.dropIndicatorPosition()

        # Reject: dropping a theme directly on top of another theme
        if (target is not None
                and target.data(0, Qt.UserRole) is not None   # target is a leaf
                and indicator == QAbstractItemView.OnItem):
            event.ignore()
            return

        super().dropEvent(event)
        self._dock._rebuild_from_tree()


# ── Create Group dialog ───────────────────────────────────────────────────────

class CreateGroupDialog(QDialog):
    def __init__(self, themes, groups_map, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create / Move into Group")
        self.setMinimumWidth(380)
        self.setMinimumHeight(440)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        layout.addWidget(QLabel("<b>Group name:</b>"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g.  FDF")
        layout.addWidget(self._name_edit)

        layout.addWidget(QLabel("<b>Themes to add to this group:</b>"))
        hint = QLabel("Hold Ctrl to select multiple.  Current group shown in brackets.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for theme in sorted(themes, key=str.casefold):
            grp   = groups_map.get(theme)
            label = f"{theme}  [{grp}]" if grp else theme
            item  = QListWidgetItem(label)
            item.setData(Qt.UserRole, theme)
            if grp:
                item.setForeground(QColor("#1a5276"))
            self._list.addItem(item)
        layout.addWidget(self._list)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def group_name(self):
        return self._name_edit.text().strip()

    def selected_themes(self):
        return [item.data(Qt.UserRole) for item in self._list.selectedItems()]


# ── Theme Presenter dock ──────────────────────────────────────────────────────

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

        hdr = QLabel("Click to apply · Drag to reorder or move between groups.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet("color:#555; font-size:10px; padding-bottom:2px;")
        layout.addWidget(hdr)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Filter themes…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Drag-enabled tree
        self._list = ThemeTree(self)
        self._list.setHeaderHidden(True)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setAlternatingRowColors(True)
        self._list.setIndentation(16)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        # ── 2×2 action buttons ────────────────────────────────────────────────
        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)

        self._btn_add     = QPushButton("➕  Add")
        self._btn_rename  = QPushButton("✏️  Rename")
        self._btn_replace = QPushButton("🔄  Replace")
        self._btn_delete  = QPushButton("🗑  Delete")

        self._btn_add.setToolTip("Create a new theme from the current canvas state")
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

        # ── Group buttons ─────────────────────────────────────────────────────
        grp_grid = QGridLayout()
        grp_grid.setSpacing(4)

        self._btn_group   = QPushButton("📁  Create Group")
        self._btn_ungroup = QPushButton("↩  Ungroup")

        self._btn_group.setToolTip(
            "Assign selected themes to a named group.\n"
            "You can also drag themes between groups.")
        self._btn_ungroup.setToolTip(
            "Remove the selected theme from its group.\n"
            "You can also drag it out of the group folder.")
        self._btn_ungroup.setEnabled(False)

        self._btn_group.clicked.connect(self._on_create_group)
        self._btn_ungroup.clicked.connect(self._on_ungroup)

        grp_grid.addWidget(self._btn_group,   0, 0)
        grp_grid.addWidget(self._btn_ungroup, 0, 1)
        layout.addLayout(grp_grid)

        # Status banner
        self._status = QLabel("No theme applied yet.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "background:#d4edda; color:#155724; border:1px solid #c3e6cb; "
            "border-radius:4px; padding:5px; font-size:10px;"
        )
        layout.addWidget(self._status)

        # Refresh
        refresh_btn = QPushButton("↻  Refresh List")
        refresh_btn.setToolTip("Reload theme list from project")
        refresh_btn.clicked.connect(self._populate)
        layout.addWidget(refresh_btn)

        self.setWidget(container)

    # ── Project-variable persistence ──────────────────────────────────────────

    def _load_groups(self):
        raw = QgsProject.instance().customVariables().get(GROUP_VAR, "")
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def _save_groups(self, mapping):
        v = QgsProject.instance().customVariables()
        v[GROUP_VAR] = json.dumps(mapping, ensure_ascii=False)
        QgsProject.instance().setCustomVariables(v)

    def _load_order(self):
        raw = QgsProject.instance().customVariables().get(ORDER_VAR, "")
        try:
            return json.loads(raw) if raw else []
        except Exception:
            return []

    def _save_order(self, order):
        v = QgsProject.instance().customVariables()
        v[ORDER_VAR] = json.dumps(order, ensure_ascii=False)
        QgsProject.instance().setCustomVariables(v)

    def _clean_groups(self, mapping, existing):
        stale = [t for t in mapping if t not in existing]
        for t in stale:
            del mapping[t]
        return bool(stale)

    # ── Rebuild metadata from current tree (called after drag-drop) ───────────

    def _rebuild_from_tree(self):
        """
        Walk the tree as Qt left it after a drop, extract the new
        group assignments and display order, persist them, then repopulate.
        """
        groups_map = {}
        order      = []

        root = self._list.invisibleRootItem()
        for i in range(root.childCount()):
            item       = root.child(i)
            theme_name = item.data(0, Qt.UserRole)

            if theme_name is not None:
                # Root-level leaf = ungrouped
                order.append(theme_name)
            else:
                # Group header
                group_name = item.data(0, GROUP_NAME_ROLE)
                for j in range(item.childCount()):
                    leaf      = item.child(j)
                    leaf_name = leaf.data(0, Qt.UserRole)
                    if leaf_name:
                        groups_map[leaf_name] = group_name
                        order.append(leaf_name)

        self._save_groups(groups_map)
        self._save_order(order)
        self._populate()   # redraw cleanly

    # ── Core helpers ──────────────────────────────────────────────────────────

    def _tc(self):
        return QgsProject.instance().mapThemeCollection()

    def _root(self):
        return QgsProject.instance().layerTreeRoot()

    def _model(self):
        return self.iface.layerTreeView().layerTreeModel()

    def _selected_theme(self):
        item = self._list.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def _require_selection(self):
        name = self._selected_theme()
        if not name:
            QMessageBox.warning(self, "No Theme Selected",
                                "Please click a theme in the list first.")
        return name

    def _update_ungroup_btn(self):
        name = self._selected_theme()
        self._btn_ungroup.setEnabled(
            bool(name) and name in self._load_groups()
        )

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self):
        selected   = self._selected_theme()
        self._list.clear()
        tc         = self._tc()
        all_themes = set(tc.mapThemes())
        groups_map = self._load_groups()
        saved_order = self._load_order()

        if self._clean_groups(groups_map, all_themes):
            self._save_groups(groups_map)

        if not all_themes:
            ph = QTreeWidgetItem(self._list, ["  (no themes in project)"])
            ph.setFlags(ph.flags() & ~Qt.ItemIsEnabled)
            ph.setForeground(0, QColor("#999"))
            self._btn_ungroup.setEnabled(False)
            return

        # Sort by saved order first, alphabetical for themes not yet in the list
        order_map = {n: i for i, n in enumerate(saved_order)}
        themes    = sorted(all_themes,
                           key=lambda n: (order_map.get(n, len(saved_order)),
                                          n.casefold()))

        bold = QFont(); bold.setBold(True)
        grp_bold = QFont(); grp_bold.setBold(True)

        group_items = {}   # group_name -> header QTreeWidgetItem

        for name in themes:
            group_name = groups_map.get(name)

            # ── ensure group header exists ────────────────────────────────────
            if group_name is not None:
                if group_name not in group_items:
                    grp = QTreeWidgetItem(self._list, [f"  📁  {group_name}"])
                    grp.setFont(0, grp_bold)
                    grp.setForeground(0, QColor("#1a5276"))
                    grp.setExpanded(True)
                    grp.setFlags(grp.flags() & ~Qt.ItemIsSelectable)
                    grp.setData(0, GROUP_NAME_ROLE, group_name)  # for _rebuild_from_tree
                    group_items[group_name] = grp
                parent = group_items[group_name]
            else:
                parent = self._list.invisibleRootItem()

            # ── leaf item ─────────────────────────────────────────────────────
            item = QTreeWidgetItem(parent, [f"  {name}"])
            item.setData(0, Qt.UserRole, name)

            if name == self._current_theme:
                item.setFont(0, bold)
                item.setForeground(0, QColor("#155724"))
                item.setBackground(0, QColor("#d4edda"))

            if name == selected:
                self._list.setCurrentItem(item)

        self._filter(self._search.text())
        self._update_ungroup_btn()

    def _filter(self, text):
        text = text.strip().casefold()
        root = self._list.invisibleRootItem()
        for i in range(root.childCount()):
            top       = root.child(i)
            full_name = top.data(0, Qt.UserRole)
            if full_name is not None:
                top.setHidden(bool(text) and text not in full_name.casefold())
            else:
                any_vis = False
                for j in range(top.childCount()):
                    leaf      = top.child(j)
                    leaf_name = (leaf.data(0, Qt.UserRole) or "").casefold()
                    hidden    = bool(text) and text not in leaf_name
                    leaf.setHidden(hidden)
                    if not hidden:
                        any_vis = True
                top.setHidden(not any_vis)

    # ── Apply (click) ─────────────────────────────────────────────────────────

    def _on_item_clicked(self, item, column):
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        self._tc().applyTheme(name, self._root(), self._model())
        self.iface.mapCanvas().refresh()
        self._current_theme = name
        self._status.setText(f"✅  Applied: <b>{name}</b>")
        self._populate()

    # ── Add ───────────────────────────────────────────────────────────────────

    def _on_add(self):
        tc = self._tc()
        name, ok = QInputDialog.getText(self, "Add Theme", "New theme name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in tc.mapThemes():
            QMessageBox.warning(self, "Already Exists",
                                f"A theme named '{name}' already exists.")
            return
        state = tc.createThemeFromCurrentState(self._root(), self._model())
        tc.insert(name, state)
        self._status.setText(f"➕  Created: <b>{name}</b>  (from current canvas)")
        self._populate()

    # ── Rename ────────────────────────────────────────────────────────────────

    def _on_rename(self):
        old = self._require_selection()
        if not old:
            return
        tc = self._tc()
        new, ok = QInputDialog.getText(self, "Rename Theme", "New name:", text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        if new in tc.mapThemes():
            QMessageBox.warning(self, "Already Exists",
                                f"A theme named '{new}' already exists.")
            return
        tc.insert(new, tc.mapThemeState(old))
        tc.removeMapTheme(old)

        # Transfer group assignment and order position
        groups_map = self._load_groups()
        if old in groups_map:
            groups_map[new] = groups_map.pop(old)
            self._save_groups(groups_map)

        order = self._load_order()
        if old in order:
            order[order.index(old)] = new
            self._save_order(order)

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

        groups_map = self._load_groups()
        if name in groups_map:
            del groups_map[name]
            self._save_groups(groups_map)

        order = self._load_order()
        if name in order:
            order.remove(name)
            self._save_order(order)

        if self._current_theme == name:
            self._current_theme = None
            self._status.setText("No theme applied yet.")
        self._populate()

    # ── Create Group ──────────────────────────────────────────────────────────

    def _on_create_group(self):
        tc     = self._tc()
        themes = tc.mapThemes()
        if not themes:
            QMessageBox.information(self, "No Themes",
                                    "No themes in the project to group.")
            return
        groups_map = self._load_groups()
        dlg = CreateGroupDialog(themes, groups_map, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        group_name = dlg.group_name()
        selected   = dlg.selected_themes()

        if not group_name:
            QMessageBox.warning(self, "No Group Name", "Please enter a group name.")
            return
        if not selected:
            QMessageBox.warning(self, "Nothing Selected",
                                "Please select at least one theme.")
            return

        for theme in selected:
            groups_map[theme] = group_name
        self._save_groups(groups_map)
        self._status.setText(
            f"📁  Assigned {len(selected)} theme(s) to group <b>{group_name}</b>"
        )
        self._populate()

    # ── Ungroup ───────────────────────────────────────────────────────────────

    def _on_ungroup(self):
        name = self._require_selection()
        if not name:
            return
        groups_map = self._load_groups()
        if name not in groups_map:
            QMessageBox.information(self, "Not Grouped",
                                    f"'{name}' is not in any group.")
            return
        old_group = groups_map.pop(name)
        self._save_groups(groups_map)
        self._status.setText(
            f"↩  Removed <b>{name}</b> from group <b>{old_group}</b>"
        )
        self._populate()
