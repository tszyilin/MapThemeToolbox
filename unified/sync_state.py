# -*- coding: utf-8 -*-
"""
Sync connection state — supports multiple named Excel ↔ GeoPackage connections.

REGISTRY  — module-level ConnectionRegistry singleton.
            Import and use this everywhere instead of the old CONNECTION.

Connections are stored per-project (in the .qgz/.qgs file) so each project
has its own independent set of sync connections.
"""

import json
from qgis.core import QgsProject

_PROJ_SCOPE = "MapThemeToolbox"
_PROJ_KEY   = "sync_connections_v2"


class SyncConnection:
    """One named Excel ↔ GeoPackage connection."""

    def __init__(self, name="New Connection"):
        self.name          = name
        self.connected     = False
        self.file_path     = None
        self.layer_id      = None
        self.layer_name    = ""
        self.cols_to_sync  = []
        self.last_sync_msg = ""

    # ── Persistence ───────────────────────────────────────────────────────────

    def to_dict(self):
        return {
            "name":          self.name,
            "connected":     self.connected,
            "file_path":     self.file_path,
            "layer_id":      self.layer_id,
            "layer_name":    self.layer_name,
            "cols_to_sync":  self.cols_to_sync,
            "last_sync_msg": self.last_sync_msg,
        }

    @classmethod
    def from_dict(cls, d):
        c = cls(d.get("name", "Connection"))
        c.connected     = d.get("connected", False)
        c.file_path     = d.get("file_path")
        c.layer_id      = d.get("layer_id")
        c.layer_name    = d.get("layer_name", "")
        c.cols_to_sync  = d.get("cols_to_sync", [])
        c.last_sync_msg = d.get("last_sync_msg", "")
        return c


class ConnectionRegistry:
    """
    Manages a list of SyncConnection objects.
    Persists state to QgsSettings so connections survive QGIS restarts.
    Fires registered callbacks whenever any connection changes.
    """

    def __init__(self):
        self._connections = []
        self._callbacks   = []
        self._load()
        QgsProject.instance().readProject.connect(self._on_project_read)
        QgsProject.instance().cleared.connect(self._on_project_cleared)

    # ── Connection management ─────────────────────────────────────────────────

    def connections(self):
        return list(self._connections)

    def add(self, name="New Connection"):
        conn = SyncConnection(name)
        self._connections.append(conn)
        self._save()
        self._notify()
        return conn

    def remove(self, conn):
        if conn in self._connections:
            self._connections.remove(conn)
            self._save()
            self._notify()

    def update(self, conn=None):
        """Call after mutating any SyncConnection to persist and notify."""
        self._save()
        self._notify()

    # ── Queries ───────────────────────────────────────────────────────────────

    def any_connected(self):
        return any(c.connected for c in self._connections)

    def connected_list(self):
        return [c for c in self._connections if c.connected]

    # ── Project signals ───────────────────────────────────────────────────────

    def _on_project_read(self, _doc=None):
        self._load()
        self._notify()

    def _on_project_cleared(self):
        self._connections = []
        self._notify()

    def cleanup(self):
        """Disconnect project signals — call from plugin.unload()."""
        try:
            QgsProject.instance().readProject.disconnect(self._on_project_read)
            QgsProject.instance().cleared.disconnect(self._on_project_cleared)
        except Exception:
            pass

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def register_callback(self, fn):
        if fn not in self._callbacks:
            self._callbacks.append(fn)

    def unregister_callback(self, fn):
        self._callbacks = [f for f in self._callbacks if f is not fn]

    def _notify(self):
        for fn in list(self._callbacks):
            try:
                fn()
            except Exception:
                pass

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self):
        QgsProject.instance().writeEntry(
            _PROJ_SCOPE, _PROJ_KEY,
            json.dumps([c.to_dict() for c in self._connections], ensure_ascii=False)
        )

    def _load(self):
        raw, _ = QgsProject.instance().readEntry(_PROJ_SCOPE, _PROJ_KEY, "")
        if not raw:
            self._connections = []
            return
        try:
            self._connections = [SyncConnection.from_dict(d)
                                 for d in json.loads(raw)]
        except Exception:
            self._connections = []


# Module-level singleton
REGISTRY = ConnectionRegistry()

# ---------------------------------------------------------------------------
# Backward-compat shim so any code that still does
#   from .sync_state import CONNECTION
# gets a dummy object that does nothing harmful.
# ---------------------------------------------------------------------------
class _LegacyShim:
    connected   = False
    file_path   = None
    layer_name  = ""
    layer_id    = None
    cols_to_sync = []
    last_sync_msg = ""
    def register_callback(self, fn):   REGISTRY.register_callback(fn)
    def unregister_callback(self, fn): REGISTRY.unregister_callback(fn)

CONNECTION = _LegacyShim()
