"""USDA NASS Quick Stats client (corn). Standard library only.

Single host: https://quickstats.nass.usda.gov/api  (HTTPS/443, key required).
Per-state queries are small (well under the 50,000-row cap), so we query one
state at a time and never need paging.
"""
import datetime
import urllib.parse

import http_util

BASE = "https://quickstats.nass.usda.gov/api/api_GET/"

COMMON = {
    "source_desc": "SURVEY",
    "sector_desc": "CROPS",
    "commodity_desc": "CORN",
    "format": "JSON",
}


class NassAuthError(Exception):
    pass


def _scope(state_alpha):
    """STATE+state filter, or NATIONAL when state_alpha is None (US-wide)."""
    if state_alpha:
        return {"agg_level_desc": "STATE", "state_alpha": state_alpha}
    return {"agg_level_desc": "NATIONAL"}


def _build_url(key, params):
    q = {"key": key}
    q.update(COMMON)
    q.update(params)
    # NASS wants spaces/commas literally encoded; urlencode with quote_via handles it.
    return BASE + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def _api_get(key, params):
    """Return the list of records, or [] when nothing matches the query."""
    url = _build_url(key, params)
    try:
        obj = http_util.get_json(url)
    except http_util.HttpError as exc:
        body = str(exc).lower()
        if exc.status == 401 or "unauthorized" in body or "api key" in body:
            raise NassAuthError(
                "USDA NASS rejected the API key (401/unauthorized). "
                "Check nass_api_key in config.json."
            )
        # 400 with no matching records is normal for sparse states.
        return []
    if isinstance(obj, dict):
        if "data" in obj:
            return obj["data"]
        if "error" in obj:
            return []
    return []


# ----------------------------------------------------------------------------
# value parsing
# ----------------------------------------------------------------------------
def _num(value):
    """Parse a NASS Value string. Suppressed markers -> None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s or s.startswith("(") or s.upper() in ("", "NA", "D", "Z"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _week_num(week_ending):
    """ISO week number from a YYYY-MM-DD week_ending date (for cross-year align)."""
    try:
        d = datetime.date.fromisoformat(week_ending)
        return d.isocalendar()[1]
    except (ValueError, TypeError):
        return None


def _condition_cat(short_desc):
    s = (short_desc or "").upper()
    if "VERY POOR" in s:
        return "very_poor"
    if "EXCELLENT" in s:
        return "excellent"
    if "GOOD" in s:
        return "good"
    if "FAIR" in s:
        return "fair"
    if "POOR" in s:
        return "poor"
    return None


def _progress_stage(short_desc):
    s = (short_desc or "").upper()
    if "PLANTED" in s:
        return "planted"
    if "SILKING" in s:
        return "silking"
    if "DOUGH" in s:
        return "dough"
    if "MATURE" in s:
        return "mature"
    return None


# ----------------------------------------------------------------------------
# panels 3: phenology (current snapshot)
# ----------------------------------------------------------------------------
def phenology(key, usps, year):
    params = {"statisticcat_desc": "PROGRESS", "year": str(year)}
    params.update(_scope(usps))
    rows = _api_get(key, params)
    latest = {}   # stage -> (week_ending, value)
    for r in rows:
        stage = _progress_stage(r.get("short_desc"))
        if not stage:
            continue
        wk = r.get("week_ending")
        val = _num(r.get("Value"))
        if wk is None or val is None:
            continue
        if stage not in latest or wk > latest[stage][0]:
            latest[stage] = (wk, val)
    if not latest:
        return None
    as_of = max(v[0] for v in latest.values())
    return {
        "as_of": as_of,
        "planted": latest.get("planted", (None, None))[1],
        "silking": latest.get("silking", (None, None))[1],
        "dough": latest.get("dough", (None, None))[1],
        "mature": latest.get("mature", (None, None))[1],
    }


# ----------------------------------------------------------------------------
# panels 4 + 5 + 8: condition (current donut, G+E line w/ bands, season averages)
# ----------------------------------------------------------------------------
def condition_history(key, usps, start_year):
    """Return weekly condition for start_year..now in one call, processed into:
        {
          latest: {week_ending, excellent, good, fair, poor, very_poor, ge},
          ge_line: {weeks, current, min, median, max},
          season_ge_by_year: {year: mean_ge},   # for the correlation panel
        }
    """
    params = {"statisticcat_desc": "CONDITION", "year__GE": str(start_year)}
    params.update(_scope(usps))
    rows = _api_get(key, params)
    if not rows:
        return None

    # group by (year, week_ending) -> {category: value}
    weeks = {}
    for r in rows:
        cat = _condition_cat(r.get("short_desc"))
        val = _num(r.get("Value"))
        wk = r.get("week_ending")
        yr = r.get("year")
        if not cat or val is None or not wk or not yr:
            continue
        try:
            yr = int(yr)
        except (ValueError, TypeError):
            continue
        weeks.setdefault((yr, wk), {})[cat] = val

    if not weeks:
        return None

    # per-week G+E
    ge_records = []  # (year, week_ending, iso_week, ge, cats)
    for (yr, wk), cats in weeks.items():
        ge = (cats.get("good") or 0) + (cats.get("excellent") or 0)
        ge_records.append((yr, wk, _week_num(wk), round(ge, 1), cats))

    current_year = max(yr for yr, *_ in ge_records)

    # latest snapshot (most recent week of the most recent year)
    cur_recs = sorted([r for r in ge_records if r[0] == current_year], key=lambda r: r[1])
    latest_rec = cur_recs[-1]
    lc = latest_rec[4]
    latest = {
        "week_ending": latest_rec[1],
        "excellent": lc.get("excellent"),
        "good": lc.get("good"),
        "fair": lc.get("fair"),
        "poor": lc.get("poor"),
        "very_poor": lc.get("very_poor"),
        "ge": latest_rec[3],
    }

    # historical min/median/max by iso-week (years before current)
    from compute import stats as _st
    hist_by_week = {}
    for yr, wk, iso, ge, _cats in ge_records:
        if yr < current_year and iso is not None:
            hist_by_week.setdefault(iso, []).append(ge)

    # current-season line + aligned bands
    weeks_labels, current_vals, mins, meds, maxs = [], [], [], [], []
    for yr, wk, iso, ge, _cats in cur_recs:
        weeks_labels.append(wk[5:])  # MM-DD
        current_vals.append(ge)
        mn, md, mx = _st.safe_stats(hist_by_week.get(iso, []))
        mins.append(mn)
        meds.append(md)
        maxs.append(mx)

    # season average G+E per year (for correlation vs yield)
    season_ge_by_year = {}
    by_year = {}
    for yr, wk, iso, ge, _cats in ge_records:
        by_year.setdefault(yr, []).append(ge)
    for yr, vals in by_year.items():
        season_ge_by_year[yr] = round(sum(vals) / len(vals), 1)

    return {
        "latest": latest,
        "ge_line": {
            "weeks": weeks_labels,
            "current": current_vals,
            "min": mins,
            "median": meds,
            "max": maxs,
            "current_year": current_year,
        },
        "season_ge_by_year": season_ge_by_year,
    }


# ----------------------------------------------------------------------------
# panels 6 + 7: yield (curve + trend) and detrended deviation
# ----------------------------------------------------------------------------
def yield_series(key, usps, start_year):
    params = {
        "statisticcat_desc": "YIELD",
        "short_desc": "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE",
        "freq_desc": "ANNUAL",
        "year__GE": str(start_year),
    }
    params.update(_scope(usps))
    rows = _api_get(key, params)
    by_year = {}
    for r in rows:
        val = _num(r.get("Value"))
        yr = r.get("year")
        if val is None or not yr:
            continue
        try:
            yr = int(yr)
        except (ValueError, TypeError):
            continue
        ref = (r.get("reference_period_desc") or "").upper()
        # prefer the final annual ("YEAR") row if duplicates appear
        if yr not in by_year or ref == "YEAR":
            by_year[yr] = val
    if not by_year:
        return None
    years = sorted(by_year)
    return {"years": years, "values": [by_year[y] for y in years]}


# ----------------------------------------------------------------------------
# corn-region weighting: county production -> top counties
# ----------------------------------------------------------------------------
def all_state_production(key, year):
    """One call: {state_alpha: corn grain production (bu)} for every state in ``year``."""
    rows = _api_get(key, {
        "statisticcat_desc": "PRODUCTION",
        "agg_level_desc": "STATE",
        "short_desc": "CORN, GRAIN - PRODUCTION, MEASURED IN BU",
        "year": str(year),
    })
    best = {}  # usps -> (is_year_ref, value) ; prefer reference_period_desc == YEAR
    for r in rows:
        val = _num(r.get("Value"))
        us = (r.get("state_alpha") or "").strip().upper()
        if val is None or not us:
            continue
        is_year = (r.get("reference_period_desc") or "").upper() == "YEAR"
        if us not in best or (is_year and not best[us][0]):
            best[us] = (is_year, val)
    return {us: v for us, (_iy, v) in best.items()}


def national_production(key, year):
    """US total corn grain production (bu) for ``year``, or None."""
    rows = _api_get(key, {
        "statisticcat_desc": "PRODUCTION",
        "agg_level_desc": "NATIONAL",
        "short_desc": "CORN, GRAIN - PRODUCTION, MEASURED IN BU",
        "year": str(year),
    })
    for want_year in (True, False):
        for r in rows:
            is_year = (r.get("reference_period_desc") or "").upper() in ("YEAR", "")
            if is_year == want_year or not want_year:
                v = _num(r.get("Value"))
                if v:
                    return v
    return None


def county_production(key, usps, year):
    """Return list of (county_fips5, production_bu) for one state/year."""
    rows = _api_get(key, {
        "statisticcat_desc": "PRODUCTION",
        "agg_level_desc": "COUNTY",
        "state_alpha": usps,
        "short_desc": "CORN, GRAIN - PRODUCTION, MEASURED IN BU",
        "year": str(year),
    })
    out = []
    for r in rows:
        val = _num(r.get("Value"))
        if val is None:
            continue
        st = (r.get("state_ansi") or r.get("state_fips_code") or "").zfill(2)
        co = (r.get("county_ansi") or r.get("county_code") or "").strip()
        if not co or not co.isdigit():
            continue  # skip "other (combined) counties"
        fips = st + co.zfill(3)
        out.append((fips, val))
    return out
