# -*- coding: utf-8 -*-
"""
Repair Unavailable Layers — batch re-link broken layer sources.

The dialog shows all unavailable file-based layers in a table.
Two independent actions, both feeding the same "Apply Fixes" button:

  Fix ALL rows (prefix replace)
      Replace the common old-folder prefix with a new one.
      The relative sub-path is preserved, so layers scattered across
      sub-folders are all resolved in one shot — as long as the folder
      *structure* is the same on the new machine.

  Fix SELECTED rows (point to folder)
      Select any subset of rows, then browse to the folder that contains
      *those specific* files.  The old-folder prefix is auto-computed
      from the selection's common directory, so sub-folder structure is
      still preserved within the group.  Repeat for each group of layers
      that live in a different location.

Green rows (file found) are applied when you click Apply Fixes.
"""

import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem,
    QFileDialog, QLineEdit, QHeaderView, QMessageBox,
    QAbstractItemView, QApplication, QProgressDialog,
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import QgsProject


# ── helpers ───────────────────────────────────────────────────────────────────

def _broken_file_layers():
    broken = []
    for layer in QgsProject.instance().mapLayers().values():
        if layer.isValid():
            continue
        src      = layer.source()
        file_part = src.split('|')[0]
        if os.sep in file_part or '/' in file_part or (
                len(file_part) > 1 and file_part[1] == ':'):
            broken.append((layer, file_part, src))
    return broken


def _common_dir(paths):
    """Longest common directory prefix of a list of file paths."""
    if not paths:
        return ""
    dirs   = [os.path.normpath(os.path.dirname(p)) for p in paths]
    common = dirs[0]
    for d in dirs[1:]:
        while True:
            if d == common or d.lower().startswith(common.lower() + os.sep):
                break
            parent = os.path.dirname(common)
            if parent == common:
                return ""
            common = parent
    return common


def _prefix_replace(broken_rows, old_norm, new_norm):
    """
    For each (layer, file_path, src) in broken_rows, replace old_norm prefix
    with new_norm.  Returns list of (layer, new_src, exists).
    """
    results = []
    for layer, file_path, src in broken_rows:
        fp_norm = os.path.normpath(file_path)
        if fp_norm.lower().startswith(old_norm.lower()):
            rel      = fp_norm[len(old_norm):]
            if rel.startswith(os.sep):
                rel = rel[len(os.sep):]
            new_file = os.path.join(new_norm, rel)
            new_src  = new_file + src[len(file_path):]
            results.append((layer, new_src, os.path.isfile(new_file)))
        else:
            results.append((layer, None, False))
    return results


def _divider():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def _section_label(text):
    lbl  = QLabel(text)
    font = QFont()
    font.setBold(True)
    lbl.setFont(font)
    return lbl


# ── dialog ────────────────────────────────────────────────────────────────────

class RepairLayersDialog(QDialog):

    # ── column indices ────────────────────────────────────────────────────────
    COL_NAME   = 0
    COL_OLD    = 1
    COL_NEW    = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Repair Unavailable Layers")
        self.resize(960, 640)
        self._broken    = []   # [(layer, file_path, src), …]
        self._previewed = {}   # row_index → (layer, new_src, exists)
        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._summary = QLabel("")
        layout.addWidget(self._summary)

        # ── table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            ["Layer Name", "Current (broken) path", "New path (preview)"]
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_OLD,  QHeaderView.Stretch)
        hdr.setSectionResizeMode(self.COL_NEW,  QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        # ── selection info bar ────────────────────────────────────────────────
        self._sel_label = QLabel("No rows selected.")
        self._sel_label.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self._sel_label)

        layout.addWidget(_divider())

        # ── Section A: Fix ALL rows (prefix replace) ──────────────────────────
        layout.addWidget(_section_label("Fix ALL rows — prefix replace"))
        layout.addWidget(QLabel(
            "Replace the old folder prefix with a new one.  "
            "Sub-folder structure is preserved automatically."
        ))

        old_row = QHBoxLayout()
        old_row.addWidget(QLabel("Old folder:"))
        self._old_edit = QLineEdit()
        self._old_edit.setPlaceholderText("Auto-detected from broken layer paths…")
        old_row.addWidget(self._old_edit)
        btn_detect = QPushButton("Auto-detect")
        btn_detect.setFixedWidth(100)
        btn_detect.clicked.connect(self._auto_detect_all)
        old_row.addWidget(btn_detect)
        layout.addLayout(old_row)

        new_all_row = QHBoxLayout()
        new_all_row.addWidget(QLabel("New folder:"))
        self._new_all_edit = QLineEdit()
        self._new_all_edit.setPlaceholderText("Browse to the equivalent root on this machine…")
        new_all_row.addWidget(self._new_all_edit)
        btn_browse_all = QPushButton("Browse…")
        btn_browse_all.setFixedWidth(100)
        btn_browse_all.clicked.connect(lambda: self._browse(self._new_all_edit))
        new_all_row.addWidget(btn_browse_all)
        btn_prev_all = QPushButton("Preview All")
        btn_prev_all.setFixedWidth(100)
        btn_prev_all.clicked.connect(self._preview_all)
        new_all_row.addWidget(btn_prev_all)
        layout.addLayout(new_all_row)

        layout.addWidget(_divider())

        # ── Section B: Fix SELECTED rows (point to folder) ────────────────────
        layout.addWidget(_section_label("Fix SELECTED rows — point to folder"))
        layout.addWidget(QLabel(
            "Select rows in the table above, then browse to the folder "
            "that contains those specific files.  Repeat for each group "
            "of layers in a different location."
        ))

        new_sel_row = QHBoxLayout()
        new_sel_row.addWidget(QLabel("Folder for selection:"))
        self._new_sel_edit = QLineEdit()
        self._new_sel_edit.setPlaceholderText("Browse to the folder containing the selected files…")
        new_sel_row.addWidget(self._new_sel_edit)
        btn_browse_sel = QPushButton("Browse…")
        btn_browse_sel.setFixedWidth(100)
        btn_browse_sel.clicked.connect(lambda: self._browse(self._new_sel_edit))
        new_sel_row.addWidget(btn_browse_sel)
        self._btn_prev_sel = QPushButton("Preview Selection")
        self._btn_prev_sel.setFixedWidth(130)
        self._btn_prev_sel.setEnabled(False)
        self._btn_prev_sel.clicked.connect(self._preview_selection)
        new_sel_row.addWidget(self._btn_prev_sel)
        layout.addLayout(new_sel_row)

        layout.addWidget(_divider())

        # ── status + buttons ──────────────────────────────────────────────────
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._btn_apply = QPushButton("Apply Fixes")
        self._btn_apply.setEnabled(False)
        self._btn_apply.setToolTip("Re-link all green rows")
        self._btn_apply.clicked.connect(self._apply)
        btn_row.addWidget(self._btn_apply)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    # ── populate ──────────────────────────────────────────────────────────────

    def _populate(self):
        self._broken    = _broken_file_layers()
        self._previewed = {}
        self._btn_apply.setEnabled(False)

        self._table.setRowCount(len(self._broken))
        for row, (layer, file_path, _) in enumerate(self._broken):
            self._table.setItem(row, self.COL_NAME, QTableWidgetItem(layer.name()))
            self._table.setItem(row, self.COL_OLD,  QTableWidgetItem(file_path))
            item = QTableWidgetItem("— use Preview All or Preview Selection —")
            item.setForeground(QColor("grey"))
            self._table.setItem(row, self.COL_NEW, item)

        n = len(self._broken)
        self._summary.setText(
            f"<b>{n} unavailable layer(s) found.</b>" if n
            else "<b>No unavailable layers — nothing to fix!</b>"
        )
        self._auto_detect_all()
        self._update_status()

    # ── selection tracking ────────────────────────────────────────────────────

    def _on_selection_changed(self):
        rows = self._selected_rows()
        n    = len(rows)
        if n:
            self._sel_label.setText(f"{n} row(s) selected.")
            self._btn_prev_sel.setEnabled(True)
        else:
            self._sel_label.setText("No rows selected.")
            self._btn_prev_sel.setEnabled(False)

    def _selected_rows(self):
        return sorted({idx.row() for idx in self._table.selectedIndexes()})

    # ── helpers ───────────────────────────────────────────────────────────────

    def _browse(self, edit_widget):
        start  = edit_widget.text() or ""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", start)
        if folder:
            edit_widget.setText(folder)

    def _auto_detect_all(self):
        paths  = [fp for _, fp, _ in self._broken]
        common = _common_dir(paths)
        if common:
            self._old_edit.setText(common)

    def _set_row_preview(self, row, new_src, exists, skipped=False):
        """Update one table cell and store the preview result."""
        item = self._table.item(row, self.COL_NEW)
        if skipped:
            item.setText("(not under old folder — skipped)")
            item.setForeground(QColor("darkorange"))
            self._previewed[row] = (self._broken[row][0], None, False)
        else:
            item.setText(new_src)
            item.setForeground(QColor("#1a7a1a") if exists else QColor("#cc0000"))
            self._previewed[row] = (self._broken[row][0], new_src, exists)
        self._update_status()

    def _update_status(self):
        found = sum(1 for _, src, ok in self._previewed.values() if ok)
        total = len(self._broken)
        self._btn_apply.setEnabled(found > 0)
        if self._previewed:
            self._status.setText(
                f"<b>{found}</b> of <b>{total}</b> layer(s) ready to fix.  "
                f"<span style='color:#1a7a1a'>Green=found</span> · "
                f"<span style='color:#cc0000'>Red=missing</span> · "
                f"<span style='color:darkorange'>Orange=skipped</span>"
            )
        else:
            self._status.setText(f"{total} layer(s) pending — use Preview to check paths.")

    # ── preview: all rows ─────────────────────────────────────────────────────

    def _preview_all(self):
        old = self._old_edit.text().strip()
        new = self._new_all_edit.text().strip()
        if not old or not new:
            QMessageBox.warning(self, "Missing Input",
                                "Please set both Old folder and New folder.")
            return
        old_norm = os.path.normpath(old)
        new_norm = os.path.normpath(new)
        results  = _prefix_replace(self._broken, old_norm, new_norm)
        for row, (layer, new_src, exists) in enumerate(results):
            self._set_row_preview(row, new_src, exists, skipped=(new_src is None))

    # ── preview: selected rows ────────────────────────────────────────────────

    def _preview_selection(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "No Selection",
                                    "Select rows in the table first.")
            return
        new = self._new_sel_edit.text().strip()
        if not new:
            QMessageBox.warning(self, "Missing Input",
                                "Please browse to the folder for the selected rows.")
            return

        # Auto-compute the old prefix from the selected rows
        sel_paths = [self._broken[r][1] for r in rows]
        old_norm  = os.path.normpath(_common_dir(sel_paths))
        new_norm  = os.path.normpath(new)

        sel_broken = [self._broken[r] for r in rows]
        results    = _prefix_replace(sel_broken, old_norm, new_norm)

        for row, (layer, new_src, exists) in zip(rows, results):
            self._set_row_preview(row, new_src, exists, skipped=(new_src is None))

    # ── apply ─────────────────────────────────────────────────────────────────

    def _apply(self):
        fixed = 0
        for layer, new_src, exists in self._previewed.values():
            if exists and new_src:
                provider = layer.dataProvider().name()
                layer.setDataSource(new_src, layer.name(), provider)
                fixed += 1
        if fixed:
            QgsProject.instance().setDirty(True)
        QMessageBox.information(
            self, "Done",
            f"Re-linked {fixed} layer(s).\n"
            "Project has unsaved changes — save to keep the new paths."
        )
        self._previewed = {}
        self._populate()
