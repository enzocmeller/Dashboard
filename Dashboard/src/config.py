"""Load configuration from config.json with sensible defaults and env overrides.

Pure standard library. The only required setting is ``nass_api_key``.
"""
import json
import os

# Project root = parent of this file's directory (src/..)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "nass_api_key": "",
    "states": "all",
    "yield_start_year": 1990,
    "condition_history_years": 12,
    "ndvi_product": "vnp09h1-ndvi",
    "ndvi_season_start_month": 4,
    "ndvi_baseline_years": 2,
    "ndvi_max_composites": 24,
    "gdd_start_month": 5,
    "top_counties_for_centroid": 15,
    "request_delay_seconds": 0.3,
    "request_timeout_seconds": 60,
    "request_retries": 3,
    "ca_bundle": "",
    "open_meteo_commercial_key": "",
}


class ConfigError(Exception):
    pass


def load(path=None):
    """Read config.json (if present), layer it over defaults, apply env overrides."""
    cfg = dict(DEFAULTS)
    path = path or os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                user = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"config.json is not valid JSON: {exc}")
        for key, value in user.items():
            if key.startswith("_"):
                continue
            cfg[key] = value

    # Environment overrides (handy on locked-down machines / CI)
    if os.environ.get("NASS_API_KEY"):
        cfg["nass_api_key"] = os.environ["NASS_API_KEY"]
    if os.environ.get("SSL_CERT_FILE") and not cfg.get("ca_bundle"):
        cfg["ca_bundle"] = os.environ["SSL_CERT_FILE"]

    cfg["root"] = ROOT
    cfg["data_dir"] = os.path.join(ROOT, "data")
    return cfg


def require_nass_key(cfg):
    key = (cfg.get("nass_api_key") or "").strip()
    if not key or key.upper().startswith("PASTE_"):
        raise ConfigError(
            "No USDA NASS API key found.\n"
            "  1. Get a free key (instant) at: https://quickstats.nass.usda.gov/api\n"
            "  2. Copy config.example.json to config.json\n"
            "  3. Paste your key into the \"nass_api_key\" field.\n"
            "  (or set the NASS_API_KEY environment variable)"
        )
    return key
