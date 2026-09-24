# -*- coding: utf-8 -*-
"""
Theme Session — export/import.

Exports a self-contained JSON snapshot of the current QGIS project's
Map Themes so the user can rebuild everything (layers + themes + Theme
Presenter tree) on a fresh project if the .qgz is lost.

The snapshot contains:
  - project name + timestamp + plugin version
  - layer catalog: for every layer used by any theme (or every project
    layer), record id / name / source / provider / type / CRS + a full
    QML style string
  - themes: for each theme, the list of visible layer records (id +
    optional named style) and the set of checked layer-tree groups
  - Theme Presenter tree (the mtt_tree custom variable)

Import re-adds any missing layers (matching by source), applies their
saved QML styles, then rebuilds every theme using
QgsMapThemeCollection.MapThemeRecord.  Existing themes with the same
name are replaced.
"""

import json
import os
import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QCheckBox, QDialogButtonBox,
)
from qgis.core import (
    QgsProject, QgsMapThemeCollection, QgsVectorLayer, QgsRasterLayer,
    QgsMeshLayer, QgsReadWriteContext, QgsLayerTreeGroup, QgsLayerTreeLayer,
)
from qgis.PyQt.QtXml import QDomDocument

from .compat import Button_Ok, Button_Cancel, Accepted

SESSION_FORMAT_VERSION = 1
TREE_VAR = "mtt_tree"


# ── helpers ──────────────────────────────────────────────────────────────────

def _layer_kind(layer):
    try:
        from qgis.core import QgsMapLayerType
        t = layer.type()
        if t == QgsMapLayerType.VectorLayer:  return "vector"
        if t == QgsMapLayerType.RasterLayer:  return "raster"
        if t == QgsMapLayerType.MeshLayer:    return "mesh"
    except Exception:
        pass
    cn = layer.__class__.__name__
    if "Vector" in cn: return "vector"
    if "Raster" in cn: return "raster"
    if "Mesh"   in cn: return "mesh"
    return "other"


def _export_style_qml(layer):
    doc = QDomDocument()
    err = layer.exportNamedStyle(doc)
    if err:
        return ""
    return doc.toString()


def _import_style_qml(layer, qml):
    if not qml:
        return
    doc = QDomDocument()
    if not doc.setContent(qml):
        return
    layer.importNamedStyle(doc)
    layer.triggerRepaint()


def _serialize_layer(layer):
    return {
        "id":       layer.id(),
        "name":     layer.name(),
        "source":   layer.source(),
        "provider": (layer.dataProvider().name()
                     if layer.dataProvider() is not None else ""),
        "kind":     _layer_kind(layer),
        "crs":      layer.crs().authid(),
        "qml":      _export_style_qml(layer),
    }


def _serialize_layer_tree(node):
    if isinstance(node, QgsLayerTreeGroup):
        return {
            "type":     "group",
            "name":     node.name(),
            "checked":  node.isVisible(),
            "children": [_serialize_layer_tree(c) for c in node.children()],
        }
    if isinstance(node, QgsLayerTreeLayer):
        layer = node.layer()
        return {
            "type":    "layer",
            "layer_id": node.layerId(),
            "layer_name": layer.name() if layer else "",
            "checked": node.isVisible(),
        }
    return None


def _serialize_theme_record(record):
    layer_records = []
    for lr in record.layerRecords():
        layer = lr.layer()
        if layer is None:
            continue
        layer_records.append({
            "layer_id":    layer.id(),
            "layer_name":  layer.name(),
            "layer_source": layer.source(),
            "use_default_style": bool(lr.usingCurrentStyle) if hasattr(lr, "usingCurrentStyle") else True,
            "current_style":     getattr(lr, "currentStyle", "") or "",
        })
    checked_groups = list(record.checkedGroupNodes()) if hasattr(record, "checkedGroupNodes") else []
    return {
        "layers":         layer_records,
        "checked_groups": checked_groups,
    }


def build_session(project=None, plugin_version="?"):
    project = project or QgsProject.instance()
    tc = project.mapThemeCollection()
    theme_names = tc.mapThemes()

    used_layer_ids = set()
    themes = {}
    for name in theme_names:
        rec = tc.mapThemeState(name)
        themes[name] = _serialize_theme_record(rec)
        for lr in rec.layerRecords():
            if lr.layer():
                used_layer_ids.add(lr.layer().id())

    layer_map = project.mapLayers()
    used_layer_ids.update(layer_map.keys())
    layers = [_serialize_layer(layer_map[lid])
              for lid in layer_map if lid in used_layer_ids]

    root = project.layerTreeRoot()
    tree = [_serialize_layer_tree(c) for c in root.children()]
    tree = [t for t in tree if t]

    vars_ = project.customVariables()
    presenter_tree_raw = vars_.get(TREE_VAR, "")

    return {
        "format_version": SESSION_FORMAT_VERSION,
        "plugin_version": plugin_version,
        "exported_at":    datetime.datetime.now().isoformat(timespec="seconds"),
        "project_name":   project.fileName() or "(unsaved project)",
        "layers":         layers,
        "layer_tree":     tree,
        "themes":         themes,
        "presenter_tree": presenter_tree_raw,
    }


# ── import ───────────────────────────────────────────────────────────────────

def _make_layer(rec):
    kind, source, name = rec["kind"], rec["source"], rec["name"]
    provider = rec.get("provider") or ""
    if kind == "vector":
        return QgsVectorLayer(source, name, provider or "ogr")
    if kind == "raster":
        return QgsRasterLayer(source, name, provider or "gdal")
    if kind == "mesh":
        return QgsMeshLayer(source, name, provider or "mdal")
    return QgsVectorLayer(source, name, provider or "ogr")


def _find_group(root, name):
    for c in root.children():
        if isinstance(c, QgsLayerTreeGroup) and c.name() == name:
            return c
    return None


def _restore_layer_tree(root, tree_nodes, src_to_layer):
    """
    Best-effort recreation of the layer tree structure.  Only creates
    groups that don't exist; moves matching layers into them.  We do
    NOT strip anything the user already has.
    """
    def place(parent, nodes):
        for n in nodes:
            if n["type"] == "group":
                grp = _find_group(parent, n["name"])
                if grp is None:
                    grp = parent.addGroup(n["name"])
                grp.setItemVisibilityChecked(bool(n.get("checked", True)))
                place(grp, n.get("children", []))
            elif n["type"] == "layer":
                src = None
                lid = n.get("layer_id")
                if lid and QgsProject.instance().mapLayer(lid) is not None:
                    src = QgsProject.instance().mapLayer(lid).source()
                if src is None:
                    src = n.get("layer_name")
                layer = src_to_layer.get(src) if src else None
                if layer is None:
                    for l in QgsProject.instance().mapLayers().values():
                        if l.name() == n.get("layer_name"):
                            layer = l
                            break
                if layer is None:
                    continue
                if parent.findLayer(layer.id()) is not None:
                    continue
                already = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
                if already is not None and already.parent() is not parent:
                    parent.addLayer(layer)
                elif already is None:
                    parent.addLayer(layer)
                node = parent.findLayer(layer.id())
                if node:
                    node.setItemVisibilityChecked(bool(n.get("checked", True)))
    place(root, tree_nodes)


def load_session(session, add_missing_layers=True, restore_tree=True,
                 restore_presenter=True):
    """
    Returns (report_dict).  Never raises for per-layer failures; it
    collects them into the report.
    """
    project = QgsProject.instance()
    report = {
        "layers_added":   [],
        "layers_matched": [],
        "layers_failed":  [],
        "themes_created": [],
        "themes_skipped": [],
    }

    # 1) Build source → layer map from existing project.
    src_to_layer = {}
    for l in project.mapLayers().values():
        src_to_layer[l.source()] = l

    # 2) Add missing layers.
    id_remap = {}  # old_id -> new_id
    for rec in session.get("layers", []):
        existing = src_to_layer.get(rec["source"])
        if existing is not None:
            id_remap[rec["id"]] = existing.id()
            report["layers_matched"].append(rec["name"])
            _import_style_qml(existing, rec.get("qml", ""))
            continue
        if not add_missing_layers:
            report["layers_failed"].append(f"{rec['name']} (missing, skipped)")
            continue
        layer = _make_layer(rec)
        if layer is None or not layer.isValid():
            report["layers_failed"].append(f"{rec['name']} (invalid source)")
            continue
        _import_style_qml(layer, rec.get("qml", ""))
        project.addMapLayer(layer, addToLegend=True)
        src_to_layer[rec["source"]] = layer
        id_remap[rec["id"]] = layer.id()
        report["layers_added"].append(rec["name"])

    # 3) Restore layer tree structure.
    if restore_tree:
        _restore_layer_tree(project.layerTreeRoot(),
                            session.get("layer_tree", []),
                            src_to_layer)

    # 4) Rebuild themes.
    tc = project.mapThemeCollection()
    for tname, tdata in session.get("themes", {}).items():
        try:
            record = QgsMapThemeCollection.MapThemeRecord()
            for lr in tdata.get("layers", []):
                new_id = id_remap.get(lr.get("layer_id"))
                layer = None
                if new_id:
                    layer = project.mapLayer(new_id)
                if layer is None:
                    layer = src_to_layer.get(lr.get("layer_source"))
                if layer is None:
                    for l in project.mapLayers().values():
                        if l.name() == lr.get("layer_name"):
                            layer = l
                            break
                if layer is None:
                    continue
                layer_rec = QgsMapThemeCollection.MapThemeLayerRecord(layer)
                if lr.get("current_style"):
                    layer_rec.currentStyle = lr["current_style"]
                    layer_rec.usingCurrentStyle = True
                record.addLayerRecord(layer_rec)
            checked_groups = tdata.get("checked_groups") or []
            if hasattr(record, "setCheckedGroupNodes") and checked_groups:
                record.setCheckedGroupNodes(checked_groups)
            if tname in tc.mapThemes():
                tc.update(tname, record)
            else:
                tc.insert(tname, record)
            report["themes_created"].append(tname)
        except Exception as e:
            report["themes_skipped"].append(f"{tname}: {e}")

    # 5) Restore Presenter tree custom variable.
    if restore_presenter and session.get("presenter_tree"):
        v = project.customVariables()
        v[TREE_VAR] = session["presenter_tree"]
        project.setCustomVariables(v)

    return report


# ── dialog ───────────────────────────────────────────────────────────────────

class SessionDialog(QDialog):
    def __init__(self, iface, plugin_version="?", parent=None):
        super().__init__(parent)
        self.iface = iface
        self.plugin_version = plugin_version
        self.setWindowTitle("Theme Session — Export / Import")
        self.resize(460, 260)

        lay = QVBoxLayout(self)
        info = QLabel(
            "Export a self-contained snapshot of every Map Theme,\n"
            "including the layer sources, their styles and the\n"
            "Theme Presenter grouping.  Keep the file safe: if the\n"
            "project is lost, import it into a fresh project to\n"
            "re-add the layers and rebuild the themes."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        row1 = QHBoxLayout()
        self.btn_export = QPushButton("💾  Export Session…")
        self.btn_export.setToolTip("Save all themes + layer references + styles to a .json file")
        self.btn_export.clicked.connect(self._on_export)
        row1.addWidget(self.btn_export)

        self.btn_import = QPushButton("📥  Import Session…")
        self.btn_import.setToolTip("Rebuild themes + re-add missing layers from a saved session file")
        self.btn_import.clicked.connect(self._on_import)
        row1.addWidget(self.btn_import)
        lay.addLayout(row1)

        self.chk_add_missing = QCheckBox("On import: re-add layers that aren't in the project yet")
        self.chk_add_missing.setChecked(True)
        lay.addWidget(self.chk_add_missing)

        self.chk_restore_tree = QCheckBox("On import: recreate the layer tree groups")
        self.chk_restore_tree.setChecked(True)
        lay.addWidget(self.chk_restore_tree)

        self.chk_restore_presenter = QCheckBox("On import: restore Theme Presenter grouping")
        self.chk_restore_presenter.setChecked(True)
        lay.addWidget(self.chk_restore_presenter)

        lay.addStretch(1)

        box = QDialogButtonBox()
        box.addButton("Close", QDialogButtonBox.RejectRole)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _on_export(self):
        project = QgsProject.instance()
        tc = project.mapThemeCollection()
        if not tc.mapThemes():
            QMessageBox.information(self, "No Themes",
                "This project has no map themes to export.")
            return
        default_name = "map_theme_session.json"
        try:
            base = os.path.splitext(os.path.basename(project.fileName()))[0]
            if base:
                default_name = f"{base}__theme_session.json"
        except Exception:
            pass
        start_dir = os.path.dirname(project.fileName()) or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Theme Session",
            os.path.join(start_dir, default_name),
            "Theme Session (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            session = build_session(project, self.plugin_version)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))
            return
        QMessageBox.information(
            self, "Session Exported",
            f"Wrote {len(session['themes'])} theme(s) and "
            f"{len(session['layers'])} layer reference(s) to:\n\n{path}"
        )

    def _on_import(self):
        start_dir = os.path.dirname(QgsProject.instance().fileName()) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Theme Session", start_dir,
            "Theme Session (*.json);;All files (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                session = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Failed",
                                 f"Could not read the session file:\n{e}")
            return
        if not isinstance(session, dict) or "themes" not in session:
            QMessageBox.critical(self, "Import Failed",
                                 "This file doesn't look like a theme session.")
            return
        n_themes = len(session.get("themes", {}))
        n_layers = len(session.get("layers", []))
        reply = QMessageBox.question(
            self, "Confirm Import",
            f"The session contains {n_themes} theme(s) and {n_layers} layer(s).\n\n"
            f"Existing themes with the same name will be overwritten.\n\n"
            f"Proceed?"
        )
        if reply != QMessageBox.Yes:
            return
        try:
            report = load_session(
                session,
                add_missing_layers=self.chk_add_missing.isChecked(),
                restore_tree=self.chk_restore_tree.isChecked(),
                restore_presenter=self.chk_restore_presenter.isChecked(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))
            return

        lines = [
            f"Themes rebuilt : {len(report['themes_created'])}",
            f"Layers added   : {len(report['layers_added'])}",
            f"Layers matched : {len(report['layers_matched'])}",
        ]
        if report["layers_failed"]:
            lines.append("")
            lines.append(f"⚠ {len(report['layers_failed'])} layer(s) could not be re-added:")
            for l in report["layers_failed"][:10]:
                lines.append(f"  • {l}")
            if len(report["layers_failed"]) > 10:
                lines.append(f"  … and {len(report['layers_failed']) - 10} more")
        if report["themes_skipped"]:
            lines.append("")
            lines.append("⚠ Some themes failed:")
            for t in report["themes_skipped"][:10]:
                lines.append(f"  • {t}")
        QMessageBox.information(self, "Session Imported", "\n".join(lines))
