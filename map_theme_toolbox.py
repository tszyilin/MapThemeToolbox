# -*- coding: utf-8 -*-
"""
Map Theme Toolbox — combined plugin
Toolbar buttons:
  1. Create New Themes         (icon_create.png   — teal +)
  2. Modify Theme Layers       (icon_modify.png   — orange layers)
  3. Repair Unavailable Layers (icon_repair.png   — crosshair scope)
  4. Theme Presenter           (icon_present.png  — green screen/play)
  5. Auto-Save                 (QGIS save icon    — green=on, grey=off)
"""

import os
import math
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from qgis.PyQt.QtCore import Qt, QTimer, QPointF
from qgis.core import QgsApplication, QgsProject

from .processing_provider import MapThemeToolboxProvider
from .autosave_manager import AutoSaveManager

MENU = "&Map Theme Toolbox"


class MapThemeToolbox:
    def __init__(self, iface):
        self.iface    = iface
        self.provider = None
        self.actions  = []
        self.toolbar  = self.iface.addToolBar("Map Theme Toolbox")
        self.toolbar.setObjectName("MapThemeToolboxToolbar")
        self._present_dock    = None   # ThemePresenterDock instance
        self._autosave        = None   # AutoSaveManager instance
        self._autosave_action = None

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
        """Paint a clock icon: green when auto-save is on, grey when off."""
        SIZE = 20
        pix  = QPixmap(SIZE, SIZE)
        pix.fill(Qt.transparent)

        p   = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)

        col = QColor("#27ae60") if enabled else QColor("#95a5a6")
        cx = cy = SIZE / 2.0
        r  = SIZE / 2.0 - 1.5

        # Outer ring
        p.setPen(QPen(col, 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Clock hands (10:10 position — symmetrical, looks like a smile)
        pen = QPen(col, 1.8, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        # Hour hand → 10 o'clock
        ah = math.radians(-60)   # 300° from top = 10 o'clock
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + r * 0.50 * math.sin(ah),
                            cy - r * 0.50 * math.cos(ah)))
        # Minute hand → 12 o'clock (straight up)
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.75))

        # Centre dot
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(cx, cy), 1.5, 1.5)

        p.end()
        return QIcon(pix)

    def initGui(self):
        self.provider = MapThemeToolboxProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        self._add_action("icon_create.png", "Create New Themes",
                         self.run_create, "Create empty themes one-by-one or from a CSV")
        self._add_action("icon_modify.png", "Modify Theme Layers",
                         self.run_modify, "Toggle mutual layer visibility across themes")
        self._add_action("icon_repair.png", "Repair Unavailable Layers",
                         self.run_repair,
                         "Batch re-link broken layer paths after moving project files")
        self._add_action("icon_present.png", "Theme Presenter",
                         self.run_present,
                         "Apply any map theme with a single click")

        # ── Auto-Save button ─────────────────────────────────────────────────
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
        self._on_autosave_changed()   # reflect saved state on startup

        # ── Optionally show Auto-Save dialog on QGIS startup ─────────────────
        if self._autosave.show_on_start:
            QTimer.singleShot(800, self.run_autosave)

    def unload(self):
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

    # ── 1. Create ─────────────────────────────────────────────────────────────

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

    # ── 2. Modify layers ──────────────────────────────────────────────────────

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

    # ── 3. Repair unavailable layers ─────────────────────────────────────────

    def run_repair(self):
        from .dialog_repair_layers import RepairLayersDialog
        dlg = RepairLayersDialog(parent=self.iface.mainWindow())
        dlg.exec_()

    # ── 4. Theme Presenter ────────────────────────────────────────────────────

    def run_present(self):
        from .dialog_apply_theme import ThemePresenterDock
        if self._present_dock is None:
            self._present_dock = ThemePresenterDock(self.iface, parent=self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self._present_dock)
            return   # already visible after addDockWidget — skip the toggle
        # Subsequent clicks: toggle visibility
        if self._present_dock.isVisible():
            self._present_dock.hide()
        else:
            self._present_dock.show()
            self._present_dock.raise_()

    # ── Auto-Save state callback ──────────────────────────────────────────────

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
            self._autosave_action.setToolTip(
                f"Auto-Save: ON — every {label}\nClick to configure."
            )
        else:
            self._autosave_action.setText("Auto-Save  (off)")
            self._autosave_action.setToolTip(
                "Auto-Save is OFF — click to configure."
            )

    # ── 5. Auto-Save ─────────────────────────────────────────────────────────

    def run_autosave(self):
        from .dialog_autosave import AutoSaveDialog
        dlg = AutoSaveDialog(self._autosave, parent=self.iface.mainWindow())
        dlg.exec_()
