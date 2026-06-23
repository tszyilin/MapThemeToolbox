# -*- coding: utf-8 -*-
"""
Sync Table — multiple named Excel/CSV ↔ GeoPackage connections.
QGIS 4 / PyQt6 version.

Key QGIS 4 changes vs the QGIS 3 version:
  • QVariant.String  →  QMetaType.Type.QString
  • QgsVectorFileWriter.NoError  →  QgsVectorFileWriter.VectorWriterResult.NoError
  • All Qt enum scoping (Qt.AlignLeft → Qt.AlignmentFlag.AlignLeft, etc.)
  • exec_() → exec()

Layout:
  ┌──────────────┬──────────────────────────────────────────┐
  │ Connections  │  <per-connection setup or connected UI>  │
  │  ✅ Figures  │                                          │
  │     Inset    │                                          │
  │  [+] [✏] [×] │                                          │
  ├──────────────┴──────────────────────────────────────────┤
  │  [⚡ Sync All Connected]                    [Close]     │
  └─────────────────────────────────────────────────────────┘

Each row in the list maps to a ConnectionPanel on the right.
The sync logic lives in perform_sync() which is also called by Quick Sync.
"""

import os
import csv
import io

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QComboBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QFrame, QStackedWidget,
    QMessageBox, QProgressBar, QScrollArea, QWidget,
    QGroupBox, QLineEdit, QListWidget, QListWidgetItem,
    QInputDialog
)
from qgis.PyQt.QtCore import Qt, QMetaType
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext, QgsFields, QgsWkbTypes
)
from .sync_state import REGISTRY, SyncConnection


# ── Standalone file-reading helpers ──────────────────────────────────────────

def _load_excel(path):
    """Return (headers, rows). Rows are list of dicts. Blank rows filtered out."""
    import openpyxl
    with open(path, "rb") as f:
        data = f.read()
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        raise ValueError("Workbook is empty.")
    headers = [str(c).strip() if c is not None else f"col_{i}"
               for i, c in enumerate(rows[0])]
    all_rows = [{headers[i]: (row[i] if i < len(row) else None)
                 for i in range(len(headers))} for row in rows[1:]]
    data_rows = [r for r in all_rows
                 if any(v is not None and str(v).strip() != "" for v in r.values())]
    return headers, data_rows


def _load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        all_rows = [{k.strip(): v for k, v in row.items()} for row in reader]
    data_rows = [r for r in all_rows
                 if any(v is not None and str(v).strip() != "" for v in r.values())]
    return headers, data_rows


def _read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xls'):
        return _load_excel(path)
    return _load_csv(path)


def _safe_val(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


# ── Core sync logic (called by dialog AND Quick Sync toolbar) ─────────────────

def perform_sync(conn, iface, progress_cb=None):
    """
    Sync a single SyncConnection: re-read file, reconcile GPKG columns,
    delete all features, insert all from file.

    progress_cb(current, total) — optional callback for progress updates.
    Returns (success: bool, message: str).
    """
    if not conn.file_path:
        return False, "No file path set."

    # Re-read file fresh
    try:
        headers, rows = _read_file(conn.file_path)
    except PermissionError:
        return False, "File is locked — close it in Excel first."
    except Exception as e:
        return False, f"Could not read file: {e}"

    layer = QgsProject.instance().mapLayer(conn.layer_id or "")
    if not layer:
        conn.connected = False
        REGISTRY.update(conn)
        return False, f"Layer '{conn.layer_name}' not found — reconnect."

    SYSTEM_FIELDS = {'fid', 'ogc_fid'}
    cols = list(headers)
    conn.cols_to_sync = cols

    layer_field_names = [f.name() for f in layer.fields()]
    fields_to_drop = [
        f for f in layer_field_names
        if f.lower() not in {s.lower() for s in SYSTEM_FIELDS}
        and f not in cols
    ]
    new_fields = [c for c in cols if c not in layer_field_names]

    if not layer.startEditing():
        return False, f"Could not start editing '{layer.name()}' — read-only?"

    try:
        if fields_to_drop:
            for col in fields_to_drop:
                idx = layer.fields().indexFromName(col)
                if idx >= 0 and not layer.deleteAttribute(idx):
                    raise RuntimeError(f"Failed to delete field '{col}'.")
            layer.updateFields()
            layer_field_names = [f.name() for f in layer.fields()]

        if new_fields:
            for col in new_fields:
                if not layer.addAttribute(QgsField(col, QMetaType.Type.QString)):
                    raise RuntimeError(f"Failed to add field '{col}'.")
            layer.updateFields()
            layer_field_names = [f.name() for f in layer.fields()]

        all_fids = [f.id() for f in layer.getFeatures()]
        if all_fids:
            layer.deleteFeatures(all_fids)

        total = len(rows)
        for i, row in enumerate(rows):
            feat = QgsFeature(layer.fields())
            for col in cols:
                if col in layer_field_names:
                    feat[col] = _safe_val(row.get(col))
            layer.addFeature(feat)
            if progress_cb:
                progress_cb(i + 1, total)

    except Exception as e:
        try:
            layer.rollBack()
        except Exception:
            pass
        return False, f"Sync error (rolled back): {e}"

    committed = layer.commitChanges()
    if not committed:
        errs = [e for e in layer.commitErrors()
                if not e.upper().startswith("SUCCESS")]
        if errs:
            layer.rollBack()
            return False, "Commit failed: " + "; ".join(errs)

    layer.triggerRepaint()
    try:
        iface.mapCanvas().refresh()
    except Exception:
        pass

    from datetime import datetime
    ts  = datetime.now().strftime("%H:%M:%S")
    msg = f"Last sync: {ts}  —  {len(rows)} row(s) inserted"
    conn.last_sync_msg = msg
    REGISTRY.update(conn)
    return True, msg


# ── Per-connection panel ──────────────────────────────────────────────────────

class ConnectionPanel(QWidget):
    """
    Setup + Connected UI for a single SyncConnection.
    Embedded in a QStackedWidget inside SyncTableDialog.
    """

    def __init__(self, conn, iface, parent=None):
        super().__init__(parent)
        self._conn        = conn
        self._iface       = iface
        self._file_path   = conn.file_path
        self._file_headers = []
        self._file_rows   = []
        self._col_checkboxes = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ════════════════════════════════════════════════════════════════
        # PHASE 1 — Setup
        # ════════════════════════════════════════════════════════════════
        self._setup_panel = QWidget()
        sp = QVBoxLayout(self._setup_panel)
        sp.setContentsMargins(0, 0, 0, 0)
        sp.setSpacing(6)

        # Step 1: file
        grp1 = QGroupBox("Step 1 — Source File (Excel or CSV)")
        g1 = QHBoxLayout(grp1)
        self._file_label = QLabel("No file selected.")
        self._file_label.setStyleSheet("color:#666;")
        browse_btn = QPushButton("📂  Browse…")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_file)
        g1.addWidget(self._file_label, 1)
        g1.addWidget(browse_btn)
        sp.addWidget(grp1)

        # Step 2: GeoPackage
        self._grp2 = QGroupBox("Step 2 — GeoPackage Layer")
        g2 = QVBoxLayout(self._grp2)

        self._no_gpkg_label = QLabel("⚠  No GeoPackage layers found in the project.")
        self._no_gpkg_label.setStyleSheet("color:#856404;")
        g2.addWidget(self._no_gpkg_label)

        self._gpkg_select = QWidget()
        sw = QVBoxLayout(self._gpkg_select)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.addWidget(QLabel("Select the GeoPackage layer to sync into:"))
        self._layer_combo = QComboBox()
        self._layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        sw.addWidget(self._layer_combo)
        self._mode_label = QLabel("")
        self._mode_label.setStyleSheet("font-style:italic; color:#555; font-size:10px;")
        sw.addWidget(self._mode_label)
        g2.addWidget(self._gpkg_select)

        self._create_gpkg_btn = QPushButton("🆕  Create new GeoPackage from this file…")
        self._create_gpkg_btn.setEnabled(False)
        self._create_gpkg_btn.setStyleSheet("color:#0d6efd; font-size:10px;")
        self._create_gpkg_btn.setFlat(True)
        self._create_gpkg_btn.clicked.connect(self._create_gpkg)
        g2.addWidget(self._create_gpkg_btn)
        sp.addWidget(self._grp2)

        # Step 3: columns
        grp4 = QGroupBox("Step 3 — Columns to Sync")
        g4 = QVBoxLayout(grp4)
        sel_row = QHBoxLayout()
        tick_all  = QPushButton("Tick All");   tick_all.setFixedWidth(75)
        tick_none = QPushButton("Untick All"); tick_none.setFixedWidth(75)
        tick_all.clicked.connect(lambda: [cb.setChecked(True)  for cb in self._col_checkboxes.values()])
        tick_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self._col_checkboxes.values()])
        sel_row.addWidget(tick_all); sel_row.addWidget(tick_none); sel_row.addStretch()
        g4.addLayout(sel_row)
        self._col_scroll = QScrollArea()
        self._col_scroll.setWidgetResizable(True)
        self._col_scroll.setFixedHeight(70)
        self._col_widget = QWidget()
        self._col_layout = QHBoxLayout(self._col_widget)
        self._col_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._col_scroll.setWidget(self._col_widget)
        g4.addWidget(self._col_scroll)
        sp.addWidget(grp4)

        # Preview
        grp5 = QGroupBox("File Preview  (first 5 rows)")
        g5 = QVBoxLayout(grp5)
        self._preview = QTableWidget(0, 0)
        self._preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._preview.setFixedHeight(110)
        self._preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        g5.addWidget(self._preview)
        sp.addWidget(grp5)

        # Connect button
        self._connect_btn = QPushButton("🔗  Connect")
        self._connect_btn.setStyleSheet("font-weight:bold; font-size:13px; padding:6px;")
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)
        sp.addWidget(self._connect_btn)

        layout.addWidget(self._setup_panel)

        # ════════════════════════════════════════════════════════════════
        # PHASE 2 — Connected
        # ════════════════════════════════════════════════════════════════
        self._connected_panel = QWidget()
        cp = QVBoxLayout(self._connected_panel)
        cp.setContentsMargins(0, 0, 0, 0)
        cp.setSpacing(6)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            "background:#d4edda; color:#155724; border:1px solid #c3e6cb; "
            "border-radius:6px; padding:10px; font-size:11px;"
        )
        cp.addWidget(self._banner)

        self._last_sync_label = QLabel("Not yet synced this session.")
        self._last_sync_label.setStyleSheet("color:#555; font-size:10px; padding:2px;")
        cp.addWidget(self._last_sync_label)

        self._sync_btn = QPushButton("⚡  Sync Now")
        self._sync_btn.setStyleSheet(
            "font-weight:bold; font-size:15px; padding:10px; "
            "background:#28a745; color:white; border-radius:6px;"
        )
        self._sync_btn.clicked.connect(self._on_sync)
        cp.addWidget(self._sync_btn)

        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._progress.setVisible(False)
        cp.addWidget(self._progress)

        reconfig_btn = QPushButton("⚙  Change connection…")
        reconfig_btn.setStyleSheet("color:#555; font-size:10px;")
        reconfig_btn.setFlat(True)
        reconfig_btn.clicked.connect(self._on_reconfigure)
        cp.addWidget(reconfig_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self._connected_panel)
        layout.addStretch()

        # ── Init ─────────────────────────────────────────────────────────────
        if conn.connected:
            layer = QgsProject.instance().mapLayer(conn.layer_id or "")
            if layer:
                self._rebuild_banner()
                if conn.last_sync_msg:
                    self._last_sync_label.setText(conn.last_sync_msg)
                    self._last_sync_label.setStyleSheet(
                        "color:#155724; font-size:10px; padding:2px;")
                else:
                    self._last_sync_label.setText(
                        "Connection restored — click ⚡ Sync Now to push latest data.")
                    self._last_sync_label.setStyleSheet(
                        "color:#0d6efd; font-size:10px; padding:2px;")
            else:
                conn.connected = False
                REGISTRY.update(conn)

        if conn.file_path:
            try:
                self._file_headers, self._file_rows = _read_file(conn.file_path)
                self._file_label.setText(
                    f"{os.path.basename(conn.file_path)}  —  "
                    f"{len(self._file_rows)} row(s), {len(self._file_headers)} col(s)")
                self._file_label.setStyleSheet("color:#155724;")
                self._refresh_col_checkboxes()
                self._refresh_preview()
                self._create_gpkg_btn.setEnabled(True)
            except Exception:
                pass

        self._refresh_phase()
        self._refresh_gpkg_ui()

    # ── Phase ─────────────────────────────────────────────────────────────────

    def _refresh_phase(self):
        self._setup_panel.setVisible(not self._conn.connected)
        self._connected_panel.setVisible(self._conn.connected)

    def _rebuild_banner(self):
        fname = os.path.basename(self._conn.file_path or "")
        self._banner.setText(
            f"✅  <b>Connected</b><br>"
            f"<b>File:</b> {fname}<br>"
            f"<b>Layer:</b> {self._conn.layer_name}<br>"
            f"<b>Columns:</b> {len(self._conn.cols_to_sync)} selected"
        )

    def _on_reconfigure(self):
        self._conn.connected = False
        REGISTRY.update(self._conn)
        self._refresh_phase()

    # ── GPKG helpers ──────────────────────────────────────────────────────────

    def _gpkg_layers(self):
        return [l for l in QgsProject.instance().mapLayers().values()
                if isinstance(l, QgsVectorLayer) and ".gpkg" in l.source().lower()]

    def _refresh_gpkg_ui(self):
        layers = self._gpkg_layers()
        has_gpkg = bool(layers)
        self._no_gpkg_label.setVisible(not has_gpkg)
        self._gpkg_select.setVisible(has_gpkg)
        if has_gpkg:
            self._layer_combo.blockSignals(True)
            self._layer_combo.clear()
            for l in layers:
                self._layer_combo.addItem(l.name(), l.id())
            if self._conn.layer_id:
                for i in range(self._layer_combo.count()):
                    if self._layer_combo.itemData(i) == self._conn.layer_id:
                        self._layer_combo.setCurrentIndex(i)
                        break
            self._layer_combo.blockSignals(False)
            self._on_layer_changed()
        self._update_connect_btn()

    def _current_layer(self):
        lid = self._layer_combo.currentData() if self._layer_combo.count() else None
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _on_layer_changed(self):
        layer = self._current_layer()
        if not layer:
            self._mode_label.setText("")
            return
        n = layer.featureCount()
        if n == 0:
            self._mode_label.setText("Layer is empty — all rows will be inserted on sync.")
            self._mode_label.setStyleSheet("color:#856404; font-style:italic; font-size:10px;")
        else:
            self._mode_label.setText(
                f"Layer has {n} feature(s) — all will be replaced on sync.")
            self._mode_label.setStyleSheet("color:#155724; font-style:italic; font-size:10px;")
        self._update_connect_btn()

    # ── File loading ──────────────────────────────────────────────────────────

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel or CSV", "",
            "Excel / CSV (*.xlsx *.xls *.csv *.txt)"
        )
        if not path:
            return
        try:
            self._file_headers, self._file_rows = _read_file(path)
        except PermissionError:
            QMessageBox.critical(self, "File Locked",
                f"Could not read:\n{path}\n\nFile locked — close Excel and try again.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Read Error", f"Could not read file:\n{e}")
            return
        self._file_path = path
        self._conn.file_path = path
        REGISTRY.update(self._conn)
        self._file_label.setText(
            f"{os.path.basename(path)}  —  "
            f"{len(self._file_rows)} row(s), {len(self._file_headers)} col(s)")
        self._file_label.setStyleSheet("color:#155724;")
        self._refresh_col_checkboxes()
        self._refresh_preview()
        self._create_gpkg_btn.setEnabled(True)
        self._update_connect_btn()

    # ── Column checkboxes / preview ───────────────────────────────────────────

    def _refresh_col_checkboxes(self):
        while self._col_layout.count():
            item = self._col_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._col_checkboxes = {}
        for col in self._file_headers:
            cb = QCheckBox(col)
            cb.setChecked(True)
            self._col_checkboxes[col] = cb
            self._col_layout.addWidget(cb)

    def _refresh_preview(self):
        if not self._file_headers:
            return
        n = min(5, len(self._file_rows))
        self._preview.setRowCount(n)
        self._preview.setColumnCount(len(self._file_headers))
        self._preview.setHorizontalHeaderLabels(self._file_headers)
        for r in range(n):
            for c, h in enumerate(self._file_headers):
                val = self._file_rows[r].get(h, "")
                self._preview.setItem(r, c, QTableWidgetItem(
                    str(val) if val is not None else ""))

    def _update_connect_btn(self):
        self._connect_btn.setEnabled(
            bool(self._file_rows) and bool(self._gpkg_layers()))

    # ── Create GPKG ───────────────────────────────────────────────────────────

    def _create_gpkg(self):
        if not self._file_rows:
            QMessageBox.warning(self, "No File", "Browse to a file first.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save new GeoPackage as…", "", "GeoPackage (*.gpkg)")
        if not save_path:
            return
        if not save_path.lower().endswith(".gpkg"):
            save_path += ".gpkg"
        layer_name = os.path.splitext(os.path.basename(save_path))[0]
        try:
            fields_list = [QgsField(h, QMetaType.Type.QString) for h in self._file_headers]
            qgs_fields  = QgsFields()
            for f in fields_list:
                qgs_fields.append(f)
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName   = "GPKG"
            options.layerName    = layer_name
            options.fileEncoding = "UTF-8"
            tmp = QgsVectorLayer("None", layer_name, "memory")
            tmp.dataProvider().addAttributes(fields_list)
            tmp.updateFields()
            error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                tmp, save_path, QgsCoordinateTransformContext(), options)
            if error != QgsVectorFileWriter.VectorWriterResult.NoError:
                raise RuntimeError(f"Write failed: {msg}")
            new_layer = QgsVectorLayer(
                f"{save_path}|layername={layer_name}", layer_name, "ogr")
            if not new_layer.isValid():
                raise RuntimeError("Created layer is not valid.")
            QgsProject.instance().addMapLayer(new_layer)
        except Exception as e:
            QMessageBox.critical(self, "Create Error",
                f"Could not create GeoPackage:\n{e}")
            return
        QMessageBox.information(self, "Created",
            f"GeoPackage created and added to project:\n{save_path}\n\n"
            "The layer is empty — click Connect to insert all file rows.")
        self._refresh_gpkg_ui()

    # ── Connect ───────────────────────────────────────────────────────────────

    def _on_connect(self):
        if not self._file_rows:
            QMessageBox.warning(self, "No File", "Browse to a file first.")
            return
        layer = self._current_layer()
        if not layer:
            QMessageBox.warning(self, "No Layer", "No GeoPackage layer selected.")
            return
        cols = [col for col, cb in self._col_checkboxes.items() if cb.isChecked()]
        if not cols:
            QMessageBox.warning(self, "No Columns", "Tick at least one column.")
            return

        self._conn.connected    = True
        self._conn.layer_id     = layer.id()
        self._conn.layer_name   = layer.name()
        self._conn.cols_to_sync = cols
        REGISTRY.update(self._conn)

        self._rebuild_banner()
        self._last_sync_label.setText(
            "Connected — click ⚡ Sync Now to push data.")
        self._last_sync_label.setStyleSheet("color:#0d6efd; font-size:10px; padding:2px;")
        self._refresh_phase()

    # ── Sync ──────────────────────────────────────────────────────────────────

    def _on_sync(self):
        self._progress.setVisible(True)
        self._progress.setValue(0)

        def _progress_cb(current, total):
            self._progress.setMaximum(total)
            self._progress.setValue(current)

        success, msg = perform_sync(self._conn, self._iface, _progress_cb)
        self._progress.setVisible(False)

        if success:
            self._last_sync_label.setText(msg)
            self._last_sync_label.setStyleSheet(
                "color:#155724; font-size:10px; padding:2px;")
        else:
            QMessageBox.critical(self, "Sync Error", msg)


# ── Main dialog ───────────────────────────────────────────────────────────────

class SyncTableDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Sync Excel / CSV ↔ GeoPackage")
        self.setMinimumSize(760, 520)
        self.resize(820, 560)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── Splitter: connections list (left) + panel (right) ─────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left: connection list ─────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(170)
        left.setMaximumWidth(230)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)
        lv.setSpacing(4)

        lv.addWidget(QLabel("<b>Connections</b>"))

        self._list = QListWidget()
        self._list.setSpacing(1)
        self._list.currentRowChanged.connect(self._on_row_changed)
        lv.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_add    = QPushButton("+")
        self._btn_rename = QPushButton("✏")
        self._btn_del    = QPushButton("×")
        for b in (self._btn_add, self._btn_rename, self._btn_del):
            b.setFixedWidth(32)
            b.setFixedHeight(26)
        self._btn_add.setToolTip("Add a new connection")
        self._btn_rename.setToolTip("Rename selected connection")
        self._btn_del.setToolTip("Remove selected connection")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_rename)
        btn_row.addWidget(self._btn_del)
        btn_row.addStretch()
        lv.addLayout(btn_row)

        splitter.addWidget(left)

        # ── Right: stacked connection panels ──────────────────────────────────
        self._stack  = QStackedWidget()
        self._panels = []   # list of ConnectionPanel, parallel to REGISTRY.connections()

        empty_lbl = QLabel("← Add a connection to get started.")
        empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lbl.setStyleSheet("color:#999;")
        self._empty_widget = empty_lbl
        self._stack.addWidget(self._empty_widget)

        splitter.addWidget(self._stack)
        splitter.setSizes([180, 620])

        main_layout.addWidget(splitter, 1)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bottom = QHBoxLayout()
        self._sync_all_btn = QPushButton("⚡  Sync All Connected")
        self._sync_all_btn.setStyleSheet(
            "font-weight:bold; padding:6px 14px; "
            "background:#28a745; color:white; border-radius:5px;")
        self._sync_all_btn.setToolTip("Sync every connected connection in sequence")
        self._sync_all_btn.clicked.connect(self._on_sync_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(self._sync_all_btn)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        main_layout.addLayout(bottom)

        # Populate list from REGISTRY
        self._rebuild_list()

        # Subscribe to registry changes so the list stays in sync
        REGISTRY.register_callback(self._on_registry_changed)

    def closeEvent(self, event):
        REGISTRY.unregister_callback(self._on_registry_changed)
        super().closeEvent(event)

    # ── List management ───────────────────────────────────────────────────────

    def _rebuild_list(self):
        """Rebuild list widget and panels stack from REGISTRY."""
        self._list.blockSignals(True)
        current_row = self._list.currentRow()
        self._list.clear()

        # Remove old panels from stack (keep the empty widget at index 0)
        while self._stack.count() > 1:
            w = self._stack.widget(1)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._panels = []

        for conn in REGISTRY.connections():
            item = QListWidgetItem(self._item_label(conn))
            item.setData(Qt.ItemDataRole.UserRole, id(conn))
            self._list.addItem(item)

            panel = ConnectionPanel(conn, self.iface, parent=self._stack)
            self._stack.addWidget(panel)
            self._panels.append(panel)

        self._list.blockSignals(False)

        count = len(self._panels)
        if count == 0:
            self._stack.setCurrentWidget(self._empty_widget)
        else:
            row = max(0, min(current_row, count - 1))
            self._list.setCurrentRow(row)
            self._stack.setCurrentIndex(row + 1)  # +1 because empty widget is at 0

        self._update_sync_all_btn()

    def _item_label(self, conn):
        prefix = "✅  " if conn.connected else "      "
        return f"{prefix}{conn.name}"

    def _refresh_list_labels(self):
        """Refresh labels without rebuilding panels."""
        for i, conn in enumerate(REGISTRY.connections()):
            item = self._list.item(i)
            if item:
                item.setText(self._item_label(conn))
        self._update_sync_all_btn()

    def _on_row_changed(self, row):
        if row < 0 or row >= len(self._panels):
            self._stack.setCurrentWidget(self._empty_widget)
        else:
            self._stack.setCurrentIndex(row + 1)

    def _update_sync_all_btn(self):
        self._sync_all_btn.setEnabled(REGISTRY.any_connected())

    def _on_registry_changed(self):
        self._refresh_list_labels()

    # ── Add / Rename / Delete ─────────────────────────────────────────────────

    def _on_add(self):
        name, ok = QInputDialog.getText(
            self, "New Connection", "Connection name:",
            text=f"Connection {len(REGISTRY.connections()) + 1}"
        )
        name = name.strip()
        if not ok or not name:
            return
        REGISTRY.add(name)
        self._rebuild_list()
        last = self._list.count() - 1
        self._list.setCurrentRow(last)

    def _on_rename(self):
        row = self._list.currentRow()
        conns = REGISTRY.connections()
        if row < 0 or row >= len(conns):
            return
        conn = conns[row]
        name, ok = QInputDialog.getText(
            self, "Rename Connection", "New name:", text=conn.name)
        name = name.strip()
        if not ok or not name or name == conn.name:
            return
        conn.name = name
        REGISTRY.update(conn)
        self._list.currentItem().setText(self._item_label(conn))

    def _on_delete(self):
        row = self._list.currentRow()
        conns = REGISTRY.connections()
        if row < 0 or row >= len(conns):
            return
        conn = conns[row]
        reply = QMessageBox.question(
            self, "Remove Connection",
            f"Remove connection <b>{conn.name}</b>?<br>"
            "This only removes the link — it does not delete any files or layers.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        REGISTRY.remove(conn)
        self._rebuild_list()

    # ── Sync All ──────────────────────────────────────────────────────────────

    def _on_sync_all(self):
        connected = REGISTRY.connected_list()
        if not connected:
            QMessageBox.information(self, "Nothing Connected",
                                    "No connections are currently set up.")
            return
        results = []
        for conn in connected:
            success, msg = perform_sync(conn, self.iface)
            results.append(f"<b>{conn.name}</b>: {'✅' if success else '❌'} {msg}")

        self._refresh_list_labels()

        QMessageBox.information(
            self, "Sync All — Results",
            "<br>".join(results)
        )
