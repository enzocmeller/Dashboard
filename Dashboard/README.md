# 🌽 US Corn Statistics Dashboard

A self-contained, firewall-friendly dashboard that tracks corn statistics for
every US state. One Python script gathers live data and regenerates a single
`index.html` you can open in any browser — **no install, no server, no internet
needed to view it.**

## What it shows
Opens on a **national "United States" overview**; pick any state from the map or
dropdown. A row of **at-a-glance KPI cards** summarizes the current selection,
then the panels:
1. **US map / state selector** — click a state; the map is shaded by **production share** (toggle to G+E condition or NDVI deviation)
2. **US production share & rank** — each state's % of total US corn, as a leaderboard
3. **Soil moisture** in the state's main corn area (0–27 cm, 16-day trend)
4. **Phenology table** — Planted / Silking / Dough / Mature (% complete)
5. **Crop quality donut** — E / G / F / P / V, with **G+E** highlighted in the center
6. **G+E condition line** for the season vs. historical **min / median / max**
7. **Yield curve + trend line** (USDA survey, bu/acre)
8. **Yield deviation** — detrended +/- bars (the real year-to-year change)
9. **Yield ↔ G+E correlation** — scatter + regression line + r (vs. detrended yield)
10. **Weather anomaly** — precip & temperature vs. normal, for lead times **1-5 / 6-10 / 11-15 days**
11. **Growing degree days** — cumulative corn GDD (base 50 °F) vs. the multi-year normal
12. **Satellite NDVI** (NASA Harvest GLAM, corn-masked) — value vs. mean + deviation from normal

## Requirements
- **Python 3.10 or newer** (3.12+ recommended). Check with `python --version`.
- That's it. **No third-party packages** — only the Python standard library.
  (Trend & correlation use the built-in `statistics` module, so there is nothing
  to `pip install` and nothing for a firewall to block.)

## One-time setup
1. **Get a free USDA NASS key** (instant, emailed) at
   <https://quickstats.nass.usda.gov/api>.
2. Copy `config.example.json` → **`config.json`** and paste your key into
   `"nass_api_key"`. (`config.json` is gitignored — your key stays local.)
3. *(Optional but recommended on a new work machine)* test connectivity:
   ```
   python src/check_connectivity.py
   ```

## Run / update
Double-click **`run.bat`** (or run `python src/update.py`), then open
`index.html`. Re-run any time to refresh — that's the auto-update.

- **First run** is slower (it builds the 30-year climate normals and the NDVI
  history, then caches them). **Later runs are fast** — only new data is fetched.
- **Changed only the look** (template/CSS in `templates/dashboard.html`)? Rebuild
  the HTML instantly from the last data snapshot, with no network calls:
  ```
  python src/update.py --rebuild
  ```

## Firewall / IT notes
The dashboard only ever makes **HTTPS (port 443) GET requests** to these hosts.
Ask IT to allowlist them if anything is blocked:

| Host | Purpose | Key? |
|------|---------|------|
| `quickstats.nass.usda.gov` | USDA crop data | free key |
| `api.open-meteo.com` | weather forecast / soil moisture | none |
| `archive-api.open-meteo.com` | ERA5 climate normals | none |
| `api.glamdata.org` | GLAM NDVI | none |
| `glam1.gsfc.nasa.gov` | GLAM (fallback) | none |

**Behind a TLS-intercepting proxy?** If you get `CERTIFICATE_VERIFY_FAILED`,
set `"ca_bundle"` in `config.json` to your corporate root-CA `.pem` file (or set
the `SSL_CERT_FILE` environment variable). Standard `HTTP(S)_PROXY` environment
variables are honored automatically.

## Configuration (`config.json`)
| Key | Default | Meaning |
|-----|---------|---------|
| `nass_api_key` | — | **required** USDA key |
| `states` | `"all"` | `"all"` or a list like `["IA","IL","NE"]` |
| `yield_start_year` | `1990` | first year of the yield/trend series |
| `condition_history_years` | `12` | years of history for the G+E bands & correlation |
| `ndvi_product` | `vnp09h1-ndvi` | GLAM product (VIIRS 8-day); `mod13q1-ndvi` = MODIS 16-day |
| `ndvi_season_start_month` | `4` | season start for the NDVI series |
| `ndvi_baseline_years` | `5` | prior years averaged into the NDVI "standard" / deviation (`0` = none, faster first build) |
| `ndvi_max_composites` | `24` | cap on NDVI points per state |
| `gdd_start_month` | `5` | month GDD accumulation starts (`5` = May) |
| `top_counties_for_centroid` | `15` | counties used for the production-weighted corn point |
| `request_delay_seconds` | `0.3` | politeness delay between API calls |
| `ca_bundle` | `""` | optional corporate root-CA path |

## How it works
```
run.bat → python src/update.py
            ├─ src/sources/nass.py        USDA: progress, condition, yield, county production
            ├─ src/geo/corn_points.py     production-weighted lat/lon per state (bundled county centroids)
            ├─ src/sources/openmeteo.py   forecast, soil moisture, ERA5 normals → anomalies
            ├─ src/sources/glam.py        corn-masked NDVI + baseline/anomaly
            ├─ src/compute/stats.py       trend, detrend, correlation (stdlib statistics)
            └─ src/build.py               inline ECharts + GeoJSON + data → index.html
```
Bundled, immutable assets (no runtime download): `assets/echarts.min.js`,
`src/geo/us_states.geo.json`, `src/geo/county_centroids.csv`.

## SharePoint (later)
The current `index.html` is perfect for `file://` and zipping. For SharePoint,
note that inline `<script>` is being blocked by tenant CSP (rolling out 2026), so
hosting the interactive HTML directly will need a CSP-compliant SPFx web part, or
an exported PDF/Office view. The pipeline already keeps data
(`data/dashboard_data.json`) separate from presentation to make that migration easy.

## Attribution
USDA NASS Quick Stats · Weather & soil moisture by Open-Meteo (CC-BY 4.0, ERA5) ·
NDVI by NASA Harvest GLAM (geoBoundaries: Runfola et al. 2020). Internal analytics use.
