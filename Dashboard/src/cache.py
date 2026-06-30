"""A tiny SQLite key/value cache (standard library ``sqlite3``).

Used to make re-runs fast and polite:
- *Immutable* data (ERA5 climate normals, past GLAM composites, GLAM id maps)
  is fetched once and kept forever.
- *Volatile* data (current crop progress/condition, the latest forecast) is not
  cached and is re-fetched on every run, which is what makes the dashboard
  "auto-update every time you run it".
"""
import json
import os
import sqlite3
import time

_conn = None


def init(data_dir):
    global _conn
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "cache.sqlite")
    _conn = sqlite3.connect(path)
    _conn.execute(
        "CREATE TABLE IF NOT EXISTS kv ("
        "  k TEXT PRIMARY KEY,"
        "  v TEXT NOT NULL,"
        "  created REAL NOT NULL"
        ")"
    )
    _conn.commit()
    return _conn


def get(key):
    if _conn is None:
        return None
    row = _conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    return row[0] if row else None


def set(key, value):
    if _conn is None:
        return
    _conn.execute(
        "INSERT OR REPLACE INTO kv (k, v, created) VALUES (?, ?, ?)",
        (key, value, time.time()),
    )
    _conn.commit()


def get_json(key):
    raw = get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json(key, obj):
    set(key, json.dumps(obj))


def cached_json(key, producer):
    """Return cached JSON for ``key`` or call ``producer()``, cache, and return it."""
    hit = get_json(key)
    if hit is not None:
        return hit
    value = producer()
    if value is not None:
        set_json(key, value)
    return value
