# -*- coding: utf-8 -*-
"""
Sync Table — two-phase design:

PHASE 1 (Setup):
  • Browse to Excel/CSV
  • If no GeoPackage exists → offer to CREATE one from the file
  • If a GeoPackage layer exists → pick it and map the join key
  • Click "Connect" to establish the link

PHASE 2 (Connected):
  • A single "⚡ Sync Now" button appears
  • Click it any time to push updated data from Excel → GeoPackage
  • The connection persists for the session (re-open dialog = already connected)
"""

import os
import csv
import io

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QComboBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QFrame, QStackedWidget,
    QMessageBox, QProgressBar, QScrollArea, QWidget,
    QGroupBox, QLineEdit
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext
)
from .sync_state import CONNECTION


class SyncTableDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Sync Excel / CSV ↔ GeoPackage")
        self.setMinimumSize(640, 200)   # grows per phase

        # ── Persistent connection state ───────────────────────────────────────
        self._file_path     = None
        self._file_headers  = []
        self._file_rows     = []
        self._layer_id      = None   # connected layer id
        self._file_key_col  = None
        self._layer_key_fld = None
        self._cols_to_sync  = []     # column names to push

        # Restore from shared state if already connected
        self._connected     = CONNECTION.connected
        self._file_path     = CONNECTION.file_path
        self._layer_id      = CONNECTION.layer_id
        self._cols_to_sync  = CONNECTION.cols_to_sync
        self._file_key_col  = CONNECTION.file_key_col
        self._layer_key_fld = CONNECTION.layer_key_fld

        main = QVBoxLayout()

        # ════════════════════════════════════════════════════════════════════
        # PHASE 1 — Setup panel
        # ════════════════════════════════════════════════════════════════════
        self._setup_panel = QWidget()
        sp = QVBoxLayout(self._setup_panel)
        sp.setContentsMargins(0, 0, 0, 0)

        # Step 1: file
        grp1 = QGroupBox("Step 1 — Source File (Excel or CSV)")
        g1 = QHBoxLayout(grp1)
        self.file_label = QLabel("No file selected.")
        self.file_label.setStyleSheet("color:#666;")
        browse_btn = QPushButton("📂  Browse…")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_file)
        g1.addWidget(self.file_label, 1)
        g1.addWidget(browse_btn)
        sp.addWidget(grp1)

        # Step 2: GeoPackage — dynamic: shows CREATE or SELECT
        self._grp2 = QGroupBox("Step 2 — GeoPackage Layer")
        self._g2   = QVBoxLayout(self._grp2)

        # 2a — no gpkg found: warning label
        self._no_gpkg_label = QLabel("⚠  No GeoPackage layers found in the project.")
        self._no_gpkg_label.setStyleSheet("color:#856404;")
        self._g2.addWidget(self._no_gpkg_label)

        # 2b — gpkg exists: pick layer
        self._gpkg_select_widget = QWidget()
        sw = QVBoxLayout(self._gpkg_select_widget)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.addWidget(QLabel("Select the GeoPackage layer to sync into:"))
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        sw.addWidget(self.layer_combo)
        self._mode_label = QLabel("")
        self._mode_label.setStyleSheet("font-style:italic; color:#555; font-size:10px;")
        sw.addWidget(self._mode_label)
        self._g2.addWidget(self._gpkg_select_widget)

        # Always-visible create button (enabled once a file is loaded)
        self._create_gpkg_btn = QPushButton("🆕  Create new GeoPackage from this file…")
        self._create_gpkg_btn.setEnabled(False)
        self._create_gpkg_btn.setStyleSheet("color:#0d6efd; font-size:10px;")
        self._create_gpkg_btn.setFlat(True)
        self._create_gpkg_btn.clicked.connect(self._create_gpkg)
        self._g2.addWidget(self._create_gpkg_btn)

        sp.addWidget(self._grp2)

        # (Step 3 — Join Key removed: sync always deletes all features and re-inserts from file)

        # Step 4: columns
        grp4 = QGroupBox("Step 4 — Columns to Sync")
        g4 = QVBoxLayout(grp4)
        sel_row = QHBoxLayout()
        tick_all  = QPushButton("Tick All");  tick_all.setFixedWidth(75)
        tick_none = QPushButton("Untick All"); tick_none.setFixedWidth(75)
        tick_all.clicked.connect(lambda: [cb.setChecked(True)  for cb in self._col_checkboxes.values()])
        tick_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self._col_checkboxes.values()])
        sel_row.addWidget(tick_all); sel_row.addWidget(tick_none); sel_row.addStretch()
        g4.addLayout(sel_row)
        self.col_scroll = QScrollArea(); self.col_scroll.setWidgetResizable(True); self.col_scroll.setFixedHeight(70)
        self.col_widget = QWidget()
        self.col_layout = QHBoxLayout(self.col_widget); self.col_layout.setAlignment(Qt.AlignLeft)
        self.col_scroll.setWidget(self.col_widget)
        g4.addWidget(self.col_scroll)
        sp.addWidget(grp4)
        self._col_checkboxes = {}

        # Preview
        grp5 = QGroupBox("File Preview  (first 5 rows)")
        g5 = QVBoxLayout(grp5)
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setFixedHeight(110)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        g5.addWidget(self.preview_table)
        sp.addWidget(grp5)

        # Connect button
        self._connect_btn = QPushButton("🔗  Connect")
        self._connect_btn.setStyleSheet("font-weight:bold; font-size:13px; padding:6px;")
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)
        sp.addWidget(self._connect_btn)

        main.addWidget(self._setup_panel)

        # ════════════════════════════════════════════════════════════════════
        # PHASE 2 — Connected panel
        # ════════════════════════════════════════════════════════════════════
        self._connected_panel = QWidget()
        cp = QVBoxLayout(self._connected_panel)
        cp.setContentsMargins(0, 0, 0, 0)

        # Status banner
        self._conn_banner = QLabel("")
        self._conn_banner.setWordWrap(True)
        self._conn_banner.setStyleSheet(
            "background:#d4edda; color:#155724; border:1px solid #c3e6cb; "
            "border-radius:6px; padding:10px; font-size:11px;"
        )
        cp.addWidget(self._conn_banner)

        # Last sync info
        self._last_sync_label = QLabel("Not yet synced this session.")
        self._last_sync_label.setStyleSheet("color:#555; font-size:10px; padding:2px;")
        cp.addWidget(self._last_sync_label)

        # Big sync button
        self._sync_btn = QPushButton("⚡  Sync Now")
        self._sync_btn.setStyleSheet(
            "font-weight:bold; font-size:16px; padding:12px; "
            "background:#28a745; color:white; border-radius:6px;"
        )
        self._sync_btn.clicked.connect(self._on_sync)
        cp.addWidget(self._sync_btn)

        # Progress bar
        self._progress = QProgressBar(); self._progress.setValue(0); self._progress.setVisible(False)
        cp.addWidget(self._progress)

        # Reconfigure link
        reconfig_btn = QPushButton("⚙  Change connection…")
        reconfig_btn.setStyleSheet("color:#555; font-size:10px;")
        reconfig_btn.setFlat(True)
        reconfig_btn.clicked.connect(self._on_reconfigure)
        cp.addWidget(reconfig_btn, alignment=Qt.AlignRight)

        main.addWidget(self._connected_panel)

        # Close button (always shown)
        close_row = QHBoxLayout()
        close_btn = QPushButton("Close"); close_btn.clicked.connect(self.reject)
        close_row.addStretch(); close_row.addWidget(close_btn)
        main.addLayout(close_row)

        self.setLayout(main)

        # If already connected (dialog reopened), rebuild the banner from CONNECTION
        if self._connected and CONNECTION.connected:
            layer = QgsProject.instance().mapLayer(CONNECTION.layer_id or "")
            layer_name = CONNECTION.layer_name or "unknown"
            fname = os.path.basename(CONNECTION.file_path or "")
            self._conn_banner.setText(
                f"✅  <b>Connected</b><br>"
                f"<b>File:</b> {fname}<br>"
                f"<b>Layer:</b> {layer_name}<br>"
                f"<b>Columns:</b> {len(CONNECTION.cols_to_sync)} selected"
            )
            if CONNECTION.last_sync_msg:
                self._last_sync_label.setText(CONNECTION.last_sync_msg)
                self._last_sync_label.setStyleSheet("color:#155724; font-size:10px; padding:2px;")
            else:
                self._last_sync_label.setText("Connection restored — click ⚡ Sync Now to push latest data.")
                self._last_sync_label.setStyleSheet("color:#0d6efd; font-size:10px; padding:2px;")

        self._refresh_phase()
        self._refresh_gpkg_ui()

    # ── Phase switching ───────────────────────────────────────────────────────

    def _refresh_phase(self):
        self._setup_panel.setVisible(not self._connected)
        self._connected_panel.setVisible(self._connected)
        self.adjustSize()

    def _on_reconfigure(self):
        self._connected = False
        CONNECTION.disconnect()
        self._refresh_phase()

    # ── Layer list ────────────────────────────────────────────────────────────

    def _gpkg_layers(self):
        return [l for l in QgsProject.instance().mapLayers().values()
                if isinstance(l, QgsVectorLayer) and ".gpkg" in l.source().lower()]

    def _refresh_gpkg_ui(self):
        layers = self._gpkg_layers()
        has_gpkg = bool(layers)
        self._no_gpkg_label.setVisible(not has_gpkg)
        self._gpkg_select_widget.setVisible(has_gpkg)
        if has_gpkg:
            self.layer_combo.blockSignals(True)
            self.layer_combo.clear()
            for l in layers:
                self.layer_combo.addItem(l.name(), l.id())
            self.layer_combo.blockSignals(False)
            self._on_layer_changed()
        self._update_connect_btn()

    def _current_layer(self):
        lid = self.layer_combo.currentData() if self.layer_combo.count() else None
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _on_layer_changed(self):
        layer = self._current_layer()
        if not layer:
            self._mode_label.setText("")
            return
        n = layer.featureCount()
        if n == 0:
            self._mode_label.setText("Layer is empty — all file rows will be inserted on sync.")
            self._mode_label.setStyleSheet("color:#856404; font-style:italic; font-size:10px;")
        else:
            self._mode_label.setText(f"Layer has {n} feature(s) — all will be deleted and replaced with file rows on sync.")
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
        self._file_path = path
        self._file_headers = []; self._file_rows = []
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.xlsx', '.xls'):
                self._load_excel(path)
            else:
                self._load_csv(path)
        except PermissionError:
            QMessageBox.critical(self, "File Locked",
                f"Could not read:\n{path}\n\nFile locked by OS. Close any Excel dialogs and try again.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Read Error", f"Could not read file:\n{e}")
            return

        self.file_label.setText(
            f"{os.path.basename(path)}  —  {len(self._file_rows)} row(s), {len(self._file_headers)} col(s)")
        self.file_label.setStyleSheet("color:#155724;")

        self._refresh_col_checkboxes()
        self._refresh_preview()
        self._create_gpkg_btn.setEnabled(True)
        self._update_connect_btn()

    def _load_excel(self, path):
        import openpyxl
        with open(path, "rb") as f:
            data = f.read()
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            raise ValueError("Workbook is empty.")
        self._file_headers = [str(c).strip() if c is not None else f"col_{i}" for i, c in enumerate(rows[0])]
        all_rows = [{self._file_headers[i]: (row[i] if i < len(row) else None)
                     for i in range(len(self._file_headers))} for row in rows[1:]]
        # Drop fully blank rows (all values None or empty string) — avoids inserting
        # phantom features that cause Atlas to generate empty/blank figures
        self._file_rows = [
            r for r in all_rows
            if any(v is not None and str(v).strip() != "" for v in r.values())
        ]

    def _load_csv(self, path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            self._file_headers = [h.strip() for h in (reader.fieldnames or [])]
            all_rows = [{k.strip(): v for k, v in row.items()} for row in reader]
        # Drop fully blank rows
        self._file_rows = [
            r for r in all_rows
            if any(v is not None and str(v).strip() != "" for v in r.values())
        ]

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _refresh_col_checkboxes(self):
        for cb in self._col_checkboxes.values():
            cb.setParent(None)
        self._col_checkboxes = {}
        while self.col_layout.count():
            item = self.col_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for col in self._file_headers:
            cb = QCheckBox(col); cb.setChecked(True)
            self._col_checkboxes[col] = cb
            self.col_layout.addWidget(cb)

    def _refresh_preview(self):
        if not self._file_headers: return
        n = min(5, len(self._file_rows))
        self.preview_table.setRowCount(n)
        self.preview_table.setColumnCount(len(self._file_headers))
        self.preview_table.setHorizontalHeaderLabels(self._file_headers)
        for r in range(n):
            for c, h in enumerate(self._file_headers):
                val = self._file_rows[r].get(h, "")
                self.preview_table.setItem(r, c, QTableWidgetItem(str(val) if val is not None else ""))

    def _update_connect_btn(self):
        has_file  = bool(self._file_rows)
        has_layer = bool(self._gpkg_layers())
        self._connect_btn.setEnabled(has_file and has_layer)

    # ── Create GeoPackage ─────────────────────────────────────────────────────

    def _create_gpkg(self):
        if not self._file_rows:
            QMessageBox.warning(self, "No File", "Browse to a file first."); return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save new GeoPackage as…", "",
            "GeoPackage (*.gpkg)"
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".gpkg"):
            save_path += ".gpkg"

        layer_name = os.path.splitext(os.path.basename(save_path))[0]

        try:
            from qgis.PyQt.QtCore import QVariant

            # Build fields from file headers
            fields_list = []
            for h in self._file_headers:
                fields_list.append(QgsField(h, QVariant.String))

            # Create an in-memory layer, write to gpkg
            from qgis.core import QgsFields, QgsWkbTypes
            qgs_fields = QgsFields()
            for f in fields_list:
                qgs_fields.append(f)

            # Write empty gpkg with these fields (no geometry)
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName  = layer_name
            options.fileEncoding = "UTF-8"

            tmp_layer = QgsVectorLayer("None", layer_name, "memory")
            tmp_layer.dataProvider().addAttributes(fields_list)
            tmp_layer.updateFields()

            error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                tmp_layer, save_path,
                QgsCoordinateTransformContext(), options
            )
            if error != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Write failed: {msg}")

            # Load the new layer into QGIS
            new_layer = QgsVectorLayer(f"{save_path}|layername={layer_name}", layer_name, "ogr")
            if not new_layer.isValid():
                raise RuntimeError("Created GeoPackage layer is not valid.")
            QgsProject.instance().addMapLayer(new_layer)

        except Exception as e:
            QMessageBox.critical(self, "Create Error", f"Could not create GeoPackage:\n{e}")
            return

        QMessageBox.information(self, "Created",
            f"GeoPackage created and added to project:\n{save_path}\n\n"
            "The layer is empty — click Connect to insert all file rows.")
        self._refresh_gpkg_ui()

    # ── Connect ───────────────────────────────────────────────────────────────

    def _on_connect(self):
        if not self._file_rows:
            QMessageBox.warning(self, "No File", "Browse to a file first."); return
        layer = self._current_layer()
        if not layer:
            QMessageBox.warning(self, "No Layer", "No GeoPackage layer selected."); return

        cols = [col for col, cb in self._col_checkboxes.items() if cb.isChecked()]
        if not cols:
            QMessageBox.warning(self, "No Columns", "Tick at least one column."); return

        # Write to shared connection state (toolbar button will go green)
        CONNECTION.connect(
            file_path      = self._file_path,
            layer_id       = layer.id(),
            layer_name     = layer.name(),
            cols_to_sync   = cols,
            file_key_col   = None,
            layer_key_fld  = None,
        )

        # Mirror into local attrs
        self._layer_id      = layer.id()
        self._cols_to_sync  = cols
        self._file_key_col  = None
        self._layer_key_fld = None

        self._conn_banner.setText(
            f"✅  <b>Connected</b><br>"
            f"<b>File:</b> {os.path.basename(self._file_path)}<br>"
            f"<b>Layer:</b> {layer.name()}<br>"
            f"<b>Columns:</b> {len(cols)} selected"
        )

        self._connected = True
        self._refresh_phase()

    # ── Sync ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_val(val):
        """Convert a file cell value to a safe string for GeoPackage.
        Returns None (SQL NULL) for empty/blank cells instead of empty string,
        which prevents type-mismatch errors on numeric fields."""
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    def _on_sync(self):
        # Re-read the file fresh every time (picks up any edits made in Excel)
        try:
            ext = os.path.splitext(self._file_path)[1].lower()
            if ext in ('.xlsx', '.xls'):
                self._load_excel(self._file_path)
            else:
                self._load_csv(self._file_path)
        except PermissionError:
            QMessageBox.critical(self, "File Locked",
                "Could not read the file — it is fully locked.\n"
                "Close any Save dialogs in Excel and try again.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Read Error", f"Could not read file:\n{e}")
            return

        layer = QgsProject.instance().mapLayer(self._layer_id)
        if not layer:
            QMessageBox.critical(self, "Layer Gone",
                "The connected GeoPackage layer no longer exists in the project.\n"
                "Click 'Change connection' to reconnect.")
            return

        # Use current file headers as the definitive column list — this means
        # added columns are picked up and removed columns are dropped automatically,
        # even across sessions where in-memory state may have been reset.
        SYSTEM_FIELDS = {'fid', 'ogc_fid'}
        cols = list(self._file_headers)
        self._cols_to_sync = cols
        CONNECTION.cols_to_sync = cols

        layer_field_names = [f.name() for f in layer.fields()]

        # Fields in the layer that are no longer in the file → drop them
        fields_to_drop = [
            f for f in layer_field_names
            if f.lower() not in {s.lower() for s in SYSTEM_FIELDS}
            and f not in cols
        ]
        # Fields in the file not yet in the layer → add them
        new_fields = [c for c in cols if c not in layer_field_names]

        self._progress.setVisible(True)
        inserted = 0

        from qgis.PyQt.QtCore import QVariant

        if not layer.startEditing():
            QMessageBox.critical(self, "Sync Error",
                f"Could not start editing layer '{layer.name()}'.\n"
                "Make sure the layer is not read-only and the GeoPackage file is writable.")
            self._progress.setVisible(False)
            return

        try:
            # Drop removed columns (iterate in reverse index order to keep indices stable)
            if fields_to_drop:
                for col in fields_to_drop:
                    idx = layer.fields().indexFromName(col)
                    if idx >= 0 and not layer.deleteAttribute(idx):
                        raise RuntimeError(f"Failed to delete field '{col}' from layer.")
                layer.updateFields()
                layer_field_names = [f.name() for f in layer.fields()]

            # Add new columns from the file
            if new_fields:
                for col in new_fields:
                    if not layer.addAttribute(QgsField(col, QVariant.String)):
                        raise RuntimeError(f"Failed to add field '{col}' to layer.")
                layer.updateFields()
                layer_field_names = [f.name() for f in layer.fields()]

            # Delete all existing features
            all_fids = [f.id() for f in layer.getFeatures()]
            if all_fids:
                layer.deleteFeatures(all_fids)

            # Insert all rows from file
            self._progress.setMaximum(len(self._file_rows))
            for i, row in enumerate(self._file_rows):
                feat = QgsFeature(layer.fields())
                for col in cols:
                    if col in layer_field_names:
                        feat[col] = self._safe_val(row.get(col))
                layer.addFeature(feat)
                inserted += 1
                self._progress.setValue(i + 1)

        except Exception as e:
            try:
                layer.rollBack()
            except Exception:
                pass
            QMessageBox.critical(self, "Sync Error",
                f"Error during sync — all changes rolled back.\n\n{e}")
            self._progress.setVisible(False)
            return

        # Commit.
        # QGIS's commitChanges() sometimes returns False even when the write
        # succeeded, putting only "SUCCESS: N feature(s) added" into commitErrors().
        # We treat it as a real failure ONLY if there are non-SUCCESS error strings.
        committed = layer.commitChanges()
        if not committed:
            errs = [e for e in layer.commitErrors()
                    if not e.upper().startswith("SUCCESS")]
            if errs:
                layer.rollBack()
                QMessageBox.critical(self, "Commit Error",
                    f"Changes could not be saved to the GeoPackage:\n\n" + "\n".join(errs))
                self._progress.setVisible(False)
                return

        self._progress.setVisible(False)
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()

        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        result = f"inserted {inserted}" if inserted else "no changes"

        sync_msg = f"Last sync: {ts}  —  {result} feature(s)"
        self._last_sync_label.setText(sync_msg)
        self._last_sync_label.setStyleSheet("color:#155724; font-size:10px; padding:2px;")
        CONNECTION.last_sync_msg = sync_msg   # persist across dialog reopen
