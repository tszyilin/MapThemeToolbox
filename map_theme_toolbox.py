# -*- coding: utf-8 -*-
"""
Map Theme Toolbox — combined plugin
Toolbar buttons:
  1. Delete Map Themes      (icon_delete.png  — red trash)
  2. Export Themes to CSV   (icon_export.png  — green arrow)
  3. Rename Map Themes      (icon_rename.png  — blue pencil)
  4. Create New Themes      (icon_create.png  — teal +)
  5. Modify Theme Layers    (icon_modify.png  — orange layers)
  6. Sync Setup             (icon_sync.png    — opens full dialog)
  7. Quick Sync             (icon_sync_on/off — green=ready, grey=not connected)
"""

import os
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication, QgsProject

from .processing_provider import MapThemeToolboxProvider
from .sync_state import CONNECTION

MENU = "&Map Theme Toolbox"


class MapThemeToolbox:
    def __init__(self, iface):
        self.iface    = iface
        self.provider = None
        self.actions  = []
        self.toolbar  = self.iface.addToolBar("Map Theme Toolbox")
        self.toolbar.setObjectName("MapThemeToolboxToolbar")
        self._quick_sync_action = None

    def _icon(self, name):
        path = os.path.join(os.path.dirname(__file__), name)
        return QIcon(path) if os.path.exists(path) else QIcon()

    def _add_action(self, icon_file, label, slot, tooltip=""):
        act = QAction(self._icon(icon_file), label, self.iface.mainWindow())
        act.setToolTip(tooltip or label)
        act.triggered.connect(slot)
        self.toolbar.addAction(act)
        self.iface.addPluginToMenu(MENU, act)
        self.actions.append(act)
        return act

    def initGui(self):
        self.provider = MapThemeToolboxProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        self._add_action("icon_delete.png", "Delete Map Themes",
                         self.run_delete, "Select and delete map themes")
        self._add_action("icon_export.png", "Export Themes to CSV",
                         self.run_export, "Export all map theme names to a CSV file")
        self._add_action("icon_rename.png", "Rename Map Themes",
                         self.run_rename, "Rename themes manually or via CSV import")
        self._add_action("icon_create.png", "Create New Themes",
                         self.run_create, "Create empty themes one-by-one or from a CSV")
        self._add_action("icon_modify.png", "Modify Theme Layers",
                         self.run_modify, "Toggle mutual layer visibility across themes")
        self._add_action("icon_sync.png", "Sync Setup (Excel/CSV ↔ GeoPackage)",
                         self.run_sync, "Open the sync connection setup dialog")

        # ── Quick Sync button — green when connected, grey otherwise ──────────
        self._quick_sync_action = QAction(
            self._icon("icon_sync_off.png"),
            "Quick Sync  (not connected)",
            self.iface.mainWindow()
        )
        self._quick_sync_action.setToolTip(
            "Quick Sync: no connection set up yet.\nClick 'Sync Setup' first to connect a file."
        )
        self._quick_sync_action.setEnabled(False)
        self._quick_sync_action.triggered.connect(self.run_quick_sync)
        self.toolbar.addAction(self._quick_sync_action)
        self.iface.addPluginToMenu(MENU, self._quick_sync_action)
        self.actions.append(self._quick_sync_action)

        # Register for state-change callbacks
        CONNECTION.register_callback(self._on_connection_changed)

        # Sync initial state in case dialog was opened before
        self._on_connection_changed()

    def unload(self):
        CONNECTION.unregister_callback(self._on_connection_changed)
        for act in self.actions:
            self.iface.removePluginMenu(MENU, act)
            self.iface.removeToolBarIcon(act)
        del self.toolbar
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

    # ── Connection state callback ─────────────────────────────────────────────

    def _on_connection_changed(self):
        """Called whenever SyncConnection.connect() or .disconnect() is called."""
        if self._quick_sync_action is None:
            return
        if CONNECTION.connected:
            self._quick_sync_action.setIcon(self._icon("icon_sync_on.png"))
            self._quick_sync_action.setText(f"Quick Sync  ✔ {CONNECTION.layer_name}")
            self._quick_sync_action.setToolTip(
                f"Quick Sync — click to push data now\n"
                f"File:  {os.path.basename(CONNECTION.file_path or '')}\n"
                f"Layer: {CONNECTION.layer_name}"
            )
            self._quick_sync_action.setEnabled(True)
        else:
            self._quick_sync_action.setIcon(self._icon("icon_sync_off.png"))
            self._quick_sync_action.setText("Quick Sync  (not connected)")
            self._quick_sync_action.setToolTip(
                "Quick Sync: no connection set up yet.\nClick 'Sync Setup' first to connect a file."
            )
            self._quick_sync_action.setEnabled(False)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _tc(self):
        return QgsProject.instance().mapThemeCollection()

    def _require_themes(self):
        tc = self._tc()
        themes = tc.mapThemes()
        if not themes:
            QMessageBox.information(self.iface.mainWindow(), "No Themes",
                                    "No map themes found in the current project.")
            return None, None
        return tc, themes

    # ── 1. Delete ─────────────────────────────────────────────────────────────

    def run_delete(self):
        from .dialog_delete_themes import DeleteThemesDialog
        tc, themes = self._require_themes()
        if themes is None: return
        dlg = DeleteThemesDialog(themes, parent=self.iface.mainWindow())
        if dlg.exec_() != dlg.Accepted: return
        selected = dlg.selected_themes()
        if not selected:
            QMessageBox.information(self.iface.mainWindow(), "Nothing Selected", "No themes selected.")
            return
        reply = QMessageBox.question(
            self.iface.mainWindow(), "Confirm Deletion",
            f"Delete {len(selected)} theme(s)?\n\n" + "\n".join(f"  - {t}" for t in selected),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for t in selected:
                tc.removeMapTheme(t)
            QMessageBox.information(self.iface.mainWindow(), "Done", f"{len(selected)} theme(s) deleted.")

    # ── 2. Export ─────────────────────────────────────────────────────────────

    def run_export(self):
        from qgis import processing
        processing.execAlgorithmDialog("mapthemetoolbox:exportmapthemes", {})

    # ── 3. Rename ─────────────────────────────────────────────────────────────

    def run_rename(self):
        from .dialog_rename_themes import RenameThemesDialog
        tc, themes = self._require_themes()
        if themes is None: return
        dlg = RenameThemesDialog(themes, parent=self.iface.mainWindow())
        if dlg.exec_() != dlg.Accepted: return
        renames = dlg.renames()
        if not renames: return
        for old, new in renames.items():
            record = tc.mapThemeState(old)
            tc.insert(new, record)
            tc.removeMapTheme(old)
        QMessageBox.information(self.iface.mainWindow(), "Done", f"{len(renames)} theme(s) renamed.")

    # ── 4. Create ─────────────────────────────────────────────────────────────

    def run_create(self):
        from .dialog_create_themes import CreateThemesDialog
        project = QgsProject.instance()
        tc = self._tc()
        existing = tc.mapThemes()
        root  = project.layerTreeRoot()
        model = self.iface.layerTreeView().layerTreeModel()
        dlg = CreateThemesDialog(existing, parent=self.iface.mainWindow())
        if dlg.exec_() != dlg.Accepted: return
        names = dlg.names_to_create()
        if not names: return

        # Save current layer visibility, turn everything off, capture the
        # all-hidden state, then restore so the canvas is unchanged.
        all_nodes = root.findLayers()
        saved = {node.layerId(): node.itemVisibilityChecked() for node in all_nodes}
        for node in all_nodes:
            node.setItemVisibilityChecked(False)
        state = tc.createThemeFromCurrentState(root, model)
        for node in all_nodes:
            node.setItemVisibilityChecked(saved.get(node.layerId(), True))

        created = overwritten = 0
        for name in names:
            if name in tc.mapThemes():
                tc.update(name, state); overwritten += 1
            else:
                tc.insert(name, state); created += 1
        parts = []
        if created:     parts.append(f"{created} created")
        if overwritten: parts.append(f"{overwritten} overwritten")
        QMessageBox.information(self.iface.mainWindow(), "Done",
                                f"Themes {' and '.join(parts)} from current canvas state.")

    # ── 5. Modify layers ──────────────────────────────────────────────────────

    def run_modify(self):
        from .dialog_modify_layers import ThemeSelectDialog, LayerToggleDialog
        tc, all_themes = self._require_themes()
        if all_themes is None: return
        project = QgsProject.instance()
        root  = project.layerTreeRoot()
        model = self.iface.layerTreeView().layerTreeModel()
        dlg1 = ThemeSelectDialog(all_themes, parent=self.iface.mainWindow())
        if dlg1.exec_() != dlg1.Accepted: return
        selected = dlg1.selected_themes()
        if not selected:
            QMessageBox.information(self.iface.mainWindow(), "Nothing Selected",
                                    "Please select at least one theme.")
            return
        valid = [t for t in selected if t in all_themes]
        if not valid: return

        def save_state():
            state = tc.createThemeFromCurrentState(root, model)
            tmp = "__mtt_tmp__"
            if tmp in tc.mapThemes(): tc.removeMapTheme(tmp)
            tc.insert(tmp, state)
            return tmp

        def restore_state(tmp):
            tc.applyTheme(tmp, root, model)
            tc.removeMapTheme(tmp)

        tmp = save_state()
        try:
            sets = []
            for t in valid:
                tc.applyTheme(t, root, model)
                visible = set()
                for tl in root.findLayers():
                    if tl.itemVisibilityChecked():
                        l = tl.layer()
                        if l: visible.add(l.name())
                sets.append(visible)
        finally:
            restore_state(tmp)

        common = sorted(set.intersection(*sets)) if len(sets) > 1 else sorted(sets[0])
        all_layer_names = [l.name() for l in project.mapLayers().values()]
        if not common:
            QMessageBox.information(self.iface.mainWindow(), "No Mutual Layers",
                                    "No layers are visible in ALL selected themes.\n"
                                    "You can still add layers manually in the next step.")
        dlg2 = LayerToggleDialog(common, valid, all_layer_names, parent=self.iface.mainWindow())
        if dlg2.exec_() != dlg2.Accepted: return
        to_hide = dlg2.layers_to_hide()
        to_show = [l for l in dlg2.layers_to_show() if l not in common]
        if not to_hide and not to_show:
            QMessageBox.information(self.iface.mainWindow(), "No Changes", "Nothing to update.")
            return
        lines = []
        if to_hide: lines.append(f"Turn OFF ({len(to_hide)}): " + ", ".join(to_hide))
        if to_show: lines.append(f"Turn ON  ({len(to_show)}): " + ", ".join(to_show))
        reply = QMessageBox.question(
            self.iface.mainWindow(), "Confirm Update",
            f"Apply to {len(valid)} theme(s):\n\n" + "\n".join(lines),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes: return
        tmp2 = save_state()
        try:
            for t in valid:
                tc.applyTheme(t, root, model)
                for ln in to_hide:
                    for l in project.mapLayersByName(ln):
                        node = root.findLayer(l.id())
                        if node: node.setItemVisibilityChecked(False)
                for ln in to_show:
                    for l in project.mapLayersByName(ln):
                        node = root.findLayer(l.id())
                        if node: node.setItemVisibilityChecked(True)
                tc.update(t, tc.createThemeFromCurrentState(root, model))
        finally:
            restore_state(tmp2)
        parts = []
        if to_hide: parts.append(f"turned OFF {len(to_hide)} layer(s)")
        if to_show: parts.append(f"turned ON {len(to_show)} extra layer(s)")
        QMessageBox.information(self.iface.mainWindow(), "Done",
                                f"Updated {len(valid)} theme(s) — " + " and ".join(parts) + ".")

    # ── 6. Sync setup (full dialog) ───────────────────────────────────────────

    def run_sync(self):
        from .dialog_sync_table import SyncTableDialog
        dlg = SyncTableDialog(self.iface, parent=self.iface.mainWindow())
        dlg.exec_()

    # ── 7. Quick Sync (one-click, toolbar only) ───────────────────────────────

    def run_quick_sync(self):
        if not CONNECTION.connected:
            QMessageBox.information(self.iface.mainWindow(), "Not Connected",
                "No sync connection set up yet.\nClick 'Sync Setup' to connect a file first.")
            return

        from .dialog_sync_table import SyncTableDialog
        # Re-use the dialog's sync logic via a minimal helper
        dlg = SyncTableDialog(self.iface, parent=self.iface.mainWindow())
        # Dialog restores state from CONNECTION automatically — just trigger sync
        dlg._on_sync()
        # Show result in status bar (dialog stays hidden)
        msg = dlg._last_sync_label.text()
        self.iface.messageBar().pushSuccess("Quick Sync", msg)
