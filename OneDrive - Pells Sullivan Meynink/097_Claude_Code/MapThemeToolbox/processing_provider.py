# -*- coding: utf-8 -*-
import os
from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
from .algorithm_export_themes import ExportMapThemesAlgorithm


class MapThemeToolboxProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(ExportMapThemesAlgorithm())

    def id(self):   return "mapthemetoolbox"
    def name(self): return "Map Theme Toolbox"
    def longName(self): return self.name()

    def icon(self):
        p = os.path.join(os.path.dirname(__file__), "icon_toolbox.png")
        return QIcon(p) if os.path.exists(p) else super().icon()
