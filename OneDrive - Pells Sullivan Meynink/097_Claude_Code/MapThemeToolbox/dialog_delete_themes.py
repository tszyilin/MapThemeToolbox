# -*- coding: utf-8 -*-
"""Delete Map Themes — list with checkboxes + Ctrl/Shift multi-select."""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QAbstractItemView
)
from qgis.PyQt.QtCore import Qt


class DeleteThemesDialog(QDialog):
    def __init__(self, themes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete Map Themes")
        self.setMinimumSize(380, 420)

        layout = QVBoxLayout()

        title = QLabel("Select the map themes you want to delete:")
        title.setWordWrap(True)
        layout.addWidget(title)

        hint = QLabel("Tip: click to tick · Ctrl+click or Shift+click to multi-select, then Space to tick all at once")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        layout.addWidget(hint)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Ctrl + Shift support
        for theme in sorted(themes):
            item = QListWidgetItem(theme)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)

        # When selection changes, sync checkboxes to selection
        self.list.itemSelectionChanged.connect(self._sync_checks_to_selection)
        # When a checkbox is clicked directly, also select that row
        self.list.itemChanged.connect(self._sync_selection_to_check)
        self._syncing = False

        layout.addWidget(self.list)

        # Select All / Deselect All
        sel = QHBoxLayout()
        btn_all  = QPushButton("Select All")
        btn_none = QPushButton("Deselect All")
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._deselect_all)
        sel.addWidget(btn_all); sel.addWidget(btn_none)
        layout.addLayout(sel)

        # OK / Cancel
        btns = QHBoxLayout()
        ok = QPushButton("Delete Selected")
        ok.setStyleSheet("color:red; font-weight:bold;")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok); btns.addWidget(cancel)
        layout.addLayout(btns)

        self.setLayout(layout)

    def _sync_checks_to_selection(self):
        """When user Ctrl/Shift-selects rows, tick all selected checkboxes."""
        if self._syncing:
            return
        self._syncing = True
        selected_texts = {i.text() for i in self.list.selectedItems()}
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.text() in selected_texts:
                item.setCheckState(Qt.Checked)
            # Don't uncheck others — user may have manually ticked them
        self._syncing = False

    def _sync_selection_to_check(self, item):
        """When a checkbox is toggled, update the list selection to match all checked items."""
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
