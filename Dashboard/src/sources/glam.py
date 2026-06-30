"""GLAM NDVI client (NASA Harvest "GLAM API v2", https://api.glamdata.org).

State-level, corn-masked NDVI. No API key. Standard library only.

Notes from live testing:
- Trailing slashes are REQUIRED on every path.
- In /query/{product}/{date}/{cropmask}/{boundary_layer}/{feature_id}/ the
  boundary_layer is the boundary id (geoboundaries-usa-adm1), NOT "ndvi".
- Past 8-day composites are immutable -> cached forever, so only new composites
  are fetched on later runs (keeps "update every run" fast after the first build).
"""
import datetime
import urllib.parse

import cache
import http_util

BASE = "https://api.glamdata.org"
CROPMASK = "geoglam-bacs-maize"
BOUNDARY = "geoboundaries-usa-adm1"


def feature_map():
    """{state_name: feature_id} for US states (cached; rarely changes)."""
    cached = cache.get_json("glam:feature_map")
    if cached is not None:
        return cached
    url = f"{BASE}/boundary-features/{BOUNDARY}/"
    arr = http_util.get_json(url)
    fmap = {}
    for item in arr:
        name = item.get("feature_name")
        fid = item.get("feature_id")
        if name and fid is not None:
            fmap[name] = fid
    if fmap:
        cache.set_json("glam:feature_map", fmap)
    return fmap


def _doy(date_str):
    return datetime.date.fromisoformat(date_str).timetuple().tm_yday


def _composites(product, d0, d1, cacheable):
    """Return sorted [(date_str, doy, prelim)] for ``product`` in [d0, d1]."""
    key = f"glam:dates:{product}:{d0}:{d1}"
    if cacheable:
        hit = cache.get_json(key)
        if hit is not None:
            return [tuple(x) for x in hit]

    url = (f"{BASE}/datasets/?date_after={d0}&date_before={d1}"
           f"&product={urllib.parse.quote(product)}")
    out = []
    pages = 0
    while url and pages < 12:
        obj = http_util.get_json(url)
        for r in obj.get("results", []):
            if r.get("product_id") != product:
                continue
            ds = r.get("date")
            if not ds:
                continue
            try:
                out.append((ds, _doy(ds), bool(r.get("prelim"))))
            except (ValueError, TypeError):
                continue
        url = obj.get("next")
        pages += 1
    out.sort(key=lambda t: t[0])
    if cacheable:
        cache.set_json(key, out)
    return out


def _query_mean(product, date_str, feature_id, cacheable):
    key = f"glam:ndvi:{product}:{date_str}:{CROPMASK}:{feature_id}"
    if cacheable:
        hit = cache.get_json(key)
        if hit is not None:
            return hit.get("mean")
    url = (f"{BASE}/query/{product}/{date_str}/{CROPMASK}/"
           f"{BOUNDARY}/{feature_id}/")
    try:
        obj = http_util.get_json(url)
    except http_util.HttpError:
        return None
    mean = obj.get("mean")
    if mean is None:
        return None
    mean = round(float(mean), 3)
    if cacheable:
        cache.set_json(key, {"mean": mean})
    return mean


def _nearest(doy_map, doy, tol=4):
    if doy in doy_map:
        return doy_map[doy]
    best, best_d = None, tol + 1
    for k, v in doy_map.items():
        d = abs(k - doy)
        if d < best_d:
            best, best_d = v, d
    return best


def ndvi_for_state(cfg, feature_id, today=None):
    """Corn-masked NDVI for the current season with a prior-years baseline+anomaly."""
    if feature_id is None:
        return None
    product = cfg["ndvi_product"]
    start_month = int(cfg["ndvi_season_start_month"])
    baseline_years = int(cfg["ndvi_baseline_years"])
    max_comp = int(cfg["ndvi_max_composites"])
    today = today or datetime.date.today()

    season_start = datetime.date(today.year, start_month, 1)
    if today < season_start:
        # before this year's season: show last year's full season instead
        today = datetime.date(today.year - 1, 12, 31)
        season_start = datetime.date(today.year, start_month, 1)

    cur = _composites(product, season_start.isoformat(), today.isoformat(), cacheable=False)
    cur = cur[-max_comp:]
    if not cur:
        return None

    dates, values = [], []
    for ds, _doy_v, prelim in cur:
        v = _query_mean(product, ds, feature_id, cacheable=not prelim)
        dates.append(ds)
        values.append(v)

    baseline = [None] * len(cur)
    if baseline_years > 0:
        doy_maps = {}
        for k in range(1, baseline_years + 1):
            by = today.year - k
            comps = _composites(
                product,
                datetime.date(by, start_month, 1).isoformat(),
                datetime.date(by, today.month, today.day).isoformat(),
                cacheable=True,
            )
            doy_maps[by] = {doy: ds for ds, doy, _p in comps}
        for idx, (ds, doy_v, _p) in enumerate(cur):
            bvals = []
            for k in range(1, baseline_years + 1):
                by = today.year - k
                bds = _nearest(doy_maps.get(by, {}), doy_v)
                if bds:
                    bv = _query_mean(product, bds, feature_id, cacheable=True)
                    if bv is not None:
                        bvals.append(bv)
            if bvals:
                baseline[idx] = round(sum(bvals) / len(bvals), 3)

    anomaly = [
        round(v - b, 3) if (v is not None and b is not None) else None
        for v, b in zip(values, baseline)
    ]

    if not any(v is not None for v in values):
        return None

    label = "VIIRS" if product.startswith("vnp") else "MODIS"
    return {
        "dates": [d[5:] for d in dates],
        "values": values,
        "baseline": baseline,
        "anomaly": anomaly,
        "source": f"GLAM {label} NDVI (corn-masked)",
        "baseline_years": baseline_years,
    }
