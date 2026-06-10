import os
import traceback

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QSizePolicy, QComboBox, QFrame,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsMapLayerProxyModel, QgsFieldProxyModel, QgsWkbTypes
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox


class _LayerFieldRow(QHBoxLayout):
    """Layer selector + one or more field selectors in a row."""

    def __init__(self, layer_filter, parent=None):
        super().__init__()
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(layer_filter)
        self.layer_combo.setAllowEmptyLayer(True)
        self.layer_combo.setCurrentIndex(0)
        self.addWidget(self.layer_combo, 3)
        self._field_combos = {}

    def add_field(self, label: str, key: str, allow_empty=False):
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fc = QgsFieldComboBox()
        fc.setAllowEmptyFieldName(allow_empty)
        self.layer_combo.layerChanged.connect(fc.setLayer)
        fc.setLayer(self.layer_combo.currentLayer())
        self.addWidget(lbl)
        self.addWidget(fc, 2)
        self._field_combos[key] = fc
        return fc

    def layer(self):
        return self.layer_combo.currentLayer()

    def field(self, key):
        fc = self._field_combos.get(key)
        if fc is None:
            return None
        name = fc.currentField()
        return name if name else None


class RorbBuilderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RORB Catchment Builder")
        self.setMinimumWidth(820)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Title ──────────────────────────────────────────────────────────
        title_box = QGroupBox("Catchment")
        title_form = QFormLayout(title_box)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. PSM6036_Goodwood")
        title_form.addRow("Title:", self.title_edit)
        root.addWidget(title_box)

        # ── Layers ─────────────────────────────────────────────────────────
        layers_box = QGroupBox("Input Layers & Field Mapping")
        layers_form = QFormLayout(layers_box)
        layers_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Reaches (line)
        self._reach_row = _LayerFieldRow(QgsMapLayerProxyModel.LineLayer)
        self._reach_row.add_field("id:", "id")
        self._reach_row.add_field("slope (m/m):", "slope", allow_empty=True)
        self._reach_row.add_field("type (1-4):", "type", allow_empty=True)
        layers_form.addRow("Reaches:", self._reach_row)

        # Centroids (point)
        self._centroid_row = _LayerFieldRow(QgsMapLayerProxyModel.PointLayer)
        self._centroid_row.add_field("id:", "id")
        self._centroid_row.add_field("fi [0-1]:", "fi", allow_empty=True)
        layers_form.addRow("Centroids:", self._centroid_row)

        # Junctions (point)
        self._junction_row = _LayerFieldRow(QgsMapLayerProxyModel.PointLayer)
        self._junction_row.add_field("id:", "id")
        self._junction_row.add_field("outlet (0/1):", "out")
        layers_form.addRow("Junctions:", self._junction_row)

        # Sub-catchments (polygon)
        self._basin_row = _LayerFieldRow(QgsMapLayerProxyModel.PolygonLayer)
        layers_form.addRow("Sub-catchments:", self._basin_row)

        root.addWidget(layers_box)

        # ── Reach type legend ──────────────────────────────────────────────
        legend_label = QLabel(
            "Reach type field: 1 = Natural/Drowned  |  2 = Unlined channel  |  "
            "3 = Lined channel  |  4 = Drowned (same as 1).  Leave blank → Natural."
        )
        legend_label.setWordWrap(True)
        font = QFont()
        font.setPointSize(8)
        legend_label.setFont(font)
        root.addWidget(legend_label)

        # ── Output ─────────────────────────────────────────────────────────
        out_box = QGroupBox("Output")
        out_layout = QHBoxLayout(out_box)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Path to output .catg file …")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(self.out_edit)
        out_layout.addWidget(browse_btn)
        root.addWidget(out_box)

        # ── Log ────────────────────────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        font_mono = QFont("Courier New", 8)
        self.log.setFont(font_mono)
        root.addWidget(self.log)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        build_btn = QPushButton("Build .catg")
        build_btn.setDefault(True)
        build_btn.setMinimumHeight(34)
        build_btn.clicked.connect(self._build)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addStretch()
        btn_row.addWidget(build_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── slots ──────────────────────────────────────────────────────────────
    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save .catg file", "", "RORB Catchment Files (*.catg);;All Files (*)"
        )
        if path:
            if not path.lower().endswith('.catg'):
                path += '.catg'
            self.out_edit.setText(path)

    def _log(self, msg):
        self.log.append(msg)

    def _build(self):
        self.log.clear()
        try:
            self._run_build()
        except Exception:
            self._log("ERROR:")
            self._log(traceback.format_exc())

    def _run_build(self):
        from .core.qgis_builder import build_reaches, build_confluences, build_basins
        from .core.catchment import Catchment
        from .core.traveller import Traveller
        from .core.rorb_writer import build_catg

        # ── validate inputs ────────────────────────────────────────────────
        reach_lyr   = self._reach_row.layer()
        centroid_lyr = self._centroid_row.layer()
        junction_lyr = self._junction_row.layer()
        basin_lyr   = self._basin_row.layer()
        out_path    = self.out_edit.text().strip()

        errors = []
        if reach_lyr is None:   errors.append("No reach layer selected.")
        if centroid_lyr is None: errors.append("No centroid layer selected.")
        if junction_lyr is None: errors.append("No junction layer selected.")
        if basin_lyr is None:   errors.append("No sub-catchment polygon layer selected.")
        if not out_path:        errors.append("No output file path set.")
        if errors:
            for e in errors:
                self._log(f"  ✗ {e}")
            return

        if not self._reach_row.field("id"):
            errors.append("Reach layer: 'id' field is required.")
        if not self._centroid_row.field("id"):
            errors.append("Centroid layer: 'id' field is required.")
        if not self._junction_row.field("id"):
            errors.append("Junction layer: 'id' field is required.")
        if not self._junction_row.field("out"):
            errors.append("Junction layer: 'outlet' field is required.")
        if errors:
            for e in errors:
                self._log(f"  ✗ {e}")
            return

        title = self.title_edit.text().strip()

        # ── build objects ──────────────────────────────────────────────────
        self._log("Building reaches…")
        reaches = build_reaches(
            reach_lyr,
            self._reach_row.field("id"),
            self._reach_row.field("slope"),
            self._reach_row.field("type"),
        )
        self._log(f"  {len(reaches)} reach(es) loaded.")

        self._log("Building junctions…")
        confluences = build_confluences(
            junction_lyr,
            self._junction_row.field("id"),
            self._junction_row.field("out"),
        )
        outlets = [c for c in confluences if c.isOut]
        self._log(f"  {len(confluences)} junction(s) loaded, {len(outlets)} outlet(s).")
        if len(outlets) == 0:
            self._log("  ✗ No outlet junction found. Set 'out' field = 1 on the outlet node.")
            return
        if len(outlets) > 1:
            self._log("  ✗ More than one outlet found. Only one junction may have 'out' = 1.")
            return

        self._log("Building basins (centroid → polygon matching)…")
        basins = build_basins(
            centroid_lyr,
            basin_lyr,
            self._centroid_row.field("id"),
            self._centroid_row.field("fi"),
        )
        self._log(f"  {len(basins)} basin(s) loaded.")

        # ── connect catchment ──────────────────────────────────────────────
        self._log("Connecting catchment topology…")
        catchment = Catchment(confluences, basins, reaches)
        catchment.connect()

        # ── traverse + generate ────────────────────────────────────────────
        self._log("Traversing catchment and generating .catg…")
        traveller = Traveller(catchment)
        content = build_catg(traveller, title=title)

        # ── write file ─────────────────────────────────────────────────────
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, 'w') as f:
            f.write(content)

        self._log(f"\nDone! Written to:\n  {out_path}")
