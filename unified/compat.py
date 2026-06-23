# -*- coding: utf-8 -*-
"""
Qt 5 / Qt 6 compatibility shim for Map Theme Toolbox.

Detected once at import time via qVersion(); all constants are plain
Python objects — no runtime branching in the rest of the plugin.

Usage in other modules:
    from .compat import (Checked, UserRole, Button_Yes, ...)
"""

from qgis.PyQt.QtCore import Qt, qVersion
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QDockWidget, QFrame,
    QHeaderView, QDialogButtonBox, QMessageBox, QDialog,
)
from qgis.PyQt.QtGui import QPainter

QT6 = int(qVersion().split(".")[0]) >= 6

if QT6:
    # ── Qt namespace ──────────────────────────────────────────────────────────
    Checked               = Qt.CheckState.Checked
    Unchecked             = Qt.CheckState.Unchecked
    UserRole              = Qt.ItemDataRole.UserRole
    UserRole1             = Qt.ItemDataRole.UserRole + 1
    ItemIsEnabled         = Qt.ItemFlag.ItemIsEnabled
    ItemIsSelectable      = Qt.ItemFlag.ItemIsSelectable
    ItemIsDragEnabled     = Qt.ItemFlag.ItemIsDragEnabled
    ItemIsDropEnabled     = Qt.ItemFlag.ItemIsDropEnabled
    ItemIsUserCheckable   = Qt.ItemFlag.ItemIsUserCheckable
    AlignCenter           = Qt.AlignmentFlag.AlignCenter
    AlignLeft             = Qt.AlignmentFlag.AlignLeft
    AlignRight            = Qt.AlignmentFlag.AlignRight
    AlignVCenter          = Qt.AlignmentFlag.AlignVCenter
    Transparent           = Qt.GlobalColor.transparent
    NoBrush               = Qt.BrushStyle.NoBrush
    NoPen                 = Qt.PenStyle.NoPen
    SolidLine             = Qt.PenStyle.SolidLine
    RoundCap              = Qt.PenCapStyle.RoundCap
    MoveAction            = Qt.DropAction.MoveAction
    CaseInsensitive       = Qt.CaseSensitivity.CaseInsensitive
    MatchContains         = Qt.MatchFlag.MatchContains
    WinNoHelpBtn          = Qt.WindowType.WindowContextHelpButtonHint
    RightDock             = Qt.DockWidgetArea.RightDockWidgetArea
    LeftDock              = Qt.DockWidgetArea.LeftDockWidgetArea
    BottomDock            = Qt.DockWidgetArea.BottomDockWidgetArea
    Horizontal            = Qt.Orientation.Horizontal

    # ── QAbstractItemView ─────────────────────────────────────────────────────
    InternalMove          = QAbstractItemView.DragDropMode.InternalMove
    DragDrop              = QAbstractItemView.DragDropMode.DragDrop
    OnItem                = QAbstractItemView.DropIndicatorPosition.OnItem
    ExtendedSelection     = QAbstractItemView.SelectionMode.ExtendedSelection
    SingleSelection       = QAbstractItemView.SelectionMode.SingleSelection
    NoEditTriggers        = QAbstractItemView.EditTrigger.NoEditTriggers
    SelectRows            = QAbstractItemView.SelectionBehavior.SelectRows

    # ── QPainter ──────────────────────────────────────────────────────────────
    Antialiasing          = QPainter.RenderHint.Antialiasing

    # ── QDockWidget ───────────────────────────────────────────────────────────
    DockMovable           = QDockWidget.DockWidgetFeature.DockWidgetMovable
    DockFloatable         = QDockWidget.DockWidgetFeature.DockWidgetFloatable
    DockClosable          = QDockWidget.DockWidgetFeature.DockWidgetClosable

    # ── QFrame ────────────────────────────────────────────────────────────────
    HLine                 = QFrame.Shape.HLine
    Sunken                = QFrame.Shadow.Sunken

    # ── QHeaderView ───────────────────────────────────────────────────────────
    ResizeToContents      = QHeaderView.ResizeMode.ResizeToContents
    Stretch               = QHeaderView.ResizeMode.Stretch

    # ── QDialogButtonBox ──────────────────────────────────────────────────────
    Button_Ok             = QDialogButtonBox.StandardButton.Ok
    Button_Cancel         = QDialogButtonBox.StandardButton.Cancel

    # ── QMessageBox ───────────────────────────────────────────────────────────
    Button_Yes            = QMessageBox.StandardButton.Yes
    Button_No             = QMessageBox.StandardButton.No

    # ── QDialog ───────────────────────────────────────────────────────────────
    Accepted              = QDialog.DialogCode.Accepted

    # ── QgsField / QgsVectorFileWriter ────────────────────────────────────────
    from qgis.PyQt.QtCore import QMetaType
    from qgis.core import QgsVectorFileWriter as _VFW
    FieldType_String      = QMetaType.Type.QString
    VFW_NoError           = _VFW.VectorWriterResult.NoError

else:  # Qt 5 / PyQt5
    # ── Qt namespace ──────────────────────────────────────────────────────────
    Checked               = Qt.Checked
    Unchecked             = Qt.Unchecked
    UserRole              = Qt.UserRole
    UserRole1             = Qt.UserRole + 1
    ItemIsEnabled         = Qt.ItemIsEnabled
    ItemIsSelectable      = Qt.ItemIsSelectable
    ItemIsDragEnabled     = Qt.ItemIsDragEnabled
    ItemIsDropEnabled     = Qt.ItemIsDropEnabled
    ItemIsUserCheckable   = Qt.ItemIsUserCheckable
    AlignCenter           = Qt.AlignCenter
    AlignLeft             = Qt.AlignLeft
    AlignRight            = Qt.AlignRight
    AlignVCenter          = Qt.AlignVCenter
    Transparent           = Qt.transparent
    NoBrush               = Qt.NoBrush
    NoPen                 = Qt.NoPen
    SolidLine             = Qt.SolidLine
    RoundCap              = Qt.RoundCap
    MoveAction            = Qt.MoveAction
    CaseInsensitive       = Qt.CaseInsensitive
    MatchContains         = Qt.MatchContains
    WinNoHelpBtn          = Qt.WindowContextHelpButtonHint
    RightDock             = Qt.RightDockWidgetArea
    LeftDock              = Qt.LeftDockWidgetArea
    BottomDock            = Qt.BottomDockWidgetArea
    Horizontal            = Qt.Horizontal

    # ── QAbstractItemView ─────────────────────────────────────────────────────
    InternalMove          = QAbstractItemView.InternalMove
    DragDrop              = QAbstractItemView.DragDrop
    OnItem                = QAbstractItemView.OnItem
    ExtendedSelection     = QAbstractItemView.ExtendedSelection
    SingleSelection       = QAbstractItemView.SingleSelection
    NoEditTriggers        = QAbstractItemView.NoEditTriggers
    SelectRows            = QAbstractItemView.SelectRows

    # ── QPainter ──────────────────────────────────────────────────────────────
    Antialiasing          = QPainter.Antialiasing

    # ── QDockWidget ───────────────────────────────────────────────────────────
    DockMovable           = QDockWidget.DockWidgetMovable
    DockFloatable         = QDockWidget.DockWidgetFloatable
    DockClosable          = QDockWidget.DockWidgetClosable

    # ── QFrame ────────────────────────────────────────────────────────────────
    HLine                 = QFrame.HLine
    Sunken                = QFrame.Sunken

    # ── QHeaderView ───────────────────────────────────────────────────────────
    ResizeToContents      = QHeaderView.ResizeToContents
    Stretch               = QHeaderView.Stretch

    # ── QDialogButtonBox ──────────────────────────────────────────────────────
    Button_Ok             = QDialogButtonBox.Ok
    Button_Cancel         = QDialogButtonBox.Cancel

    # ── QMessageBox ───────────────────────────────────────────────────────────
    Button_Yes            = QMessageBox.Yes
    Button_No             = QMessageBox.No

    # ── QDialog ───────────────────────────────────────────────────────────────
    Accepted              = QDialog.Accepted

    # ── QgsField / QgsVectorFileWriter ────────────────────────────────────────
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import QgsVectorFileWriter as _VFW
    FieldType_String      = QVariant.String
    VFW_NoError           = _VFW.NoError
