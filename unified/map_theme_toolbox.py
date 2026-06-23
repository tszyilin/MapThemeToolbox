# -*- coding: utf-8 -*-
"""
Map Theme Toolbox — combined plugin  (QGIS 3.22+ and QGIS 4.x)
Toolbar buttons:
  1. Modify Theme Layers       (icon_modify.png)
  2. Repair Unavailable Layers (icon_repair.png)
  3. Theme Presenter           (icon_present.png)
  4. Sync Setup                (icon_sync.png)
  5. Quick Sync                (icon_sync_on/off)
  6. Auto-Save                 (clock icon)
"""

import os
import math
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QDialog
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from qgis.PyQt.QtCore import Qt, QTimer, QPointF
from qgis.core import QgsApplication, QgsProject

from .compat import (
    Transparent, NoBrush, NoPen, SolidLine, RoundCap,
    Antialiasing, RightDock, Button_Yes, Button_No, Accepted,
)
from .processing_provider import MapThemeToolboxProvider
from .sync_state import REGISTRY
from .autosave_manager import AutoSaveManager

MENU = "&Map Theme Toolbox"


class MapThemeToolbox:
    def __init__(self, iface):
        self.iface    = iface
        self.provider = None
        self.actions  = []
        self.toolbar  = self.iface.addToolBar("Map Theme Toolbox")
        self.toolbar.setObjectName("MapThemeToolboxToolbar")
        self._quick_sync_action = None
        self._present_dock      = None
        self._autosave          = None
        self._autosave_action   = None

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

    def _make_autosave_icon(self, enabled):
        SIZE = 20
        pix  = QPixmap(SIZE, SIZE)
        pix.fill(Transparent)

        p = QPainter(pix)
        p.setRenderHint(Antialiasing)

        col = QColor("#27ae60") if enabled else QColor("#95a5a6")
        cx = cy = SIZE / 2.0
        r  = SIZE / 2.0 - 1.5

        p.setPen(QPen(col, 1.8))
        p.setBrush(NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        pen = QPen(col, 1.8, SolidLine, RoundCap)
        p.setPen(pen)
        ah = math.radians(-60)
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + r * 0.50 * math.sin(ah),
                            cy - r * 0.50 * math.cos(ah)))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.75))

        p.setPen(NoPen)
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(cx, cy), 1.5, 1.5)
        p.end()
        return QIcon(pix)

    def initGui(self):
        self.provider = MapThemeToolboxProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        self._add_action("icon_modify.png", "Modify Theme Layers",
                         self.run_modify, "Toggle mutual layer visibility across themes")
        self._add_action("icon_repair.png", "Repair Unavailable Layers",
                         self.run_repair,
                         "Batch re-link broken layer paths after moving project files")
        self._add_action("icon_present.png", "Theme Presenter",
                         self.run_present, "Apply any map theme with a single click")
        self._add_action("icon_sync.png", "Sync Setup (Excel/CSV ↔ GeoPackage)",
                         self.run_sync, "Open the sync connection setup dialog")

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

        REGISTRY.register_callback(self._on_connection_changed)
        self._on_connection_changed()

        self.toolbar.addSeparator()
        self._autosave = AutoSaveManager(self.iface)
        self._autosave_action = QAction(
            self._make_autosave_icon(self._autosave.enabled),
            "Auto-Save  (off)",
            self.iface.mainWindow()
        )
        self._autosave_action.setToolTip("Auto-Save is OFF — click to configure")
        self._autosave_action.triggered.connect(self.run_autosave)
        self.toolbar.addAction(self._autosave_action)
        self.iface.addPluginToMenu(MENU, self._autosave_action)
        self.actions.append(self._autosave_action)

        self._autosave.register_callback(self._on_autosave_changed)
        self._on_autosave_changed()

        if self._autosave.show_on_start:
            QTimer.singleShot(800, self.run_autosave)

    def unload(self):
        REGISTRY.unregister_callback(self._on_connection_changed)
        if self._autosave:
            self._autosave.stop()
        for act in self.actions:
            self.iface.removePluginMenu(MENU, act)
            self.iface.removeToolBarIcon(act)
        del self.toolbar
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        if self._present_dock:
            self.iface.removeDockWidget(self._present_dock)
            self._present_dock.deleteLater()
            self._present_dock = None

    def _on_connection_changed(self):
        if self._quick_sync_action is None:
            return
        connected = REGISTRY.connected_list()
        if connected:
            self._quick_sync_action.setIcon(self._icon("icon_sync_on.png"))
            if len(connected) == 1:
                label = connected[0].name
                tip   = (f"Quick Sync — click to push data now\n"
                         f"Connection: {connected[0].name}\n"
                         f"File:  {os.path.basename(connected[0].file_path or '')}\n"
                         f"Layer: {connected[0].layer_name}")
            else:
                label = f"{len(connected)} connected"
                tip   = "Quick Sync — will sync all connected connections:\n" + \
                        "\n".join(f"  • {c.name}" for c in connected)
            self._quick_sync_action.setText(f"Quick Sync  ✔ {label}")
            self._quick_sync_action.setToolTip(tip)
            self._quick_sync_action.setEnabled(True)
        else:
            self._quick_sync_action.setIcon(self._icon("icon_sync_off.png"))
            self._quick_sync_action.setText("Quick Sync  (not connected)")
            self._quick_sync_action.setToolTip(
                "Quick Sync: no connections set up yet.\n"
                "Click 'Sync Setup' first to connect a file."
            )
            self._quick_sync_action.setEnabled(False)

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

    def run_modify(self):
        from .dialog_modify_layers import ThemeSelectDialog, LayerToggleDialog
        tc, all_themes = self._require_themes()
        if all_themes is None: return
        project = QgsProject.instance()
        root  = project.layerTreeRoot()
        model = self.iface.layerTreeView().layerTreeModel()
        dlg1 = ThemeSelectDialog(all_themes, parent=self.iface.mainWindow())
        if dlg1.exec() != Accepted: return
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
        if dlg2.exec() != Accepted: return
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
            Button_Yes | Button_No, Button_No
        )
        if reply != Button_Yes: return
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

    def run_repair(self):
        from .dialog_repair_layers import RepairLayersDialog
        RepairLayersDialog(parent=self.iface.mainWindow()).exec()

    def run_present(self):
        from .dialog_apply_theme import ThemePresenterDock
        if self._present_dock is None:
            self._present_dock = ThemePresenterDock(self.iface, parent=self.iface.mainWindow())
            self.iface.addDockWidget(RightDock, self._present_dock)
            return
        if self._present_dock.isVisible():
            self._present_dock.hide()
        else:
            self._present_dock.show()
            self._present_dock.raise_()

    def run_sync(self):
        from .dialog_sync_table import SyncTableDialog
        SyncTableDialog(self.iface, parent=self.iface.mainWindow()).exec()

    def _on_autosave_changed(self):
        if self._autosave_action is None or self._autosave is None:
            return
        enabled = self._autosave.enabled
        self._autosave_action.setIcon(self._make_autosave_icon(enabled))
        if enabled:
            ivl = self._autosave.interval
            mins, secs = divmod(ivl, 60)
            label = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            self._autosave_action.setText(f"Auto-Save  ✔ {label}")
            self._autosave_action.setToolTip(f"Auto-Save: ON — every {label}\nClick to configure.")
        else:
            self._autosave_action.setText("Auto-Save  (off)")
            self._autosave_action.setToolTip("Auto-Save is OFF — click to configure.")

    def run_autosave(self):
        from .dialog_autosave import AutoSaveDialog
        AutoSaveDialog(self._autosave, parent=self.iface.mainWindow()).exec()

    def run_quick_sync(self):
        connected = REGISTRY.connected_list()
        if not connected:
            QMessageBox.information(self.iface.mainWindow(), "Not Connected",
                "No connections set up yet.\nClick 'Sync Setup' to connect a file first.")
            return
        from .dialog_sync_table import perform_sync
        results = []
        all_ok  = True
        for conn in connected:
            success, msg = perform_sync(conn, self.iface)
            results.append(f"{conn.name}: {msg}")
            if not success:
                all_ok = False
        summary = "  |  ".join(results)
        if all_ok:
            self.iface.messageBar().pushSuccess("Quick Sync", summary)
        else:
            self.iface.messageBar().pushWarning("Quick Sync (some errors)", summary)
