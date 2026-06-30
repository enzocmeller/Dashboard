"""Assemble the self-contained index.html by inlining ECharts + GeoJSON + data.

The result is a single file that opens directly from file:// with zero network
calls — the firewall-friendly deliverable.
"""
import json
import os


def _read(path, label):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing {label}: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _safe(text):
    """Prevent an embedded '</script>' (or '<!--') from breaking the page."""
    return text.replace("</", "<\\/").replace("<!--", "<\\!--")


def render(cfg, payload):
    root = cfg["root"]
    template = _read(os.path.join(root, "templates", "dashboard.html"), "template")
    echarts = _read(os.path.join(root, "assets", "echarts.min.js"), "echarts.min.js")
    geojson = _read(os.path.join(root, "src", "geo", "us_states.geo.json"), "us_states.geo.json")

    data_json = _safe(json.dumps(payload, ensure_ascii=False))
    geo_json = _safe(geojson.strip())

    html = template.replace("/*__ECHARTS__*/", echarts)
    html = html.replace("/*__GEOJSON__*/", geo_json)
    html = html.replace("/*__DATA__*/", data_json)

    out = os.path.join(root, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out
