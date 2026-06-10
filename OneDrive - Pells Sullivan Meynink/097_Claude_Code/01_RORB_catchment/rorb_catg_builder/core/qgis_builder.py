"""Builds pyromb objects from QGIS vector layers."""

from qgis.core import QgsWkbTypes

from .attributes import Basin, Confluence, Reach, ReachType
from .geometry import Point, polygon_area, polygon_centroid, dist


def _qgs_line_coords(geom):
    """Return list of (x, y) tuples from a QGIS line geometry (single or multi)."""
    wkb = geom.wkbType()
    if QgsWkbTypes.isMultiType(wkb):
        parts = geom.asMultiPolyline()
        if parts:
            return [(p.x(), p.y()) for p in parts[0]]
    else:
        pts = geom.asPolyline()
        return [(p.x(), p.y()) for p in pts]
    return []


def _qgs_point_coords(geom):
    """Return (x, y) from a QGIS point geometry."""
    if QgsWkbTypes.isMultiType(geom.wkbType()):
        pts = geom.asMultiPoint()
        p = pts[0] if pts else None
    else:
        p = geom.asPoint()
    return (p.x(), p.y()) if p else (0.0, 0.0)


def _qgs_polygon_coords(geom):
    """Return outer ring as list of (x,y) tuples from a QGIS polygon geometry."""
    wkb = geom.wkbType()
    if QgsWkbTypes.isMultiType(wkb):
        parts = geom.asMultiPolygon()
        ring = parts[0][0] if parts else []
    else:
        rings = geom.asPolygon()
        ring = rings[0] if rings else []
    return [(p.x(), p.y()) for p in ring]


def build_reaches(layer, fld_id, fld_slope, fld_type):
    """Build list of Reach objects from a QGIS line layer."""
    reaches = []
    for feat in layer.getFeatures():
        geom = feat.geometry()
        coords = _qgs_line_coords(geom)
        if not coords:
            continue
        name = str(feat[fld_id]) if fld_id else str(feat.id())
        slope = float(feat[fld_slope]) if fld_slope else 0.0
        rtype_val = int(feat[fld_type]) if fld_type else 1
        try:
            rtype = ReachType(rtype_val)
        except ValueError:
            rtype = ReachType.NATURAL
        reaches.append(Reach(name, coords, rtype, slope))
    return reaches


def build_confluences(layer, fld_id, fld_out):
    """Build list of Confluence objects from a QGIS point layer."""
    confluences = []
    for feat in layer.getFeatures():
        geom = feat.geometry()
        x, y = _qgs_point_coords(geom)
        name = str(feat[fld_id]) if fld_id else str(feat.id())
        out_val = feat[fld_out] if fld_out else 0
        is_out = bool(int(out_val)) if out_val is not None else False
        confluences.append(Confluence(name, x, y, is_out))
    return confluences


def build_basins(centroid_layer, basin_layer, fld_centroid_id, fld_fi):
    """
    Build Basin objects by nearest-neighbour matching centroids to basin polygons.
    Basin area is computed from polygon geometry (m² → km²).
    """
    # Pre-compute polygon centroids and areas
    poly_data = []
    for feat in basin_layer.getFeatures():
        coords = _qgs_polygon_coords(feat.geometry())
        pts = [Point(c[0], c[1]) for c in coords]
        # Use QGIS geometry area for accuracy (handles projections)
        area_m2 = feat.geometry().area()
        centroid_pt = feat.geometry().centroid().asPoint()
        poly_data.append({
            'area_km2': area_m2 / 1e6,
            'cx': centroid_pt.x(),
            'cy': centroid_pt.y(),
        })

    basins = []
    for feat in centroid_layer.getFeatures():
        geom = feat.geometry()
        x, y = _qgs_point_coords(geom)
        name = str(feat[fld_centroid_id]) if fld_centroid_id else str(feat.id())
        fi = float(feat[fld_fi]) if fld_fi else 0.0

        # find closest polygon by centroid distance
        best_idx = 0
        best_d = 1e18
        cp = Point(x, y)
        for k, pd in enumerate(poly_data):
            d = dist(cp, Point(pd['cx'], pd['cy']))
            if d < best_d:
                best_d = d
                best_idx = k

        area = poly_data[best_idx]['area_km2'] if poly_data else 0.0
        basins.append(Basin(name, x, y, area, fi))

    return basins
