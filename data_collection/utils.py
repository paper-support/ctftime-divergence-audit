"""Shared utilities: cross-process rate-limited HTTP client, atomic writes, logging.

Implements the polite-fetcher contract documented in DATA_STATEMENT.md:
  - 10 s minimum interval between requests to a given host, ENFORCED across
    all scripts via a per-host file-lock + timestamp file. This is the
    "global 10 s per host" promise we make to reviewers.
  - Bounded retry (max 8 attempts) with capped exponential backoff and honored
    Retry-After response header. No infinite loops.
  - Failed URLs append to logs/failures.jsonl for audit.
"""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "logs"
LOCK_DIR = PROJECT_ROOT / ".ratelimit"  # cross-process rate-limit state
LOG_DIR.mkdir(exist_ok=True)
LOCK_DIR.mkdir(exist_ok=True)
FAILURE_LOG = LOG_DIR / "failures.jsonl"

CRAWL_DELAY_SECONDS = 10.0          # HTML lane — matches robots.txt Crawl-delay:10
API_CRAWL_DELAY_SECONDS = 5.0       # API lane — stricter-than-common bounded REST
                                    # cadence (12 req/min). Slower than typical public
                                    # API conventions; chosen for Q1 reputational defense
                                    # per Codex round 4. Was 2 s in v3; 5 s adopted v3.1.
MAX_RETRIES = 8
MAX_BACKOFF_SECONDS = 600  # 10 min cap
USER_AGENT = (
    "ctftime-research-academic/0.1 "
    "(SCI paper data collection; contact: h@alum.vassar.edu; "
    "respects robots.txt Crawl-delay:10)"
)


# --------------------------------------------------------- Cross-process limiter

def _wait_per_host(host: str, delay_s: float = CRAWL_DELAY_SECONDS,
                   lane: str = "html") -> None:
    """Block until at least `delay_s` has elapsed since the last request to
    (host, lane) by ANY process. Uses a per-(host,lane) file lock so concurrent
    scripts cannot violate the politeness budget.

    Lanes (per DATA_STATEMENT.md two-tier policy):
      - "html" → 10 s, matches robots.txt Crawl-delay:10
      - "api"  →  2 s, courtesy limit on the CTFtime data-analysis API
    """
    import fcntl
    safe = host.replace("/", "_").replace(":", "_")
    state_path = LOCK_DIR / f"{safe}__{lane}.last"
    state_path.touch(exist_ok=True)
    while True:
        with open(state_path, "r+") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError as e:
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                time.sleep(0.05)
                continue
            try:
                raw = f.read().strip()
                last = float(raw) if raw else 0.0
                now = time.time()
                wait = delay_s - (now - last)
                if wait > 0:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    time.sleep(wait + 0.01)
                    continue
                # Eligible — claim the slot atomically:
                f.seek(0); f.truncate()
                f.write(f"{time.time():.6f}")
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return
            finally:
                try: fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception: pass


def _record_failure(url: str, reason: str) -> None:
    rec = {
        "url": url,
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with FAILURE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def setup_logging(name: str) -> logging.Logger:
    """One log file per script, append-only, with stderr mirror."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)sZ [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    fh = logging.FileHandler(LOG_DIR / f"{name}.log")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _retry_after_seconds(headers, default: float) -> float:
    """Honor Retry-After (seconds or HTTP-date). Cap at MAX_BACKOFF_SECONDS."""
    ra = headers.get("retry-after") if hasattr(headers, "get") else None
    if not ra:
        return min(default, MAX_BACKOFF_SECONDS)
    try:
        return min(float(ra), MAX_BACKOFF_SECONDS)
    except ValueError:
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(ra)
            wait = (dt - datetime.now(dt.tzinfo)).total_seconds()
            return max(0.0, min(wait, MAX_BACKOFF_SECONDS))
        except Exception:
            return min(default, MAX_BACKOFF_SECONDS)


class PoliteClient:
    """httpx client with cross-process rate limiting and bounded retry.

    All requests are JSON-expected; raises on non-2xx after retries are exhausted.
    Records failure_log sidecar on terminal failure.
    """

    def __init__(self, delay: float = API_CRAWL_DELAY_SECONDS, timeout: float = 60.0):
        # API lane defaults to API_CRAWL_DELAY_SECONDS (2s) — 5× faster than HTML
        # lane while staying polite and well within typical public-API conventions.
        self.delay = delay
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            http2=False,
        )
        self.logger = setup_logging("collect_api")

    def get_json(self, url: str, params: dict | None = None) -> Any:
        """Resilient GET with bounded retry budget. Raises after MAX_RETRIES."""
        host = httpx.URL(url).host
        decode_attempts = 0
        net_attempt = 0
        while True:
            _wait_per_host(host, self.delay, lane="api")
            try:
                r = self.client.get(url, params=params)
                self.logger.info(f"GET {r.request.url} -> {r.status_code} ({len(r.content)}B)")
                if r.status_code == 429 or r.status_code >= 500:
                    if net_attempt >= MAX_RETRIES:
                        msg = f"HTTP {r.status_code} after {MAX_RETRIES} retries"
                        self.logger.error(f"FAILED {url}: {msg}")
                        _record_failure(url, msg); raise httpx.HTTPStatusError(msg, request=r.request, response=r)
                    net_attempt += 1
                    backoff = _retry_after_seconds(r.headers, default=min(30 * net_attempt, MAX_BACKOFF_SECONDS))
                    self.logger.warning(f"HTTP {r.status_code} — sleep {backoff:.0f}s (attempt {net_attempt}/{MAX_RETRIES})")
                    time.sleep(backoff)
                    continue
                r.raise_for_status()
                return r.json()
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as e:
                if net_attempt >= MAX_RETRIES:
                    msg = f"network exhausted after {MAX_RETRIES}: {type(e).__name__}: {e}"
                    self.logger.error(f"FAILED {url}: {msg}")
                    _record_failure(url, msg); raise
                net_attempt += 1
                backoff = min(30 * net_attempt, MAX_BACKOFF_SECONDS)
                self.logger.warning(f"network ({type(e).__name__}) — sleep {backoff:.0f}s ({net_attempt}/{MAX_RETRIES})")
                time.sleep(backoff)
            except json.JSONDecodeError as e:
                decode_attempts += 1
                if decode_attempts >= 3:
                    self.logger.error(f"FAILED {url}: bad JSON × 3")
                    _record_failure(url, "JSONDecodeError × 3"); raise
                self.logger.warning(f"bad JSON ({decode_attempts}/3); retry in 5s")
                time.sleep(5)
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP {e.response.status_code} on {url}; giving up")
                _record_failure(url, f"HTTP {e.response.status_code}"); raise

    def close(self):
        self.client.close()


class PoliteHTMLClient:
    """Resilient HTML fetcher sharing the same cross-process rate limit as the
    JSON client. Use this in `collect_html.py`, `collect_writeups.py`, and
    `validation_crawl.py` so all CTFtime requests respect the global 10s/host budget.

    Returns the httpx.Response on success (or 404/410 — caller handles); returns
    None after MAX_RETRIES exhausted or on persistent 4xx; appends to FAILURE_LOG.
    """

    def __init__(self, delay: float = CRAWL_DELAY_SECONDS, timeout: float = 60.0,
                 logger_name: str = "html_client"):
        self.delay = delay
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
            follow_redirects=True,
        )
        self.logger = setup_logging(logger_name)

    def get(self, url: str) -> httpx.Response | None:
        host = httpx.URL(url).host
        attempt = 0
        while True:
            _wait_per_host(host, self.delay, lane="html")
            try:
                r = self.client.get(url)
                if r.status_code in (404, 410):
                    self.logger.info(f"GET {url} -> {r.status_code}")
                    return r
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt >= MAX_RETRIES:
                        _record_failure(url, f"HTTP {r.status_code} after {MAX_RETRIES}")
                        self.logger.error(f"FAILED {url}: HTTP {r.status_code}")
                        return None
                    attempt += 1
                    backoff = _retry_after_seconds(r.headers, default=min(30 * attempt, MAX_BACKOFF_SECONDS))
                    self.logger.warning(f"HTTP {r.status_code} on {url} — sleep {backoff:.0f}s ({attempt}/{MAX_RETRIES})")
                    time.sleep(backoff)
                    continue
                r.raise_for_status()
                self.logger.info(f"GET {url} -> {r.status_code} ({len(r.content)}B)")
                return r
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as e:
                if attempt >= MAX_RETRIES:
                    _record_failure(url, f"network exhausted: {type(e).__name__}: {e}")
                    self.logger.error(f"FAILED {url}: network exhausted")
                    return None
                attempt += 1
                backoff = min(30 * attempt, MAX_BACKOFF_SECONDS)
                self.logger.warning(f"network ({type(e).__name__}) on {url} — sleep {backoff:.0f}s ({attempt}/{MAX_RETRIES})")
                time.sleep(backoff)
            except httpx.HTTPStatusError as e:
                _record_failure(url, f"HTTP {e.response.status_code}")
                self.logger.error(f"HTTP {e.response.status_code} on {url}")
                return None

    def close(self):
        self.client.close()


def write_html_with_meta(out_path: Path, response: httpx.Response,
                         extracted: dict | None = None) -> None:
    """Save raw HTML + .meta.json sidecar with provenance + optional extracted dict."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.exists():
        out_path.write_text(response.text, encoding="utf-8")
    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
    if not meta_path.exists():
        body = response.content
        meta = {
            "url": str(response.request.url),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": response.status_code,
            "byte_count": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "user_agent": USER_AGENT,
            "crawl_delay_s": CRAWL_DELAY_SECONDS,
        }
        if extracted is not None:
            meta["extracted"] = extracted
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def atomic_write_json(path: Path, payload: Any, source_url: str) -> bool:
    """Write JSON + .meta.json sidecar atomically. Returns True if newly written.

    Skips silently if path already exists (resume support).
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)

    meta = {
        "url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "byte_count": len(body.encode("utf-8")),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "user_agent": USER_AGENT,
        "crawl_delay_s": CRAWL_DELAY_SECONDS,
    }
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return True


def already_have(path: Path) -> bool:
    return path.exists() and path.with_suffix(path.suffix + ".meta.json").exists()
