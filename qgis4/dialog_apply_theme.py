# -*- coding: utf-8 -*-
"""
Theme Presenter — dockable panel for applying map themes with one click.
QGIS 4 / PyQt6 version.

Hierarchy is stored in QgsProject custom variable 'mtt_tree' as a JSON tree:
  {"type": "root", "children": [
    {"type": "group", "name": "FDF", "children": [
      {"type": "group", "name": "100AEP", "children": [
        {"type": "theme", "name": "FDF_100AEP_d"}, ...
      ]},
      {"type": "theme", "name": "FDF_500AEP_d"}, ...
    ]},
    {"type": "theme", "name": "Regional"}
  ]}

QGIS theme names are NEVER modified.

Drag-and-drop:
  • Drag a theme  — reorder, move between groups, drop to blank area to ungroup
  • Drag a group  — reorder groups, drop INTO another group to create sub-group

Buttons:
  Add | Rename (theme or group) | Replace | Delete | Create Group | Ungroup
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

TREE_VAR        = "mtt_tree"          # primary storage (hierarchical JSON)
_LEGACY_GRP     = "mtt_theme_groups"  # old flat {theme: group} — migrated on first load
_LEGACY_ORDER   = "mtt_theme_order"   # old [theme, ...] order — migrated on first load
GROUP_NAME_ROLE = Qt.ItemDataRole.UserRole + 1   # extra data role on group-header items


# ── Drag-and-drop tree widget ─────────────────────────────────────────────────

class ThemeTree(QTreeWidget):
    """
    QTreeWidget with drag-and-drop for both themes AND group headers.
    After every valid drop, calls dock._rebuild_from_tree() to persist.
    """

    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self._dock = dock
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        target    = self.itemAt(event.pos())
        indicator = self.dropIndicatorPosition()
        dragged   = self.currentItem()

        if dragged is None:
            event.ignore()
            return

        # Block: dropping ON a theme leaf (would nest inside it)
        if (target is not None
                and target.data(0, Qt.ItemDataRole.UserRole) is not None   # leaf
                and indicator == QAbstractItemView.DropIndicatorPosition.OnItem):
            event.ignore()
            return

        # Block: dropping a group header inside itself or a descendant
        if dragged.data(0, Qt.ItemDataRole.UserRole) is None:   # dragged is a group
            ancestor = target
            while ancestor is not None:
                if ancestor is dragged:
                    event.ignore()
                    return
                ancestor = ancestor.parent()

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
        hint = QLabel("Hold Ctrl to select multiple.  Current group shown in [brackets].")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for theme in sorted(themes, key=str.casefold):
            grp   = groups_map.get(theme)
            label = f"{theme}  [{grp}]" if grp else theme
            item  = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, theme)
            if grp:
                item.setForeground(QColor("#1a5276"))
            self._list.addItem(item)
        layout.addWidget(self._list)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def group_name(self):
        return self._name_edit.text().strip()

    def selected_themes(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self._list.selectedItems()]


# ── Theme Presenter dock ──────────────────────────────────────────────────────

class ThemePresenterDock(QDockWidget):

    def __init__(self, iface, parent=None):
        super().__init__("Theme Presenter", parent)
        self.iface          = iface
        self._current_theme = None

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea |
            Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        hdr = QLabel("Click theme to apply · Drag themes or groups to reorder / nest.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet("color:#555; font-size:10px; padding-bottom:2px;")
        layout.addWidget(hdr)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Filter themes…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Drag-drop tree
        self._list = ThemeTree(self)
        self._list.setHeaderHidden(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setAlternatingRowColors(True)
        self._list.setIndentation(16)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        # ── 2×2 action buttons ────────────────────────────────────────────────
        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)

        self._btn_add     = QPushButton("➕  Add")
        self._btn_rename  = QPushButton("✏️  Rename")
        self._btn_replace = QPushButton("🔄  Replace")
        self._btn_delete  = QPushButton("🗑  Delete")

        self._btn_add.setToolTip("Create a new theme from the current canvas state")
        self._btn_rename.setToolTip("Rename the selected theme or group")
        self._btn_replace.setToolTip("Overwrite selected theme with current canvas state")
        self._btn_delete.setToolTip("Delete the selected theme from QGIS")
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
            "Assign themes to a named group.\n"
            "Drag group headers to reorder or nest as sub-groups.")
        self._btn_ungroup.setToolTip(
            "Move selected theme to the top level (no group).\n"
            "Or drag it out of the group folder.")
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

    # ── Tree JSON persistence ─────────────────────────────────────────────────

    def _load_tree(self):
        """Load the hierarchy tree from project variables, migrating legacy format if needed."""
        vars_ = QgsProject.instance().customVariables()
        raw = vars_.get(TREE_VAR, "")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass

        # ── Migrate from legacy flat format ───────────────────────────────────
        grp_raw   = vars_.get(_LEGACY_GRP, "")
        order_raw = vars_.get(_LEGACY_ORDER, "")
        if grp_raw or order_raw:
            try:
                groups_map = json.loads(grp_raw) if grp_raw else {}
            except Exception:
                groups_map = {}
            try:
                order = json.loads(order_raw) if order_raw else []
            except Exception:
                order = []
            buckets = {}
            root_themes = []
            for name in order:
                g = groups_map.get(name)
                if g:
                    buckets.setdefault(g, []).append({"type": "theme", "name": name})
                else:
                    root_themes.append({"type": "theme", "name": name})
            children = [
                {"type": "group", "name": g, "children": ts}
                for g, ts in buckets.items()
            ] + root_themes
            return {"type": "root", "children": children}

        return {"type": "root", "children": []}

    def _save_tree(self, tree):
        v = QgsProject.instance().customVariables()
        v[TREE_VAR] = json.dumps(tree, ensure_ascii=False)
        QgsProject.instance().setCustomVariables(v)

    # ── Tree helpers ──────────────────────────────────────────────────────────

    def _collect_themes(self, node):
        """Return set of all theme names anywhere in the tree."""
        if node["type"] == "theme":
            return {node["name"]}
        result = set()
        for child in node.get("children", []):
            result |= self._collect_themes(child)
        return result

    def _clean_tree(self, node, valid):
        """Remove theme entries whose names are not in `valid`. Returns node."""
        if node["type"] == "theme":
            return node if node["name"] in valid else None
        if "children" in node:
            node["children"] = [
                r for r in (self._clean_tree(c, valid) for c in node["children"])
                if r is not None
            ]
        return node

    def _remove_themes_from_tree(self, node, names):
        """Remove all theme nodes whose name is in `names` (in place)."""
        if "children" not in node:
            return
        node["children"] = [
            c for c in node["children"]
            if not (c["type"] == "theme" and c["name"] in names)
        ]
        for c in node["children"]:
            self._remove_themes_from_tree(c, names)

    def _rename_theme_in_tree(self, node, old, new):
        if node["type"] == "theme" and node["name"] == old:
            node["name"] = new
        for c in node.get("children", []):
            self._rename_theme_in_tree(c, old, new)

    def _rename_group_in_tree(self, node, old, new):
        for c in node.get("children", []):
            if c["type"] == "group" and c["name"] == old:
                c["name"] = new
            self._rename_group_in_tree(c, old, new)

    def _find_top_group(self, tree, name):
        """Return first top-level group node with the given name, or None."""
        for c in tree.get("children", []):
            if c["type"] == "group" and c["name"] == name:
                return c
        return None

    def _build_groups_map(self, node, _path=None):
        """Return {theme_name: immediate_group_name} (deepest group only)."""
        result = {}
        if node["type"] == "group":
            for c in node.get("children", []):
                if c["type"] == "theme":
                    result[c["name"]] = node["name"]
                else:
                    result.update(self._build_groups_map(c))
        elif node["type"] == "root":
            for c in node.get("children", []):
                result.update(self._build_groups_map(c))
        return result

    def _is_theme_grouped(self, name):
        tree = self._load_tree()
        return name in self._build_groups_map(tree)

    # ── Rebuild from QTreeWidget state (called after drag-drop) ───────────────

    def _rebuild_from_tree(self):
        root_item = self._list.invisibleRootItem()
        children  = [
            self._item_to_node(root_item.child(i))
            for i in range(root_item.childCount())
        ]
        children = [n for n in children if n]

        tree = {"type": "root", "children": children}

        # Recover any themes that Qt might have dropped/lost
        all_themes = set(self._tc().mapThemes())
        in_tree    = self._collect_themes(tree)
        for name in sorted(all_themes - in_tree, key=str.casefold):
            tree["children"].append({"type": "theme", "name": name})

        self._save_tree(tree)
        self._populate()

    def _item_to_node(self, item):
        theme_name = item.data(0, Qt.ItemDataRole.UserRole)
        if theme_name is not None:
            return {"type": "theme", "name": theme_name}
        group_name = item.data(0, GROUP_NAME_ROLE)
        if not group_name:
            return None
        children = [
            self._item_to_node(item.child(i))
            for i in range(item.childCount())
        ]
        return {"type": "group", "name": group_name,
                "children": [n for n in children if n]}

    # ── Core helpers ──────────────────────────────────────────────────────────

    def _tc(self):
        return QgsProject.instance().mapThemeCollection()

    def _root(self):
        return QgsProject.instance().layerTreeRoot()

    def _model(self):
        return self.iface.layerTreeView().layerTreeModel()

    def _selected_theme(self):
        """Return theme name if a theme leaf is selected, else None."""
        item = self._list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _selected_group(self):
        """Return group name if a group header is selected, else None."""
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(0, GROUP_NAME_ROLE)

    def _require_theme_selection(self):
        name = self._selected_theme()
        if not name:
            QMessageBox.warning(self, "No Theme Selected",
                                "Please click a theme (not a group) in the list first.")
        return name

    def _update_ungroup_btn(self):
        name = self._selected_theme()
        self._btn_ungroup.setEnabled(bool(name) and self._is_theme_grouped(name))

    def _on_selection_changed(self, current, previous):
        self._update_ungroup_btn()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self):
        selected   = self._selected_theme()
        self._list.clear()
        tc         = self._tc()
        all_themes = set(tc.mapThemes())

        tree = self._load_tree()
        orig = self._collect_themes(tree)

        # Remove stale / add new
        self._clean_tree(tree, all_themes)
        after_clean = self._collect_themes(tree)
        new_themes  = sorted(all_themes - after_clean, key=str.casefold)
        for name in new_themes:
            tree["children"].append({"type": "theme", "name": name})
        if orig != all_themes or new_themes:
            self._save_tree(tree)

        if not all_themes:
            ph = QTreeWidgetItem(self._list, ["  (no themes in project)"])
            ph.setFlags(ph.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            ph.setForeground(0, QColor("#999"))
            self._btn_ungroup.setEnabled(False)
            return

        bold     = QFont(); bold.setBold(True)
        grp_bold = QFont(); grp_bold.setBold(True)

        self._populate_children(
            self._list.invisibleRootItem(),
            tree.get("children", []),
            selected, bold, grp_bold
        )

        self._filter(self._search.text())
        self._update_ungroup_btn()

    def _populate_children(self, parent, children, selected, bold, grp_bold):
        for node in children:
            if node["type"] == "group":
                grp = QTreeWidgetItem(parent, [f"  📁  {node['name']}"])
                grp.setFont(0, grp_bold)
                grp.setForeground(0, QColor("#1a5276"))
                grp.setExpanded(True)
                grp.setData(0, Qt.ItemDataRole.UserRole, None)
                grp.setData(0, GROUP_NAME_ROLE, node["name"])
                grp.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                    Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
                )
                self._populate_children(
                    grp, node.get("children", []), selected, bold, grp_bold
                )

            elif node["type"] == "theme":
                name = node["name"]
                item = QTreeWidgetItem(parent, [f"  {name}"])
                item.setData(0, Qt.ItemDataRole.UserRole, name)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                    Qt.ItemFlag.ItemIsDragEnabled
                    # No ItemIsDropEnabled — themes are leaves
                )
                if name == self._current_theme:
                    item.setFont(0, bold)
                    item.setForeground(0, QColor("#155724"))
                    item.setBackground(0, QColor("#d4edda"))
                if name == selected:
                    self._list.setCurrentItem(item)

    def _filter(self, text):
        text = text.strip().casefold()
        root = self._list.invisibleRootItem()
        for i in range(root.childCount()):
            self._filter_node(root.child(i), text)

    def _filter_node(self, item, text):
        """Recursively hide non-matching items. Returns True if item is visible."""
        theme_name = item.data(0, Qt.ItemDataRole.UserRole)
        if theme_name is not None:
            visible = not text or text in theme_name.casefold()
            item.setHidden(not visible)
            return visible
        # Group header
        any_visible = False
        for i in range(item.childCount()):
            if self._filter_node(item.child(i), text):
                any_visible = True
        item.setHidden(not any_visible)
        return any_visible

    # ── Apply (click) ─────────────────────────────────────────────────────────

    def _on_item_clicked(self, item, column):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if not name:
            return   # group header
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

    # ── Rename (theme or group) ───────────────────────────────────────────────

    def _on_rename(self):
        item = self._list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Nothing Selected",
                                "Please click a theme or group header first.")
            return

        theme_name = item.data(0, Qt.ItemDataRole.UserRole)
        group_name = item.data(0, GROUP_NAME_ROLE)

        if theme_name is not None:
            # ── rename theme ─────────────────────────────────────────────────
            tc = self._tc()
            new, ok = QInputDialog.getText(self, "Rename Theme",
                                           "New theme name:", text=theme_name)
            new = new.strip()
            if not ok or not new or new == theme_name:
                return
            if new in tc.mapThemes():
                QMessageBox.warning(self, "Already Exists",
                                    f"A theme named '{new}' already exists.")
                return
            tc.insert(new, tc.mapThemeState(theme_name))
            tc.removeMapTheme(theme_name)
            tree = self._load_tree()
            self._rename_theme_in_tree(tree, theme_name, new)
            self._save_tree(tree)
            if self._current_theme == theme_name:
                self._current_theme = new
                self._status.setText(f"✅  Applied: <b>{new}</b>")
            self._populate()

        elif group_name:
            # ── rename group ─────────────────────────────────────────────────
            new, ok = QInputDialog.getText(self, "Rename Group",
                                           "New group name:", text=group_name)
            new = new.strip()
            if not ok or not new or new == group_name:
                return
            tree = self._load_tree()
            self._rename_group_in_tree(tree, group_name, new)
            self._save_tree(tree)
            self._populate()

    # ── Replace ───────────────────────────────────────────────────────────────

    def _on_replace(self):
        name = self._require_theme_selection()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Replace Theme",
            f"Overwrite <b>{name}</b> with the current canvas state?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        tc    = self._tc()
        state = tc.createThemeFromCurrentState(self._root(), self._model())
        tc.update(name, state)
        self._status.setText(f"🔄  Replaced: <b>{name}</b>")
        self._populate()

    # ── Delete (theme only) ───────────────────────────────────────────────────

    def _on_delete(self):
        item = self._list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Nothing Selected",
                                "Please click a theme to delete.")
            return
        if item.data(0, Qt.ItemDataRole.UserRole) is None:
            QMessageBox.information(
                self, "Select a Theme",
                "To delete a group, first move or delete all themes inside it.\n"
                "Empty groups are removed automatically."
            )
            return
        name = item.data(0, Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete Theme",
            f"Delete theme <b>{name}</b> from QGIS? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._tc().removeMapTheme(name)
        if self._current_theme == name:
            self._current_theme = None
            self._status.setText("No theme applied yet.")
        self._populate()   # _clean_tree in populate removes the stale entry

    # ── Create Group ──────────────────────────────────────────────────────────

    def _on_create_group(self):
        tc     = self._tc()
        themes = list(tc.mapThemes())
        if not themes:
            QMessageBox.information(self, "No Themes",
                                    "No themes in the project to group.")
            return

        tree       = self._load_tree()
        groups_map = self._build_groups_map(tree)
        dlg        = CreateGroupDialog(themes, groups_map, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
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

        # Remove selected themes from wherever they are now
        self._remove_themes_from_tree(tree, set(selected))

        # Find or create the target top-level group
        target_grp = self._find_top_group(tree, group_name)
        if target_grp is None:
            target_grp = {"type": "group", "name": group_name, "children": []}
            tree["children"].append(target_grp)

        for name in selected:
            target_grp["children"].append({"type": "theme", "name": name})

        self._save_tree(tree)
        self._status.setText(
            f"📁  Assigned {len(selected)} theme(s) to group <b>{group_name}</b>"
        )
        self._populate()

    # ── Ungroup (move theme to root) ──────────────────────────────────────────

    def _on_ungroup(self):
        name = self._require_theme_selection()
        if not name:
            return
        tree       = self._load_tree()
        groups_map = self._build_groups_map(tree)
        if name not in groups_map:
            QMessageBox.information(self, "Not Grouped",
                                    f"'{name}' is not inside any group.")
            return
        old_group = groups_map[name]
        self._remove_themes_from_tree(tree, {name})
        tree["children"].append({"type": "theme", "name": name})
        self._save_tree(tree)
        self._status.setText(
            f"↩  Removed <b>{name}</b> from group <b>{old_group}</b>"
        )
        self._populate()
