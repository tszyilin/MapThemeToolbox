import numpy as np
from .geometry import dist
from .attributes import Confluence


class Catchment:
    """Catchment tree of nodes (basins + confluences) connected by reaches."""

    def __init__(self, confluences=None, basins=None, reaches=None):
        self._edges = reaches or []
        self._vertices = (confluences or []) + (basins or [])
        self._incidenceMatrixDS = []
        self._incidenceMatrixUS = []
        self._out = 0
        self._endSentinel = -1

    def connect(self):
        """Nearest-neighbour topology connect. Returns (DS, US) incidence matrices."""
        verts = self._vertices
        edges = self._edges
        nv = len(verts)
        ne = len(edges)

        conn = np.zeros((nv, ne), dtype=int)
        for j, edge in enumerate(edges):
            s = edge.getStart()
            e = edge.getEnd()
            min_s = min_e = 1e18
            cs = ce = 0
            for i, v in enumerate(verts):
                ds = dist(v, s)
                de = dist(v, e)
                if ds < min_s:
                    cs = i; min_s = ds
                if de < min_e:
                    ce = i; min_e = de
            conn[cs][j] = 1
            conn[ce][j] = 2

        for k, v in enumerate(verts):
            if isinstance(v, Confluence) and v.isOut:
                self._out = k
                break

        sentinel = self._endSentinel
        newDS = np.full((nv, ne), sentinel, dtype=int)
        newUS = np.full((nv, ne), sentinel, dtype=int)
        colour = np.zeros((nv, ne), dtype=int)

        queue = [(self._out, 0)]
        while queue:
            u = queue.pop()
            idxi, j = u
            for k in range(ne):
                idxj = j % ne
                if conn[idxi][idxj] > 0 and colour[idxi][idxj] == 0:
                    colour[idxi][idxj] = 1
                    queue.append((idxi, idxj))
                j += 1

            i2 = u[0]
            idxj = u[1]
            for _ in range(nv):
                idxi2 = i2 % nv
                if conn[idxi2][idxj] > 0 and colour[idxi2][idxj] == 0:
                    colour[idxi2][idxj] = 1
                    queue.append((idxi2, idxj))
                    newUS[u[0]][u[1]] = idxi2
                    newDS[idxi2][idxj] = u[0]
                i2 += 1

        self._incidenceMatrixDS = newDS
        self._incidenceMatrixUS = newUS
        return (newDS, newUS)
