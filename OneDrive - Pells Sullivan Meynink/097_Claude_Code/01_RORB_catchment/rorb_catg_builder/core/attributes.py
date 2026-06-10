from enum import Enum
from .geometry import Point, Line


class Node(Point):
    def __init__(self, name="", x=0.0, y=0.0):
        super().__init__(x, y)
        self._name = str(name)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, v):
        self._name = str(v)


class Basin(Node):
    def __init__(self, name="", x=0.0, y=0.0, area=0.0, fi=0.0):
        super().__init__(name, x, y)
        self._area = float(area)
        self._fi = float(fi)

    @property
    def area(self):
        return self._area

    @area.setter
    def area(self, v):
        self._area = float(v)

    @property
    def fi(self):
        return self._fi

    @fi.setter
    def fi(self, v):
        self._fi = float(v)

    def __str__(self):
        return f"Basin({self._name}, area={self._area:.4f}, fi={self._fi:.3f})"


class Confluence(Node):
    def __init__(self, name="", x=0.0, y=0.0, out=False):
        super().__init__(name, x, y)
        self._isOut = bool(out)

    @property
    def isOut(self):
        return self._isOut

    @isOut.setter
    def isOut(self, v):
        self._isOut = bool(v)

    def __str__(self):
        return f"Confluence({self._name}, out={self._isOut})"


class ReachType(Enum):
    NATURAL = 1
    UNLINED = 2
    LINED = 3
    DROWNED = 4


class Reach(Line):
    def __init__(self, name="", vector=None, rtype=None, slope=0.0):
        super().__init__(vector or [])
        self._name = str(name)
        self._type = rtype if rtype is not None else ReachType.NATURAL
        self._slope = float(slope)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, v):
        self._name = str(v)

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, v):
        self._type = v

    @property
    def slope(self):
        return self._slope

    @slope.setter
    def slope(self, v):
        self._slope = float(v)

    def getSlope(self):
        return self._slope

    def __str__(self):
        return f"Reach({self._name}, len={self.length():.1f}m, type={self._type.name})"
