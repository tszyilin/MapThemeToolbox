# -*- coding: utf-8 -*-
"""
Shared sync connection state.
The dialog writes here when connected; the toolbar button reads from here.
"""


class SyncConnection:
    """Singleton holding the active Excel ↔ GeoPackage connection."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.connected      = False
        self.file_path      = None
        self.layer_id       = None
        self.cols_to_sync   = []
        self.file_key_col   = None   # None = INSERT mode
        self.layer_key_fld  = None
        self.layer_name     = ""
        self.last_sync_msg  = ""     # last sync result string
        self._callbacks     = []     # notify toolbar when state changes

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

    def connect(self, file_path, layer_id, layer_name,
                cols_to_sync, file_key_col, layer_key_fld):
        self.connected     = True
        self.file_path     = file_path
        self.layer_id      = layer_id
        self.layer_name    = layer_name
        self.cols_to_sync  = cols_to_sync
        self.file_key_col  = file_key_col
        self.layer_key_fld = layer_key_fld
        self._notify()

    def disconnect(self):
        self.reset()
        self._notify()


# Module-level singleton — imported by both dialog and toolbox
CONNECTION = SyncConnection()
