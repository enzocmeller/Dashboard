"""Open-Meteo client: 16-day forecast, soil moisture, ERA5 climate normals, and
forecast-vs-normal anomalies on the 1-5 / 6-10 / 11-15 day windows.

No API key (non-commercial/free). HTTPS/443 JSON. Standard library only.
ERA5 normals are immutable, so they are cached permanently per location.
"""
import datetime
import urllib.parse

import cache
import http_util

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# root-zone soil-moisture layers (cm) and their thickness weights
_SM_LAYERS = [
    ("soil_moisture_0_to_1cm", 1),
    ("soil_moisture_1_to_3cm", 2),
    ("soil_moisture_3_to_9cm", 6),
    ("soil_moisture_9_to_27cm", 18),
]


def _url(base, params):
    return base + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def fetch_forecast(lat, lon):
    """One call returns the daily temp/precip forecast + hourly soil moisture."""
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "daily": "temperature_2m_mean,precipitation_sum",
        "hourly": ",".join(name for name, _w in _SM_LAYERS),
        "forecast_days": "16",
        "timezone": "auto",
    }
    return http_util.get_json(_url(FORECAST_URL, params))


def soil_moisture(forecast):
    """Daily root-zone (0-27 cm) volumetric soil moisture from the forecast."""
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    # accumulate per-day weighted sums
    day_acc = {}   # date -> [weighted_sum, weight_count]
    weights_total = sum(w for _n, w in _SM_LAYERS)
    per_hour = []
    for i, t in enumerate(times):
        num = 0.0
        wsum = 0
        for name, w in _SM_LAYERS:
            arr = hourly.get(name)
            if not arr or i >= len(arr) or arr[i] is None:
                continue
            num += arr[i] * w
            wsum += w
        if wsum == 0:
            continue
        val = num / wsum
        per_hour.append((t, val))
    for t, val in per_hour:
        d = t[:10]
        acc = day_acc.setdefault(d, [0.0, 0])
        acc[0] += val
        acc[1] += 1
    dates = sorted(day_acc)
    values = [round(day_acc[d][0] / day_acc[d][1], 3) for d in dates]
    if not values:
        return None
    return {
        "current": values[0],
        "dates": [d[5:] for d in dates],
        "values": values,
        "unit": "m³/m³",
    }


def _doy(date_str):
    return datetime.date.fromisoformat(date_str).timetuple().tm_yday


def _doy_climatology(daily, fields):
    """Build smoothed (±7 day) per-DOY normals for the requested daily fields."""
    times = daily.get("time") or []
    buckets = {f: [[] for _ in range(367)] for f in fields}
    for i, t in enumerate(times):
        try:
            d = _doy(t)
        except (ValueError, TypeError):
            continue
        for f in fields:
            arr = daily.get(f) or []
            if i < len(arr) and arr[i] is not None:
                buckets[f][d].append(arr[i])

    def base(lists):
        return [None if not lists[d] else sum(lists[d]) / len(lists[d]) for d in range(367)]

    def smooth(arr):
        out = [None] * 367
        for d in range(1, 367):
            win = [arr[((k - 1) % 366) + 1] for k in range(d - 7, d + 8)
                   if arr[((k - 1) % 366) + 1] is not None]
            out[d] = round(sum(win) / len(win), 3) if win else None
        return out

    return {f: smooth(base(buckets[f])) for f in fields}


def normals(lat, lon):
    """Smoothed day-of-year ERA5 1991-2020 normals (temp mean, precip). Cached forever."""
    key = f"normals:{round(lat, 2)}:{round(lon, 2)}"
    cached = cache.get_json(key)
    if cached is not None:
        return cached
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": "1991-01-01",
        "end_date": "2020-12-31",
        "daily": "temperature_2m_mean,precipitation_sum",
        "timezone": "auto",
    }
    data = http_util.get_json(_url(ARCHIVE_URL, params))
    clim = _doy_climatology(data.get("daily") or {}, ["temperature_2m_mean", "precipitation_sum"])
    result = {"temp": clim["temperature_2m_mean"], "precip": clim["precipitation_sum"]}
    cache.set_json(key, result)
    return result


def gdd_f(tmax_c, tmin_c):
    """Daily corn growing-degree-days (base 50 °F, cap 86 °F) from °C max/min."""
    if tmax_c is None or tmin_c is None:
        return 0.0
    tmax = min(tmax_c * 9 / 5 + 32, 86.0)
    tmin = max(tmin_c * 9 / 5 + 32, 50.0)
    return max(0.0, (tmax + tmin) / 2.0 - 50.0)


def gdd_normal(lat, lon):
    """Per-DOY GDD normal from a 10-year ERA5 window (lighter archive call). Cached."""
    key = f"gddnorm:{round(lat, 2)}:{round(lon, 2)}"
    cached = cache.get_json(key)
    if cached is not None:
        return cached
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": "2011-01-01",
        "end_date": "2020-12-31",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    }
    data = http_util.get_json(_url(ARCHIVE_URL, params))
    clim = _doy_climatology(data.get("daily") or {}, ["temperature_2m_max", "temperature_2m_min"])
    tmax, tmin = clim["temperature_2m_max"], clim["temperature_2m_min"]
    gdd = [round(gdd_f(tmax[d], tmin[d]), 2) for d in range(367)]
    cache.set_json(key, gdd)
    return gdd


def gdd_series(lat, lon, start_date, end_date):
    """Cumulative GDD (actual vs normal) from start_date to today.

    Actual comes from the FORECAST endpoint via past_days (avoids the heavily
    rate-limited archive endpoint); the normal is the cached gdd_normal.
    """
    key = f"gdd:{round(lat, 2)}:{round(lon, 2)}:{start_date}:{end_date}"
    cached = cache.get_json(key)
    if cached is not None:
        return cached

    start = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date)
    past = (end - start).days
    if past < 1:
        return None
    past = min(92, past)  # Open-Meteo forecast past_days cap

    # The normal needs the (rate-limited) archive; if it's unavailable we still
    # show actual accumulation from the forecast endpoint and fill normal later.
    try:
        gnorm = gdd_normal(lat, lon)
    except Exception:
        gnorm = None

    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "daily": "temperature_2m_max,temperature_2m_min",
        "past_days": str(past),
        "forecast_days": "1",
        "timezone": "auto",
    }
    data = http_util.get_json(_url(FORECAST_URL, params))
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []

    dates, actual_cum, normal_cum = [], [], []
    acc = nacc = 0.0
    for i, t in enumerate(times):
        if t > end_date:
            break  # actual only up to today
        if i >= len(tmax) or i >= len(tmin) or tmax[i] is None or tmin[i] is None:
            continue
        acc += gdd_f(tmax[i], tmin[i])
        dates.append(t)
        actual_cum.append(round(acc))
        if gnorm:
            try:
                nacc += gnorm[_doy(t)] or 0.0
            except (ValueError, IndexError, TypeError):
                pass
            normal_cum.append(round(nacc))
        else:
            normal_cum.append(None)

    if not dates:
        return None
    td = actual_cum[-1]
    ntd = normal_cum[-1] if gnorm else None
    result = {
        "dates": [d[5:] for d in dates],
        "actual_cum": actual_cum,
        "normal_cum": normal_cum,
        "to_date": td,
        "normal_to_date": ntd,
        "pct_of_normal": round(td / ntd * 100) if ntd else None,
        "through": dates[-1],
    }
    if gnorm:  # only cache the full (with-normal) result permanently
        cache.set_json(key, result)
    return result


def weather_anomaly(forecast, norm):
    """Forecast-minus-normal anomalies grouped into days 1-5 / 6-10 / 11-15."""
    daily = forecast.get("daily") or {}
    times = daily.get("time") or []
    temps = daily.get("temperature_2m_mean") or []
    precs = daily.get("precipitation_sum") or []
    if len(times) < 15 or not norm:
        return None

    windows = [(0, 5), (5, 10), (10, 15)]
    temp_out, precip_mm_out, precip_pct_out = [], [], []
    for start, end in windows:
        t_anoms, f_prec, n_prec = [], 0.0, 0.0
        for i in range(start, end):
            try:
                d = _doy(times[i])
            except (ValueError, IndexError, TypeError):
                continue
            tn = norm["temp"][d]
            pn = norm["precip"][d]
            if i < len(temps) and temps[i] is not None and tn is not None:
                t_anoms.append(temps[i] - tn)
            if i < len(precs) and precs[i] is not None:
                f_prec += precs[i]
            if pn is not None:
                n_prec += pn
        temp_out.append(round(sum(t_anoms) / len(t_anoms), 2) if t_anoms else None)
        precip_mm_out.append(round(f_prec - n_prec, 1))
        precip_pct_out.append(round(f_prec / n_prec * 100, 0) if n_prec > 0 else None)

    return {
        "windows": ["1-5 d", "6-10 d", "11-15 d"],
        "temp": temp_out,
        "precip_mm": precip_mm_out,
        "precip_pct": precip_pct_out,
    }
