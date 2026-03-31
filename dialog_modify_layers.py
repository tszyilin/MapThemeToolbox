# -*- coding: utf-8 -*-
"""
Modify Theme Layers — Step 1 theme selector + Step 2 drag-and-drop layer toggle.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
    QAbstractItemView, QLineEdit, QCompleter,
)
from qgis.core import QgsProject


# ── Step 1 — theme selector with checkbox + Ctrl/Shift multi-select ───────────

class ThemeSelectDialog(QDialog):
    def __init__(self, themes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Step 1 — Select Themes to Modify")
        self.setMinimumSize(420, 440)

        layout = QVBoxLayout()

        title = QLabel("<b>Select the themes you want to modify:</b>")
        layout.addWidget(title)

        sub = QLabel("The next step shows layers visible in ALL selected themes.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#555;")
        layout.addWidget(sub)

        hint = QLabel("Tip: click to tick · Ctrl+click or Shift+click to multi-select, then Space to tick all at once")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        layout.addWidget(hint)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for t in sorted(themes):
            item = QListWidgetItem(t)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)

        self._syncing = False
        self.list.itemSelectionChanged.connect(self._sync_checks_to_selection)
        self.list.itemChanged.connect(self._sync_selection_to_check)

        layout.addWidget(self.list)

        row = QHBoxLayout()
        ba = QPushButton("Select All")
        bn = QPushButton("Deselect All")
        ba.clicked.connect(self._select_all)
        bn.clicked.connect(self._deselect_all)
        row.addWidget(ba); row.addWidget(bn); row.addStretch()
        layout.addLayout(row)

        btns = QHBoxLayout()
        nxt = QPushButton("Next →")
        nxt.setStyleSheet("font-weight:bold;")
        cnl = QPushButton("Cancel")
        nxt.clicked.connect(self.accept)
        cnl.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(cnl); btns.addWidget(nxt)
        layout.addLayout(btns)

        self.setLayout(layout)

    def _sync_checks_to_selection(self):
        if self._syncing:
            return
        self._syncing = True
        selected_texts = {i.text() for i in self.list.selectedItems()}
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.text() in selected_texts:
                item.setCheckState(Qt.Checked)
        self._syncing = False

    def _sync_selection_to_check(self, item):
        if self._syncing:
            return
        self._syncing = True
        self.list.clearSelection()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                it.setSelected(True)
        self._syncing = False

    def _select_all(self):
        self._syncing = True
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.Checked)
            item.setSelected(True)
        self._syncing = False

    def _deselect_all(self):
        self._syncing = True
        self.list.clearSelection()
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Unchecked)
        self._syncing = False

    def selected_themes(self):
        return [
            self.list.item(i).text()
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.Checked
        ]


# ── Draggable list (Step 2) ────────────────────────────────────────────────────

class DraggableList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True); self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True); self.setMinimumHeight(200)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        super().dropEvent(e)
        for i in range(self.count()-1, -1, -1):
            if not self.item(i).text().strip():
                self.takeItem(i)

    def has_item(self, text):
        return any(self.item(i).text() == text for i in range(self.count()))

    def all_items(self):
        return [self.item(i).text() for i in range(self.count())]


# ── Step 2 — drag-and-drop layer toggle ───────────────────────────────────────

class LayerToggleDialog(QDialog):
    def __init__(self, common_layers, selected_themes, all_project_layers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Step 2 — Toggle Mutual Layers")
        self.setMinimumSize(680, 560)
        self._original = sorted(common_layers)
        self._all_layers = sorted(all_project_layers)

        layout = QVBoxLayout()
        header = QLabel(
            f"<b>Themes:</b> {', '.join(selected_themes)}<br>"
            f"<b>Mutual visible layers ({len(common_layers)}):</b> "
            "drag between columns, or type a layer name to add it."
        )
        header.setWordWrap(True); layout.addWidget(header)

        instr = QLabel("⬅ Drag to <b>HIDDEN</b> to turn OFF · Drag to <b>VISIBLE</b> to turn ON ➡ · Or type below")
        instr.setAlignment(Qt.AlignCenter)
        instr.setStyleSheet("background:#f0f4ff;padding:4px;border-radius:4px;color:#333;")
        layout.addWidget(instr)

        cols = QHBoxLayout()

        # VISIBLE column
        vc = QVBoxLayout()
        vt = QLabel("✅  VISIBLE"); vt.setAlignment(Qt.AlignCenter)
        vt.setStyleSheet("background:#d4edda;color:#155724;font-weight:bold;padding:4px;border-radius:4px;")
        vc.addWidget(vt)
        self.vis = DraggableList()
        self.vis.setStyleSheet("border:2px solid #28a745;border-radius:4px;")
        for l in sorted(common_layers): self.vis.addItem(QListWidgetItem(l))
        vc.addWidget(self.vis)
        vr = QHBoxLayout()
        self.vis_in = QLineEdit(); self.vis_in.setPlaceholderText("Type layer to turn ON…")
        self._completer(self.vis_in)
        vadd = QPushButton("+ Add"); vadd.setFixedWidth(54)
        vadd.clicked.connect(self._add_vis); self.vis_in.returnPressed.connect(self._add_vis)
        vr.addWidget(self.vis_in); vr.addWidget(vadd); vc.addLayout(vr)
        cols.addLayout(vc)

        arr = QLabel("⇄"); arr.setAlignment(Qt.AlignCenter)
        arr.setStyleSheet("font-size:22px;color:#888;"); arr.setFixedWidth(28)
        cols.addWidget(arr)

        # HIDDEN column
        hc = QVBoxLayout()
        ht = QLabel("🚫  HIDDEN"); ht.setAlignment(Qt.AlignCenter)
        ht.setStyleSheet("background:#f8d7da;color:#721c24;font-weight:bold;padding:4px;border-radius:4px;")
        hc.addWidget(ht)
        self.hid = DraggableList()
        self.hid.setStyleSheet("border:2px solid #dc3545;border-radius:4px;")
        hc.addWidget(self.hid)
        hr = QHBoxLayout()
        self.hid_in = QLineEdit(); self.hid_in.setPlaceholderText("Type layer to turn OFF…")
        self._completer(self.hid_in)
        hadd = QPushButton("+ Add"); hadd.setFixedWidth(54)
        hadd.clicked.connect(self._add_hid); self.hid_in.returnPressed.connect(self._add_hid)
        hr.addWidget(self.hid_in); hr.addWidget(hadd); hc.addLayout(hr)
        cols.addLayout(hc)

        layout.addLayout(cols)

        btns = QHBoxLayout()
        rst = QPushButton("↺ Reset"); rst.clicked.connect(self._reset)
        apl = QPushButton("✔ Apply Changes"); apl.setStyleSheet("font-weight:bold;")
        apl.clicked.connect(self.accept)
        cnl = QPushButton("Cancel"); cnl.clicked.connect(self.reject)
        btns.addWidget(rst); btns.addStretch(); btns.addWidget(cnl); btns.addWidget(apl)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _completer(self, le):
        c = QCompleter(self._all_layers)
        c.setCaseSensitivity(Qt.CaseInsensitive)
        c.setFilterMode(Qt.MatchContains)
        le.setCompleter(c)

    def _add_vis(self):
        n = self.vis_in.text().strip()
        if not n: return
        if not self.vis.has_item(n):
            for i in range(self.hid.count()-1, -1, -1):
                if self.hid.item(i).text() == n: self.hid.takeItem(i)
            self.vis.addItem(QListWidgetItem(n))
        self.vis_in.clear()

    def _add_hid(self):
        n = self.hid_in.text().strip()
        if not n: return
        if not self.hid.has_item(n):
            for i in range(self.vis.count()-1, -1, -1):
                if self.vis.item(i).text() == n: self.vis.takeItem(i)
            self.hid.addItem(QListWidgetItem(n))
        self.hid_in.clear()

    def _reset(self):
        self.vis.clear(); self.hid.clear()
        for l in self._original: self.vis.addItem(QListWidgetItem(l))
        self.vis_in.clear(); self.hid_in.clear()

    def layers_to_hide(self): return self.hid.all_items()
    def layers_to_show(self): return self.vis.all_items()
