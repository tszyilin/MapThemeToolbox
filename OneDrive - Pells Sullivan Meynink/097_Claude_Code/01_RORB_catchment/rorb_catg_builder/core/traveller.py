import numpy as np
from .attributes import Reach
from .catchment import Catchment


class Traveller:
    """Depth-first traversal of the catchment from outlet upward."""

    def __init__(self, catchment: Catchment):
        self._catchment = catchment
        self._colour = np.zeros(len(catchment._incidenceMatrixDS), dtype=int)
        self._us = catchment._incidenceMatrixUS
        self._ds = catchment._incidenceMatrixDS
        self._endSentinel = catchment._endSentinel
        self._pos = self._getStart()

    def _getStart(self):
        for i, row in enumerate(self._ds):
            if all(v == self._endSentinel for v in row):
                return i
        return 0

    def getNode(self, i):
        return self._catchment._vertices[i]

    def getReach(self, i) -> Reach:
        for j, val in enumerate(self._ds[i]):
            if val != self._endSentinel:
                return self._catchment._edges[j]
        raise KeyError(f"No downstream reach from node {i}")

    def top(self, i):
        """Most upstream unvisited node reachable from i."""
        for val in self._us[i]:
            if val != self._endSentinel and self._colour[val] == 0:
                return self.top(val)
        return i

    def up(self, i):
        return [v for v in self._us[i] if v != self._endSentinel]

    def down(self, i):
        for val in self._ds[i]:
            if val != self._endSentinel:
                return val
        return self._endSentinel

    def next(self):
        top = self.top(self._pos)
        if top == self._pos:
            self._colour[self._pos] = 1
            self._pos = self.down(self._pos)
        else:
            self._pos = top
        return self._pos
