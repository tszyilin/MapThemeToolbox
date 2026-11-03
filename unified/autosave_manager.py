# -*- coding: utf-8 -*-
"""
AutoSaveManager — persistent timer that saves the project on a schedule.

Settings (enabled, interval) are stored in QgsSettings so they survive
QGIS restarts.  The timer keeps running even when the dialog is closed.
"""

from datetime import datetime

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.core import QgsProject, QgsSettings

from .compat import MsgBox_Ok


class AutoSaveManager:

    _KEY_ENABLED       = "MapThemeToolbox/autosave/enabled"
    _KEY_INTERVAL      = "MapThemeToolbox/autosave/interval"
    _KEY_SHOW_ON_START = "MapThemeToolbox/autosave/show_on_start"

    def __init__(self, iface):
        self.iface          = iface
        self.last_save      = None   # "HH:MM:SS" string set after each save
        self._enabled       = False
        self._interval      = 3600   # seconds (default 60 min)
        self._show_on_start = True   # open dialog when QGIS starts
        self._callbacks     = []

        self._timer = QTimer()
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._do_save)

        self._load_settings()
        if self._enabled:
            self._timer.start(self._interval * 1000)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def enabled(self):
        return self._enabled

    @property
    def interval(self):
        return self._interval

    @property
    def show_on_start(self):
        return self._show_on_start

    def timer_remaining(self):
        """Seconds until next auto-save, or None if not running."""
        if not self._timer.isActive():
            return None
        return max(0, self._timer.remainingTime() // 1000)

    def apply(self, enabled, interval, show_on_start=True):
        """Apply new settings and (re)start or stop the timer."""
        self._enabled       = bool(enabled)
        self._interval      = max(10, int(interval))
        self._show_on_start = bool(show_on_start)
        self._save_settings()
        if self._enabled:
            self._timer.start(self._interval * 1000)
        else:
            self._timer.stop()
        self._notify()

    def save_now(self):
        """Trigger an immediate save and reset the countdown."""
        self._do_save()
        if self._enabled:
            self._timer.start(self._interval * 1000)   # reset countdown

    def register_callback(self, cb):
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    def unregister_callback(self, cb):
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    def stop(self):
        """Called during plugin unload."""
        self._timer.stop()
        self._callbacks.clear()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _do_save(self):
        project = QgsProject.instance()
        if not project.fileName():
            self.iface.messageBar().pushWarning(
                "Auto-Save",
                "Project has no file path — please save it manually first (Ctrl+S)."
            )
            return
        # Save through QGIS's own action, not project.write(): QGIS remembers the
        # file's modified time only for its own saves, and would otherwise ask
        # "Project Has Changed on Disk" at the next save
        # The save blocks while QGIS shows "Project Has Changed on Disk", so a
        # timer running alongside it answers OK for auto-saves
        confirm = QTimer()
        confirm.setInterval(100)
        confirm.timeout.connect(self._confirm_overwrite)
        confirm.start()
        try:
            self.iface.actionSaveProject().trigger()
        finally:
            confirm.stop()
        if not project.isDirty():
            self.last_save = datetime.now().strftime("%H:%M:%S")
            self.iface.messageBar().pushSuccess(
                "Auto-Save", f"Project saved at {self.last_save}"
            )
            self._notify()
        else:
            self.iface.messageBar().pushCritical(
                "Auto-Save", "Failed to save the project."
            )

    @staticmethod
    def _confirm_overwrite():
        for w in QApplication.topLevelWidgets():
            if (isinstance(w, QMessageBox) and w.isVisible()
                    and ("Changed on Disk" in w.windowTitle()
                         or "modified externally" in w.text())):
                ok = w.button(MsgBox_Ok)
                if ok is not None:
                    ok.click()

    def _load_settings(self):
        s = QgsSettings()
        self._enabled       = s.value(self._KEY_ENABLED,       False, type=bool)
        self._interval      = s.value(self._KEY_INTERVAL,      3600,  type=int)
        self._show_on_start = s.value(self._KEY_SHOW_ON_START, True,  type=bool)

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(self._KEY_ENABLED,       self._enabled)
        s.setValue(self._KEY_INTERVAL,      self._interval)
        s.setValue(self._KEY_SHOW_ON_START, self._show_on_start)

    def _notify(self):
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                pass
