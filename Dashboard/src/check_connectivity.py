"""Self-test: confirm the work machine can reach every data domain.

Run FIRST on a new machine:  python src/check_connectivity.py
Hand the output to IT if anything is blocked — these are the only domains the
dashboard ever contacts (all HTTPS/443).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import http_util

def _checks(key):
    nass = "https://quickstats.nass.usda.gov/api/get_counts/?commodity_desc=CORN&state_alpha=IA"
    if key:
        nass += "&key=" + key
    return [
        ("USDA NASS" + ("" if key else " (no key set)"), nass),
        ("Open-Meteo forecast", "https://api.open-meteo.com/v1/forecast?latitude=41.6&longitude=-93.6&daily=temperature_2m_mean&forecast_days=1&timezone=auto"),
        ("Open-Meteo archive", "https://archive-api.open-meteo.com/v1/archive?latitude=41.6&longitude=-93.6&start_date=2020-06-01&end_date=2020-06-02&daily=temperature_2m_mean&timezone=auto"),
        ("GLAM API", "https://api.glamdata.org/products/"),
    ]


def main():
    cfg = config.load()
    http_util.configure(ca_bundle=cfg["ca_bundle"], delay=0.0,
                        timeout=cfg["request_timeout_seconds"], retries=1)
    key = (cfg.get("nass_api_key") or "").strip()
    if key.upper().startswith("PASTE_"):
        key = ""
    CHECKS = _checks(key)
    print("Checking data-source connectivity (HTTPS/443)...\n")
    ok = 0
    for name, url in CHECKS:
        host = url.split("/")[2]
        try:
            http_util.get_bytes(url)
            print(f"  [ OK ]  {name:<22} {host}")
            ok += 1
        except Exception as exc:
            print(f"  [FAIL]  {name:<22} {host}\n          -> {exc}")
    print(f"\n{ok}/{len(CHECKS)} reachable.")
    if ok < len(CHECKS):
        print("\nIf any FAIL, ask IT to allowlist these HTTPS domains:")
        print("  quickstats.nass.usda.gov, api.open-meteo.com,")
        print("  archive-api.open-meteo.com, api.glamdata.org, glam1.gsfc.nasa.gov")
        print("Behind a TLS-intercepting proxy? Set \"ca_bundle\" in config.json")
        print("to your corporate root-CA .pem (or the SSL_CERT_FILE env var).")
        return 1
    print("All good — run:  python src/update.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
