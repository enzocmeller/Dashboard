"""Compute a representative "corn point" (lat/lon) for each state.

The point is the corn-PRODUCTION-weighted centroid of the state's top counties,
so weather / soil-moisture / NDVI queries land where corn is actually grown.
Falls back to the geographic centroid of the state's counties when production
data is unavailable.

County centroids come from the bundled Census Gazetteer file
(``county_centroids.csv``: geoid, usps, name, lat, lon) — no network needed.
"""
import csv
import os

_CENTROIDS = None  # fips5 -> (lat, lon)
_BY_STATE = None   # usps -> list of (lat, lon)


def _load():
    global _CENTROIDS, _BY_STATE
    if _CENTROIDS is not None:
        return
    _CENTROIDS = {}
    _BY_STATE = {}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "county_centroids.csv")
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (ValueError, KeyError):
                continue
            fips = row["geoid"].strip()
            _CENTROIDS[fips] = (lat, lon)
            _BY_STATE.setdefault(row["usps"].strip(), []).append((lat, lon))


def state_fallback_point(usps):
    """Plain geographic centroid of a state's counties (no production weighting)."""
    _load()
    pts = _BY_STATE.get(usps, [])
    if not pts:
        return None
    lat = sum(p[0] for p in pts) / len(pts)
    lon = sum(p[1] for p in pts) / len(pts)
    return {"lat": round(lat, 4), "lon": round(lon, 4), "based_on_counties": 0}


def production_weighted_point(usps, county_production, top_n=15):
    """county_production: list of (fips5, production_bu). Returns the weighted point."""
    _load()
    ranked = sorted(
        [(f, v) for f, v in county_production if f in _CENTROIDS and v > 0],
        key=lambda t: t[1],
        reverse=True,
    )[:top_n]
    if not ranked:
        return state_fallback_point(usps)

    total = sum(v for _f, v in ranked)
    lat = sum(_CENTROIDS[f][0] * v for f, v in ranked) / total
    lon = sum(_CENTROIDS[f][1] * v for f, v in ranked) / total
    return {"lat": round(lat, 4), "lon": round(lon, 4), "based_on_counties": len(ranked)}
