# -*- coding: utf-8 -*-
"""
Theme Presenter — dockable panel for applying map themes with one click.

Grouping is stored in QgsProject custom variable 'mtt_theme_groups' as JSON
{theme_name: group_name}.  The actual QGIS theme names are NEVER changed.

Operations available:
  • Click theme    — apply instantly to canvas
  • Add            — create new theme from current canvas state
  • Rename         — rename the selected theme
  • Replace        — overwrite selected theme with current canvas state
  • Delete         — delete the selected theme
  • Create Group   — pick themes and assign them to a named group
  • Ungroup        — remove the selected theme from its group
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

GROUP_VAR = "mtt_theme_groups"   # key in QgsProject.customVariables()


# ── Create Group dialog ───────────────────────────────────────────────────────

class CreateGroupDialog(QDialog):
    """Pick a group name + select which themes to assign to it."""

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
            grp = groups_map.get(theme)
            label = f"{theme}  [{grp}]" if grp else theme
            item = QListWidgetItem(label)
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

        # Theme tree
        self._list = QTreeWidget()
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

        # ── Group buttons row ─────────────────────────────────────────────────
        grp_grid = QGridLayout()
        grp_grid.setSpacing(4)

        self._btn_group   = QPushButton("📁  Create Group")
        self._btn_ungroup = QPushButton("↩  Ungroup")

        self._btn_group.setToolTip(
            "Select themes to assign to a named group.\n"
            "Theme names are NOT changed — grouping is display-only."
        )
        self._btn_ungroup.setToolTip("Remove the selected theme from its group")
        self._btn_ungroup.setEnabled(False)

        self._btn_group.clicked.connect(self._on_create_group)
        self._btn_ungroup.clicked.connect(self._on_ungroup)

        grp_grid.addWidget(self._btn_group,   0, 0)
        grp_grid.addWidget(self._btn_ungroup, 0, 1)
        layout.addLayout(grp_grid)

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

    # ── Group metadata helpers ────────────────────────────────────────────────

    def _load_groups(self):
        """Return {theme_name: group_name} from project custom variables."""
        raw = QgsProject.instance().customVariables().get(GROUP_VAR, "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save_groups(self, mapping):
        """Persist {theme_name: group_name} into project custom variables."""
        variables = QgsProject.instance().customVariables()
        variables[GROUP_VAR] = json.dumps(mapping, ensure_ascii=False)
        QgsProject.instance().setCustomVariables(variables)

    def _clean_groups(self, mapping, existing_themes):
        """Remove stale entries for themes that no longer exist."""
        stale = [t for t in mapping if t not in existing_themes]
        changed = bool(stale)
        for t in stale:
            del mapping[t]
        return changed

    # ── Core helpers ──────────────────────────────────────────────────────────

    def _tc(self):
        return QgsProject.instance().mapThemeCollection()

    def _root(self):
        return QgsProject.instance().layerTreeRoot()

    def _model(self):
        return self.iface.layerTreeView().layerTreeModel()

    def _selected_theme(self):
        """Return the full QGIS theme name of the selected leaf, or None."""
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
        selected    = self._selected_theme()
        self._list.clear()
        tc          = self._tc()
        all_themes  = set(tc.mapThemes())
        themes      = sorted(all_themes, key=str.casefold)

        # Load + clean group map
        groups_map = self._load_groups()
        if self._clean_groups(groups_map, all_themes):
            self._save_groups(groups_map)

        if not themes:
            placeholder = QTreeWidgetItem(self._list, ["  (no themes in project)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsEnabled)
            placeholder.setForeground(0, QColor("#999"))
            self._btn_ungroup.setEnabled(False)
            return

        bold = QFont()
        bold.setBold(True)
        group_bold = QFont()
        group_bold.setBold(True)

        group_items = {}   # group_name -> QTreeWidgetItem header

        for name in themes:
            group_name = groups_map.get(name)   # None = ungrouped

            # ── ensure group header exists ────────────────────────────────────
            if group_name is not None:
                if group_name not in group_items:
                    grp = QTreeWidgetItem(self._list, [f"  📁  {group_name}"])
                    grp.setFont(0, group_bold)
                    grp.setForeground(0, QColor("#1a5276"))
                    grp.setExpanded(True)
                    grp.setFlags(grp.flags() & ~Qt.ItemIsSelectable)
                    group_items[group_name] = grp
                parent = group_items[group_name]
            else:
                parent = self._list.invisibleRootItem()

            # ── leaf item (always shows the real theme name) ──────────────────
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
                # Root-level leaf (ungrouped)
                top.setHidden(bool(text) and text not in full_name.casefold())
            else:
                # Group header — hide if ALL children hidden
                any_visible = False
                for j in range(top.childCount()):
                    leaf      = top.child(j)
                    leaf_name = (leaf.data(0, Qt.UserRole) or "").casefold()
                    hidden    = bool(text) and text not in leaf_name
                    leaf.setHidden(hidden)
                    if not hidden:
                        any_visible = True
                top.setHidden(not any_visible)

    def _update_ungroup_btn(self):
        """Enable Ungroup only when a grouped theme is selected."""
        name = self._selected_theme()
        if name:
            grps = self._load_groups()
            self._btn_ungroup.setEnabled(name in grps)
        else:
            self._btn_ungroup.setEnabled(False)

    # ── Apply (click) ─────────────────────────────────────────────────────────

    def _on_item_clicked(self, item, column):
        name = item.data(0, Qt.UserRole)
        if not name:
            return   # group header — ignore
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
            self, "Add Theme", "New theme name:"
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

        # Keep group assignment under the new name
        groups_map = self._load_groups()
        if old in groups_map:
            groups_map[new] = groups_map.pop(old)
            self._save_groups(groups_map)

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

        # Remove from group map
        groups_map = self._load_groups()
        if name in groups_map:
            del groups_map[name]
            self._save_groups(groups_map)

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
        self._status.setText(f"↩  Removed <b>{name}</b> from group <b>{old_group}</b>")
        self._populate()
