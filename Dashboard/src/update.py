"""Main entry point: gather all data for every state, then rebuild index.html.

Run:  python src/update.py
Re-running refreshes the live data and regenerates the dashboard.
"""
import datetime
import json
import os
import sys
import time

# make sibling modules importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build
import cache
import config
import http_util
from compute import stats
from geo import corn_points
from sources import glam, nass, openmeteo
from states import BY_USPS, resolve


def _log(msg):
    print(msg, flush=True)


def build_state(cfg, key, st, fmap, today):
    cy = today.year
    res = {"name": st.name, "usps": st.usps, "has_data": False}

    # --- corn-production-weighted point (county data lags ~1-2 yrs) ---
    prod = []
    for y in (cy - 1, cy - 2, cy - 3):
        prod = nass.county_production(key, st.usps, y)
        if prod:
            break
    point = (corn_points.production_weighted_point(st.usps, prod, cfg["top_counties_for_centroid"])
             if prod else corn_points.state_fallback_point(st.usps))
    res["corn_point"] = point

    # --- phenology (this year, fall back to last year early in season) ---
    res["phenology"] = nass.phenology(key, st.usps, cy) or nass.phenology(key, st.usps, cy - 1)

    # --- condition: donut + G+E line + season averages ---
    cond = nass.condition_history(key, st.usps, cy - int(cfg["condition_history_years"]))
    if cond:
        res["condition_latest"] = cond["latest"]
        res["ge_line"] = cond["ge_line"]

    # --- yield + trend + detrended deviation ---
    ys = nass.yield_series(key, st.usps, cfg["yield_start_year"])
    if ys and len(ys["years"]) >= 2:
        fit = stats.linear_trend(ys["years"], ys["values"])
        if fit:
            slope, intercept = fit
            res["yield"] = {
                "years": ys["years"],
                "values": ys["values"],
                "trend": stats.trend_line(ys["years"], slope, intercept),
            }
            res["yield_deviation"] = {
                "years": ys["years"],
                "residuals": stats.detrend(ys["years"], ys["values"], slope, intercept),
            }

    # --- correlation: season G+E vs DETRENDED yield (by year) ---
    # Raw yield trends upward, which would swamp the signal, so we correlate
    # against the yield deviation (residual from trend) computed above.
    dev = res.get("yield_deviation")
    if cond and dev:
        resid_by_year = {yr: rv for yr, rv in zip(dev["years"], dev["residuals"])
                         if rv is not None}
        pts, xs, yv = [], [], []
        for yr, ge in sorted(cond["season_ge_by_year"].items()):
            if yr in resid_by_year:
                pts.append([ge, resid_by_year[yr]])
                xs.append(ge)
                yv.append(resid_by_year[yr])
        if len(pts) >= 3:
            res["correlation"] = {
                "points": pts,
                "line": stats.regression_endpoints(xs, yv),
                "r": stats.pearson(xs, yv),
                "n": len(pts),
            }

    # --- weather + soil moisture at the corn point ---
    if point:
        try:
            fc = openmeteo.fetch_forecast(point["lat"], point["lon"])
            res["soil_moisture"] = openmeteo.soil_moisture(fc)
            norm = openmeteo.normals(point["lat"], point["lon"])
            res["weather_anomaly"] = openmeteo.weather_anomaly(fc, norm)
        except Exception as exc:  # best-effort; needs the (rate-limited) archive
            _log(f"    ! weather failed for {st.usps}: {exc}")
        # GDD is independent (actual from the forecast endpoint), so it survives
        # a weather/normals failure on its own.
        try:
            gstart = datetime.date(today.year, int(cfg["gdd_start_month"]), 1)
            if today >= gstart:
                res["gdd"] = openmeteo.gdd_series(
                    point["lat"], point["lon"], gstart.isoformat(), today.isoformat())
        except Exception as exc:
            _log(f"    ! GDD failed for {st.usps}: {exc}")

    # --- NDVI (GLAM, corn-masked) ---
    fid = fmap.get(st.name)
    if fid is not None:
        try:
            res["ndvi"] = glam.ndvi_for_state(cfg, fid, today)
        except Exception as exc:
            _log(f"    ! NDVI failed for {st.usps}: {exc}")

    res["has_data"] = any(
        res.get(k) for k in
        ("phenology", "condition_latest", "yield", "ndvi", "soil_moisture")
    )
    return res


def _weights(ranking):
    return {r["usps"]: r["bu"] for r in ranking if r.get("bu")}


def _wavg_series(out, weights, field, label_key, value_keys):
    """Production-weighted average of a per-state series, aligned by label."""
    agg = {}
    for usps, w in weights.items():
        st = out.get(usps)
        ser = st.get(field) if st else None
        if not ser:
            continue
        for i, lab in enumerate(ser.get(label_key) or []):
            slot = agg.setdefault(lab, {vk: [] for vk in value_keys})
            for vk in value_keys:
                arr = ser.get(vk) or []
                if i < len(arr) and arr[i] is not None:
                    slot[vk].append((w, arr[i]))
    if not agg:
        return None
    labels = sorted(agg.keys())
    res = {label_key: labels}
    for vk in value_keys:
        out_vals = []
        for lab in labels:
            pairs = agg[lab][vk]
            tw = sum(w for w, _ in pairs)
            out_vals.append(round(sum(w * v for w, v in pairs) / tw, 3) if tw > 0 else None)
        res[vk] = out_vals
    return res


def _wavg_weather(out, weights):
    keys = ["temp", "precip_mm", "precip_pct"]
    acc = {k: [[] for _ in range(3)] for k in keys}
    for usps, w in weights.items():
        st = out.get(usps)
        wx = st.get("weather_anomaly") if st else None
        if not wx:
            continue
        for k in keys:
            arr = wx.get(k) or []
            for i in range(min(3, len(arr))):
                if arr[i] is not None:
                    acc[k][i].append((w, arr[i]))
    res, any_data = {"windows": ["1-5 d", "6-10 d", "11-15 d"]}, False
    for k in keys:
        vals = []
        for i in range(3):
            pairs = acc[k][i]
            tw = sum(w for w, _ in pairs)
            if tw > 0:
                vals.append(round(sum(w * v for w, v in pairs) / tw, 1))
                any_data = True
            else:
                vals.append(None)
        res[k] = vals
    return res if any_data else None


def build_national_nass(cfg, key, today, natl, prod_year):
    """National NASS half of the 'United States' view — fetched EARLY (freshest)."""
    cy = today.year
    res = {"name": "United States", "usps": "US", "has_data": True,
           "is_national": True, "corn_point": None}

    res["phenology"] = nass.phenology(key, None, cy) or nass.phenology(key, None, cy - 1)
    cond = nass.condition_history(key, None, cy - int(cfg["condition_history_years"]))
    if cond:
        res["condition_latest"] = cond["latest"]
        res["ge_line"] = cond["ge_line"]

    ys = nass.yield_series(key, None, cfg["yield_start_year"])
    if ys and len(ys["years"]) >= 2:
        fit = stats.linear_trend(ys["years"], ys["values"])
        if fit:
            slope, intercept = fit
            res["yield"] = {"years": ys["years"], "values": ys["values"],
                            "trend": stats.trend_line(ys["years"], slope, intercept)}
            res["yield_deviation"] = {"years": ys["years"],
                                      "residuals": stats.detrend(ys["years"], ys["values"], slope, intercept)}

    dev = res.get("yield_deviation")
    if cond and dev:
        resid = {yr: rv for yr, rv in zip(dev["years"], dev["residuals"]) if rv is not None}
        pts, xs, yv = [], [], []
        for yr, ge in sorted(cond["season_ge_by_year"].items()):
            if yr in resid:
                pts.append([ge, resid[yr]])
                xs.append(ge)
                yv.append(resid[yr])
        if len(pts) >= 3:
            res["correlation"] = {"points": pts, "line": stats.regression_endpoints(xs, yv),
                                  "r": stats.pearson(xs, yv), "n": len(pts)}

    res["production"] = None  # flagged national -> renderProd shows the leaderboard
    res["national_production_bu"] = natl
    res["production_year"] = prod_year
    return res


def national_aggregates(res, out, ranking):
    """Add production-weighted geo aggregates (soil/weather/NDVI/GDD) to the national view."""
    weights = _weights(ranking)
    soil = _wavg_series(out, weights, "soil_moisture", "dates", ["values"])
    if soil:
        cur = [(weights[u], out[u]["soil_moisture"]["current"]) for u in weights
               if out.get(u) and out[u].get("soil_moisture")
               and out[u]["soil_moisture"].get("current") is not None]
        if cur:
            tw = sum(w for w, _ in cur)
            soil["current"] = round(sum(w * v for w, v in cur) / tw, 3)
        soil["unit"] = "m³/m³"
    res["soil_moisture"] = soil

    res["weather_anomaly"] = _wavg_weather(out, weights)

    ndvi = _wavg_series(out, weights, "ndvi", "dates", ["values", "baseline", "anomaly"])
    if ndvi:
        ndvi["source"] = "GLAM VIIRS NDVI (corn-masked) · national, production-weighted"
        for u in weights:
            st = out.get(u)
            if st and st.get("ndvi") and st["ndvi"].get("baseline_years"):
                ndvi["baseline_years"] = st["ndvi"]["baseline_years"]
                break
    res["ndvi"] = ndvi

    gdd = _wavg_series(out, weights, "gdd", "dates", ["actual_cum", "normal_cum"])
    if gdd and gdd["dates"]:
        gdd["to_date"] = gdd["actual_cum"][-1]
        gdd["normal_to_date"] = gdd["normal_cum"][-1]
        gdd["pct_of_normal"] = (round(gdd["to_date"] / gdd["normal_to_date"] * 100)
                                if gdd["normal_to_date"] else None)
    res["gdd"] = gdd
    return res


def _rebuild_only(cfg):
    """Regenerate index.html from the last data snapshot — no network calls.
    Use after editing the template/styling:  python src/update.py --rebuild
    """
    snap = os.path.join(cfg["data_dir"], "dashboard_data.json")
    if not os.path.exists(snap):
        _log("No data/dashboard_data.json yet — run a normal update first.")
        return 1
    with open(snap, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    out_path = build.render(cfg, payload)
    _log(f"Rebuilt dashboard from cached data: {out_path}")
    return 0


def main():
    cfg = config.load()

    if "--rebuild" in sys.argv:
        return _rebuild_only(cfg)

    try:
        key = config.require_nass_key(cfg)
    except config.ConfigError as exc:
        _log("ERROR: " + str(exc))
        return 2

    http_util.configure(
        ca_bundle=cfg["ca_bundle"],
        delay=cfg["request_delay_seconds"],
        timeout=cfg["request_timeout_seconds"],
        retries=cfg["request_retries"],
    )
    cache.init(cfg["data_dir"])

    today = datetime.date.today()
    sts = resolve(cfg["states"])
    _log(f"Gathering corn data for {len(sts)} states (first run is slower; "
         f"later runs reuse the cache)...")

    try:
        fmap = glam.feature_map()
    except Exception as exc:
        _log(f"  ! GLAM feature map unavailable ({exc}); NDVI will be skipped.")
        fmap = {}

    # --- US production share + ranking (1-2 calls total) ---
    prod_lookup, ranking, prod_year, natl = {}, [], None, None
    prod_by_state = {}
    for y in (today.year - 1, today.year - 2, today.year - 3):
        try:
            prod_by_state = nass.all_state_production(key, y)
        except nass.NassAuthError as exc:
            _log("ERROR: " + str(exc))
            return 2
        if prod_by_state:
            prod_year = y
            break
    if prod_year:
        try:
            natl = nass.national_production(key, prod_year)
        except Exception:
            natl = None
        if not natl:
            natl = sum(prod_by_state.values())
        ordered = sorted(((us, bu) for us, bu in prod_by_state.items() if us in BY_USPS),
                         key=lambda kv: kv[1], reverse=True)
        for rnk, (us, bu) in enumerate(ordered, 1):
            ranking.append({"usps": us, "name": BY_USPS[us].name, "bu": bu,
                            "share": round(bu / natl * 100, 2), "rank": rnk})
        prod_lookup = {r["usps"]: {"bu": r["bu"], "share": r["share"], "rank": r["rank"],
                                   "of": len(ranking), "year": prod_year} for r in ranking}
        _log(f"  production: ranked {len(ranking)} states for {prod_year} "
             f"(US total {natl:,.0f} bu)")

    # national NASS first, while the API is freshest (geo aggregates added later)
    us_national = None
    try:
        us_national = build_national_nass(cfg, key, today, natl, prod_year)
        _log("  fetched national 'United States' NASS data")
    except nass.NassAuthError as exc:
        _log("ERROR: " + str(exc))
        return 2
    except Exception as exc:
        _log(f"  ! national NASS failed: {exc}")

    out = {}
    t0 = time.time()
    for i, st in enumerate(sts, 1):
        _log(f"[{i:>2}/{len(sts)}] {st.name} ...")
        try:
            out[st.usps] = build_state(cfg, key, st, fmap, today)
        except nass.NassAuthError as exc:
            _log("ERROR: " + str(exc))
            return 2
        except Exception as exc:
            _log(f"    ! {st.usps} failed: {exc}")
            out[st.usps] = {"name": st.name, "usps": st.usps, "has_data": False}

    # attach production share/rank to each state
    for us, pd in prod_lookup.items():
        if us in out:
            out[us]["production"] = pd
            out[us]["has_data"] = True

    # finalize the national view with production-weighted geo aggregates
    if us_national is not None:
        try:
            national_aggregates(us_national, out, ranking)
        except Exception as exc:
            _log(f"  ! national aggregates failed: {exc}")
        out["US"] = us_national
        _log("  built national 'United States' view")

    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "states": out,
        "production": {"year": prod_year, "national_bu": natl, "ranking": ranking},
        "attribution": {
            "usda": "USDA NASS Quick Stats",
            "weather": "Open-Meteo (CC-BY 4.0, ERA5)",
            "ndvi": "NASA Harvest GLAM",
        },
    }

    os.makedirs(cfg["data_dir"], exist_ok=True)
    with open(os.path.join(cfg["data_dir"], "dashboard_data.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)

    out_path = build.render(cfg, payload)
    n_data = sum(1 for s in out.values() if s.get("has_data"))
    _log(f"\nDone in {time.time()-t0:.0f}s. {n_data}/{len(sts)} states have data.")
    _log(f"Dashboard written to: {out_path}")
    _log("Open index.html in your browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
