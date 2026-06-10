import math


class Point:
    def __init__(self, x=0.0, y=0.0):
        self._x = float(x)
        self._y = float(y)

    def coordinates(self):
        return (self._x, self._y)

    def __str__(self):
        return f"[{self._x:.3f}, {self._y:.3f}]"


def _make_points(vector):
    return [Point(t[0], t[1]) for t in vector]


def seg_length(vertices):
    total = 0.0
    for i in range(len(vertices) - 1):
        x0, y0 = vertices[i].coordinates()
        x1, y1 = vertices[i + 1].coordinates()
        total += math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    return total


def dist(a, b):
    ax, ay = a.coordinates()
    bx, by = b.coordinates()
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)


def polygon_area(vertices):
    """Shoelace algorithm. vertices is a list of Point."""
    psum = nsum = 0.0
    n = len(vertices)
    for i in range(n):
        j = (i + 1) % n
        xi, yi = vertices[i].coordinates()
        xj, yj = vertices[j].coordinates()
        psum += xi * yj
        nsum += xj * yi
    return abs(0.5 * (psum - nsum))


def polygon_centroid(vertices):
    sumx = sumy = suma = 0.0
    for i in range(len(vertices) - 1):
        x0, y0 = vertices[i].coordinates()
        x1, y1 = vertices[i + 1].coordinates()
        cross = x0 * y1 - x1 * y0
        sumx += (x0 + x1) * cross
        sumy += (y0 + y1) * cross
        suma += cross
    A = 0.5 * suma
    if A == 0:
        xs = [v.coordinates()[0] for v in vertices]
        ys = [v.coordinates()[1] for v in vertices]
        return Point(sum(xs) / len(xs), sum(ys) / len(ys))
    return Point((1.0 / (6.0 * A)) * sumx, (1.0 / (6.0 * A)) * sumy)


class Line:
    def __init__(self, vector=None):
        pts = _make_points(vector or [])
        self._vector = pts
        self._end = max(len(pts) - 1, 0)
        self._length = seg_length(pts)

    def length(self):
        return self._length

    def getStart(self):
        return self._vector[0]

    def getEnd(self):
        return self._vector[self._end]

    def __len__(self):
        return self._end

    def __getitem__(self, i):
        return self._vector[i]

    def toVector(self):
        return self._vector
