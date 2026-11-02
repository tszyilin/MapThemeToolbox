# -*- coding: utf-8 -*-
"""
Export Selected Atlas Pages — layout designer button.  QGIS 3.22+ and QGIS 4.x.

Pages are exported by seeking the real atlas rather than by filtering it, so
@atlas_featurenumber and @atlas_totalfeatures match a full atlas export.
"""

import os
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QLineEdit, QComboBox, QFileDialog, QProgressDialog,
    QMessageBox, QSpinBox, QSlider, QCheckBox, QGroupBox, QDialogButtonBox,
)
from qgis.core import (
    Qgis, QgsAbstractLayoutIterator, QgsFeedback, QgsLayoutExporter, QgsLayoutUtils,
    QgsLayoutRenderContext, QgsMargins, QgsSettings, QgsUnitTypes,
)

from .compat import (
    Checked, Unchecked, ItemIsUserCheckable, ExtendedSelection, WindowModal, Accepted,
    Horizontal, Button_Ok, Button_Cancel,
)

TITLE = "Export Selected Atlas Pages"
DIR_KEY = "MapThemeToolbox/atlasExportDir"

SINGLE_PDF = "single_pdf"
SEPARATE_PDFS = "separate_pdfs"
FORMATS = [
    ("Single PDF", SINGLE_PDF),
    ("Separate PDFs", SEPARATE_PDFS),
    ("PNG images", "png"),
    ("JPG images", "jpg"),
    ("TIF images", "tif"),
]

_last_pages = {}    # layout name -> page names ticked last time (this session)


def designer_print_layout(designer):
    """The designer's print layout, or None for a report.

    Some QGIS builds hand back designer.layout() as a plain QgsLayout with no
    atlas(), so fall back to masterLayout(), which resolves to QgsPrintLayout.
    """
    for get in ("layout", "masterLayout"):
        layout = getattr(designer, get, lambda: None)()
        if hasattr(layout, "atlas"):
            return layout
    return None


class SelectedPagesIterator(QgsAbstractLayoutIterator):
    """Walks only the chosen pages of an atlas, for QgsLayoutExporter."""

    def __init__(self, atlas, pages, on_page=None):
        super().__init__()
        self._atlas   = atlas
        self._pages   = pages
        self._on_page = on_page
        self._pos     = -1

    def layout(self):
        return self._atlas.layout()

    def beginRender(self):
        self._pos = -1
        return self._atlas.beginRender()

    def endRender(self):
        return self._atlas.endRender()

    def count(self):
        return len(self._pages)

    def filePath(self, baseFilePath, extension):
        return self._atlas.filePath(baseFilePath, extension)

    def next(self):
        self._pos += 1
        if self._pos >= len(self._pages):
            return False
        page = self._pages[self._pos]
        if self._on_page:
            self._on_page(self._pos, self._atlas.nameForPage(page))
        return self._atlas.seekTo(page)


class AtlasPagesDialog(QDialog):
    def __init__(self, layout, preselect=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setMinimumSize(420, 520)
        atlas = layout.atlas()

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>Select the pages of “{layout.name()}” to export:</b>"))
        hint = QLabel("Tip: click to tick · Shift+click for a range · Ctrl+click to add")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        root.addWidget(hint)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter pages…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        root.addWidget(self.filter)

        self.list = QListWidget()
        self.list.setSelectionMode(ExtendedSelection)
        for i in range(atlas.count()):
            name = atlas.nameForPage(i)
            item = QListWidgetItem(f"{i + 1}.  {name}")
            item.setFlags(item.flags() | ItemIsUserCheckable)
            item.setCheckState(Checked if name in preselect else Unchecked)
            self.list.addItem(item)
        self._syncing = False
        self.list.itemSelectionChanged.connect(self._sync_checks_to_selection)
        self.list.itemChanged.connect(self._sync_selection_to_check)
        root.addWidget(self.list)

        row = QHBoxLayout()
        ba = QPushButton("Select All")
        bn = QPushButton("Deselect All")
        ba.setToolTip("Tick every page shown by the filter")
        ba.clicked.connect(lambda: self._set_visible(Checked))
        bn.clicked.connect(self._deselect_all)
        row.addWidget(ba)
        row.addWidget(bn)
        row.addStretch()
        self.count_label = QLabel()
        row.addWidget(self.count_label)
        root.addLayout(row)

        fmt = QHBoxLayout()
        fmt.addWidget(QLabel("Export as:"))
        self.format = QComboBox()
        for label, key in FORMATS:
            self.format.addItem(label, key)
        fmt.addWidget(self.format, 1)
        root.addLayout(fmt)

        self.format.setCurrentIndex(self.format.findData("jpg"))

        note = QLabel("Image formats ask for resolution, quality and cropping next; "
                      "PDFs use the options saved in this layout. "
                      "Separate files are named by the atlas output filename expression.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#555; font-style:italic;")
        root.addWidget(note)

        btns = QHBoxLayout()
        self.ok = QPushButton("Export…")
        self.ok.setDefault(True)
        self.ok.setStyleSheet("font-weight:bold;")
        cnl = QPushButton("Cancel")
        self.ok.clicked.connect(self.accept)
        cnl.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cnl)
        btns.addWidget(self.ok)
        root.addLayout(btns)

        self._update_count()

    def _items(self):
        return [self.list.item(i) for i in range(self.list.count())]

    def _apply_filter(self, text):
        text = text.strip().lower()
        for item in self._items():
            item.setHidden(text not in item.text().lower())

    def _sync_checks_to_selection(self):
        if self._syncing:
            return
        self._syncing = True
        for item in self.list.selectedItems():
            item.setCheckState(Checked)
        self._syncing = False
        self._update_count()

    def _sync_selection_to_check(self, _item):
        if self._syncing:
            return
        self._syncing = True
        self.list.clearSelection()
        for item in self._items():
            if item.checkState() == Checked:
                item.setSelected(True)
        self._syncing = False
        self._update_count()

    def _set_visible(self, state):
        self._syncing = True
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(state)
                item.setSelected(state == Checked)
        self._syncing = False
        self._update_count()

    def _deselect_all(self):
        self._syncing = True
        self.list.clearSelection()
        for item in self._items():
            item.setCheckState(Unchecked)
        self._syncing = False
        self._update_count()

    def _update_count(self):
        n = len(self.selected_pages())
        self.count_label.setText(f"{n} of {self.list.count()} selected")
        self.ok.setEnabled(n > 0)

    def selected_pages(self):
        return [i for i, item in enumerate(self._items()) if item.checkState() == Checked]

    def format_key(self):
        return self.format.currentData()


def _prop_bool(layout, key, default):
    value = layout.customProperty(key, default)
    if isinstance(value, str):
        return value.lower() in ("1", "true")
    return bool(value)


def _common_settings(settings, layout):
    settings.dpi = layout.renderContext().dpi()
    settings.flags = layout.renderContext().flags()
    settings.predefinedMapScales = QgsLayoutUtils.predefinedScales(layout)
    return settings


def _pdf_settings(layout):
    """Same options the layout's native PDF export has saved."""
    s = _common_settings(QgsLayoutExporter.PdfExportSettings(), layout)
    s.rasterizeWholeImage = _prop_bool(layout, "rasterize", False)
    s.forceVectorOutput   = _prop_bool(layout, "forceVector", False)
    s.appendGeoreference  = _prop_bool(layout, "pdfAppendGeoreference", True)
    s.exportMetadata      = _prop_bool(layout, "pdfIncludeMetadata", True)
    s.simplifyGeometries  = _prop_bool(layout, "pdfSimplify", True)
    text_format = layout.customProperty("pdfTextRenderFormat", None)
    if text_format is not None:
        s.textRenderFormat = type(s.textRenderFormat)(int(text_format))
    return s


_ANTIALIAS = getattr(QgsLayoutRenderContext, "FlagAntialiasing", None)
if _ANTIALIAS is None:
    _ANTIALIAS = Qgis.LayoutRenderFlag.Antialiasing
_INCHES = Qgis.LayoutUnit.Inches if hasattr(Qgis, "LayoutUnit") else QgsUnitTypes.LayoutInches


def _image_settings(layout):
    """Image options as last saved in the layout (same keys as QGIS's own export)."""
    s = _common_settings(QgsLayoutExporter.ImageExportSettings(), layout)
    s.generateWorldFile = _prop_bool(layout, "exportWorldFile", False)
    s.cropToContents    = _prop_bool(layout, "imageCropToContents", False)
    s.cropMargins = QgsMargins(*(int(layout.customProperty(f"imageCropMargin{side}", 0))
                                 for side in ("Left", "Top", "Right", "Bottom")))
    if _prop_bool(layout, "imageAntialias", True):
        s.flags = s.flags | _ANTIALIAS
    else:
        s.flags = s.flags & ~_ANTIALIAS
    if hasattr(s, "quality"):
        s.quality = int(layout.customProperty("imageQuality", 90))
    return s


class ImageOptionsDialog(QDialog):
    """Resolution, size, JPG quality and crop options, like QGIS's Image Export Options."""

    def __init__(self, layout, key, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Export Options")
        self._layout = layout
        self._settings = _image_settings(layout)
        page = layout.pageCollection().page(0)
        inches = layout.renderContext().measurementConverter().convert(
            page.sizeWithUnits(), _INCHES).toQSizeF()
        self._inches = (inches.width(), inches.height())

        root = QVBoxLayout(self)
        opts = QGroupBox("Export Options")
        form = QFormLayout(opts)
        self.dpi = QSpinBox()
        self.dpi.setRange(1, 3000)
        self.dpi.setSuffix(" dpi")
        self.width_px = QSpinBox()
        self.height_px = QSpinBox()
        for spin in (self.width_px, self.height_px):
            spin.setRange(1, 99999)
            spin.setSuffix(" px")
        self.dpi.setValue(int(round(self._settings.dpi)))
        self._sync_size_from_dpi()
        self.dpi.valueChanged.connect(self._sync_size_from_dpi)
        self.width_px.valueChanged.connect(lambda v: self._sync_dpi_from_px(v, 0))
        self.height_px.valueChanged.connect(lambda v: self._sync_dpi_from_px(v, 1))
        form.addRow("Export resolution", self.dpi)
        form.addRow("Page width", self.width_px)
        form.addRow("Page height", self.height_px)

        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setSuffix("%")
        slider = QSlider(Horizontal)
        slider.setRange(1, 100)
        slider.valueChanged.connect(self.quality.setValue)
        self.quality.valueChanged.connect(slider.setValue)
        self.quality.setValue(getattr(self._settings, "quality", 90))
        q_row = QHBoxLayout()
        q_row.addWidget(slider, 1)
        q_row.addWidget(self.quality)
        q_label = QLabel("JPG quality")
        form.addRow(q_label, q_row)
        jpg = key == "jpg" and hasattr(self._settings, "quality")
        for w in (q_label, slider, self.quality):
            w.setEnabled(jpg)

        self.antialias = QCheckBox("Enable antialiasing")
        self.antialias.setChecked(bool(self._settings.flags & _ANTIALIAS))
        self.world_file = QCheckBox("Generate world file")
        self.world_file.setChecked(self._settings.generateWorldFile)
        form.addRow(self.antialias)
        form.addRow(self.world_file)
        root.addWidget(opts)

        self.crop = QGroupBox("Crop to Content")
        self.crop.setCheckable(True)
        self.crop.setChecked(self._settings.cropToContents)
        grid = QGridLayout(self.crop)
        m = self._settings.cropMargins
        self.margins = {}
        for side, value, row, col in (("Top", m.top(), 0, 1), ("Left", m.left(), 1, 0),
                                      ("Right", m.right(), 1, 2), ("Bottom", m.bottom(), 2, 1)):
            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(int(value))
            box = QHBoxLayout()
            box.addWidget(QLabel(f"{side} margin (px)"))
            box.addWidget(spin)
            grid.addLayout(box, row, col)
            self.margins[side] = spin
        root.addWidget(self.crop)

        bb = QDialogButtonBox(Button_Ok | Button_Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _sync_size_from_dpi(self, _=None):
        dpi = self.dpi.value()
        for spin, inches in ((self.width_px, self._inches[0]), (self.height_px, self._inches[1])):
            spin.blockSignals(True)
            spin.setValue(int(round(inches * dpi)))
            spin.blockSignals(False)

    def _sync_dpi_from_px(self, px, axis):
        self.dpi.blockSignals(True)
        self.dpi.setValue(int(round(px / self._inches[axis])))
        self.dpi.blockSignals(False)
        other = self.height_px if axis == 0 else self.width_px
        other.blockSignals(True)
        other.setValue(int(round(px * self._inches[1 - axis] / self._inches[axis])))
        other.blockSignals(False)

    def settings(self):
        """ImageExportSettings from the dialog; also saved back to the layout."""
        s, lay = self._settings, self._layout
        s.dpi = self.dpi.value()
        s.generateWorldFile = self.world_file.isChecked()
        s.cropToContents = self.crop.isChecked()
        s.cropMargins = QgsMargins(*(self.margins[k].value()
                                     for k in ("Left", "Top", "Right", "Bottom")))
        if self.antialias.isChecked():
            s.flags = s.flags | _ANTIALIAS
        else:
            s.flags = s.flags & ~_ANTIALIAS
        if hasattr(s, "quality"):
            s.quality = self.quality.value()
            lay.setCustomProperty("imageQuality", s.quality)
        lay.setCustomProperty("exportWorldFile", s.generateWorldFile)
        lay.setCustomProperty("imageCropToContents", s.cropToContents)
        lay.setCustomProperty("imageAntialias", self.antialias.isChecked())
        for side, spin in self.margins.items():
            lay.setCustomProperty(f"imageCropMargin{side}", spin.value())
        return s


def export_pages(layout, pages, key, path, feedback=None, on_page=None, image_settings=None):
    """Export atlas pages (0-based) to path — a file for SINGLE_PDF, else a folder.

    Returns (QgsLayoutExporter.ExportResult, error text).
    """
    iterator = SelectedPagesIterator(layout.atlas(), pages, on_page)
    if key == SINGLE_PDF:
        return QgsLayoutExporter.exportToPdf(iterator, path, _pdf_settings(layout), feedback)
    # QgsLayoutAtlas.filePath() keeps only the directory of this base path, so
    # it must name a file inside the folder; the atlas supplies the real names
    base = os.path.join(path, "atlas")
    if key == SEPARATE_PDFS:
        return QgsLayoutExporter.exportToPdfs(iterator, base, _pdf_settings(layout), feedback)
    return QgsLayoutExporter.exportToImage(iterator, base, key,
                                           image_settings or _image_settings(layout), feedback)


def _ask_path(parent, layout, key):
    settings = QgsSettings()
    folder = settings.value(DIR_KEY, os.path.expanduser("~"))
    if key == SINGLE_PDF:
        start = os.path.join(folder, f"{layout.name()}_selected.pdf")
        path, _ = QFileDialog.getSaveFileName(parent, TITLE, start, "PDF files (*.pdf)")
        if path and not path.lower().endswith(".pdf"):
            path += ".pdf"
    else:
        path = QFileDialog.getExistingDirectory(parent, f"{TITLE} — output folder", folder)
    if path:
        settings.setValue(DIR_KEY, os.path.dirname(path) if key == SINGLE_PDF else path)
    return path


def run_atlas_export(designer):
    layout = designer_print_layout(designer)
    if layout is None:
        return
    atlas  = layout.atlas()
    parent = designer.window()

    preview = designer.atlasPreviewEnabled()
    current = atlas.currentFeatureNumber()
    if not preview:
        atlas.updateFeatures()
    if atlas.count() == 0:
        QMessageBox.information(parent, TITLE, "This atlas has no pages to export.\n"
                                "Check its coverage layer and filter in Atlas Settings.")
        return

    preselect = _last_pages.get(layout.name(), ())
    if not preselect and preview and current >= 0:
        preselect = (atlas.nameForPage(current),)

    dlg = AtlasPagesDialog(layout, preselect, parent)
    if dlg.exec() != Accepted:
        return
    pages = dlg.selected_pages()
    key   = dlg.format_key()
    _last_pages[layout.name()] = {atlas.nameForPage(p) for p in pages}

    image_settings = None
    if key not in (SINGLE_PDF, SEPARATE_PDFS):
        opts = ImageOptionsDialog(layout, key, parent)
        if opts.exec() != Accepted:
            return
        image_settings = opts.settings()

    path = _ask_path(parent, layout, key)
    if not path:
        return

    feedback = QgsFeedback()
    progress = QProgressDialog("Preparing…", "Cancel", 0, 100, parent)
    progress.setWindowTitle(TITLE)
    progress.setWindowModality(WindowModal)
    progress.setMinimumDuration(0)
    progress.setMinimumWidth(420)
    progress.setValue(0)
    progress.canceled.connect(feedback.cancel)

    def on_page(index, name):
        progress.setLabelText(f"Exporting page {index + 1} of {len(pages)}:\n{name}")
        QCoreApplication.processEvents()

    def on_progress(value):
        progress.setValue(int(value))
        QCoreApplication.processEvents()

    feedback.progressChanged.connect(on_progress)

    view = designer.view()
    view.setUpdatesEnabled(False)
    if preview:
        designer.setAtlasPreviewEnabled(False)
    try:
        result, error = export_pages(layout, pages, key, path, feedback, on_page, image_settings)
    finally:
        progress.close()
        view.setUpdatesEnabled(True)
        if preview:
            designer.setAtlasPreviewEnabled(True)
            atlas.seekTo(current)
        layout.refresh()

    bar = designer.messageBar()
    if result == QgsLayoutExporter.Success:
        bar.pushSuccess(TITLE, f"Exported {len(pages)} page(s) to {path}")
    elif result == QgsLayoutExporter.Canceled:
        bar.pushInfo(TITLE, "Export canceled.")
    else:
        QMessageBox.warning(parent, TITLE, f"Export failed.\n\n{error}")
