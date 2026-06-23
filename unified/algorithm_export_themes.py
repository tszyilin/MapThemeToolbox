# -*- coding: utf-8 -*-
import csv, os
from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString, QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber, QgsProcessingOutputString,
    QgsProject, QgsProcessingException,
)
from qgis.PyQt.QtCore import QCoreApplication


class ExportMapThemesAlgorithm(QgsProcessingAlgorithm):
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    FILE_NAME     = "FILE_NAME"
    INCLUDE_HEADER = "INCLUDE_HEADER"
    OUTPUT_COUNT  = "THEME_COUNT"
    OUTPUT_PATH   = "OUTPUT_PATH"

    def tr(self, s): return QCoreApplication.translate("ExportMapThemesAlgorithm", s)
    def createInstance(self): return ExportMapThemesAlgorithm()
    def name(self): return "exportmapthemes"
    def displayName(self): return self.tr("Export Map Themes to CSV")
    def group(self): return self.tr("Map Themes")
    def groupId(self): return "mapthemes"

    def shortHelpString(self):
        return self.tr("Exports all Map Themes in the current project to a CSV file.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, self.tr("Output Folder")))
        self.addParameter(QgsProcessingParameterString(self.FILE_NAME, self.tr("File Name (without extension)"), defaultValue="map_themes"))
        self.addParameter(QgsProcessingParameterBoolean(self.INCLUDE_HEADER, self.tr("Include Header Row"), defaultValue=True))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_COUNT, self.tr("Theme Count")))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_PATH, self.tr("Output Path")))

    def processAlgorithm(self, parameters, context, feedback):
        folder   = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context).strip()
        fname    = self.parameterAsString(parameters, self.FILE_NAME, context).strip()
        header   = self.parameterAsBoolean(parameters, self.INCLUDE_HEADER, context)
        base     = os.path.splitext(fname)[0] if fname else "map_themes"
        out_csv  = os.path.join(folder, base + ".csv")

        os.makedirs(folder, exist_ok=True)
        tc = QgsProject.instance().mapThemeCollection()
        names = tc.mapThemes()
        feedback.pushInfo(self.tr(f"Found {len(names)} map theme(s)."))

        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if header: w.writerow(["Theme Name"])
            for i, n in enumerate(names):
                w.writerow([n])
                feedback.setProgress(int((i+1)/max(len(names),1)*100))
                if feedback.isCanceled(): break

        feedback.pushInfo(self.tr(f"Saved to: {out_csv}"))
        return {self.OUTPUT_FOLDER: folder, self.OUTPUT_COUNT: len(names), self.OUTPUT_PATH: out_csv}
