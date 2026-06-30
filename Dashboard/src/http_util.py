"""Minimal, firewall-aware HTTP GET helpers built on the standard library only.

- Honors HTTP(S)_PROXY environment variables automatically (urllib default).
- Supports a corporate root-CA bundle (for TLS-intercepting proxies) so the
  dashboard does not die with CERTIFICATE_VERIFY_FAILED.
- Retries with backoff on transient (5xx / network) errors.
- Enforces a polite delay between requests.
"""
import json
import ssl
import time
import urllib.error
import urllib.request

_CTX = None          # ssl.SSLContext (or None for default)
_DELAY = 0.3         # seconds between requests
_TIMEOUT = 60
_RETRIES = 3
_last_request_ts = 0.0

USER_AGENT = "CornDashboard/1.0 (stdlib urllib; internal analytics)"


def configure(ca_bundle="", delay=0.3, timeout=60, retries=3):
    """Set up the shared SSL context and request policy. Call once at startup."""
    global _CTX, _DELAY, _TIMEOUT, _RETRIES
    _DELAY = float(delay)
    _TIMEOUT = int(timeout)
    _RETRIES = int(retries)
    if ca_bundle:
        _CTX = ssl.create_default_context(cafile=ca_bundle)
    else:
        _CTX = ssl.create_default_context()


def _ctx():
    global _CTX
    if _CTX is None:
        _CTX = ssl.create_default_context()
    return _CTX


def _throttle():
    global _last_request_ts
    if _DELAY > 0:
        wait = _DELAY - (time.time() - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
    _last_request_ts = time.time()


class HttpError(Exception):
    def __init__(self, status, url, message=""):
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} for {url} {message}".strip())


# Circuit breaker: once a host returns repeated 429s, stop hammering it for the
# rest of the run (subsequent calls to that host fail fast instead of retrying).
_blocked_hosts = set()


def _host(url):
    try:
        return url.split("/", 3)[2]
    except IndexError:
        return url


def get_bytes(url, headers=None, timeout=None):
    """GET a URL, returning raw bytes. Retries transient failures with backoff."""
    timeout = timeout or _TIMEOUT
    req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)

    host = _host(url)
    if host in _blocked_hosts:
        raise HttpError(429, url, "host rate-limited earlier this run; skipping")

    last_exc = None
    for attempt in range(_RETRIES + 1):
        _throttle()
        req = urllib.request.Request(url, headers=req_headers)
        backoff = min(8.0, 1.5 ** attempt)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # 4xx (except 429 rate-limit) are not worth retrying
            if exc.code not in (429, 500, 502, 503, 504):
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                raise HttpError(exc.code, url, body)
            last_exc = HttpError(exc.code, url)
            if exc.code == 429:  # rate limited: wait much longer (honor Retry-After)
                ra = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    backoff = float(ra) if ra else min(60.0, 5.0 * (2 ** attempt))
                except (TypeError, ValueError):
                    backoff = min(60.0, 5.0 * (2 ** attempt))
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError) as exc:
            last_exc = exc
        if attempt < _RETRIES:
            time.sleep(backoff)
    # exhausted retries: if it was a rate limit, open the circuit for this host
    if isinstance(last_exc, HttpError) and last_exc.status == 429:
        _blocked_hosts.add(host)
    raise last_exc if last_exc else HttpError(0, url, "unknown error")


def get_text(url, headers=None, encoding="utf-8", timeout=None):
    return get_bytes(url, headers=headers, timeout=timeout).decode(encoding, "replace")


def get_json(url, headers=None, timeout=None):
    return json.loads(get_text(url, headers=headers, timeout=timeout))
