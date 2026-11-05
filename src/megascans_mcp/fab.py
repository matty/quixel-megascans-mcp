"""The only module that knows Fab's URLs.

Fab has no public API. These are the undocumented, read-only JSON endpoints its website uses, so
Epic can change them without notice: when something breaks, this is the file to fix.

Deliberately absent: login, account calls and download-info. The user downloads on fab.com. The
client identifies itself honestly, caches, and paces itself. A 403 is reported, never worked around.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__

BASE_URL = "https://www.fab.com"
USER_AGENT = f"quixel-megascans-mcp/{__version__}"
SELLERS = {"megascans": "Quixel Megascans", "megaplants": "Quixel Megaplants"}
IMAGE_HOSTS = {"media.fab.com"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Prices are changing during the rollout to free (until 12 Nov 2026), so don't hold listings long.
LISTING_TTL_S = 6 * 3600
SEARCH_TTL_S = 3600


class FabError(Exception):
    """A catalogue request failed. The message is safe to show to the user."""


class FabClient:
    def __init__(
        self,
        cache_dir: Path,
        transport: httpx.BaseTransport | None = None,
        min_interval_s: float = 0.5,
    ):
        self._cache_dir = cache_dir
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )
        self._min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._last_request = 0.0

    def search(self, query: str, listing_type: str | None, seller: str, cursor: str | None) -> dict:
        params: dict[str, Any] = {"seller": seller, "count": 24}
        if query:
            params["q"] = query
        if listing_type:
            params["listing_types"] = listing_type
        if cursor:
            params["cursor"] = cursor
        return self._get_json("/i/listings/search", params, SEARCH_TTL_S)

    def listing(self, listing_id: str) -> dict:
        return self._get_json(f"/i/listings/{listing_id}", {}, LISTING_TTL_S)

    def formats(self, listing_id: str) -> list[dict]:
        return self._get_json(f"/i/listings/{listing_id}/asset-formats", {}, LISTING_TTL_S)

    def image(self, url: str) -> bytes:
        """Fetch a catalogue preview. Only Fab's media host, over https, with a size cap."""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in IMAGE_HOSTS:
            raise FabError(f"refusing to fetch an image from {parts.hostname!r}")
        response = self._send(url)
        if len(response.content) > MAX_IMAGE_BYTES:
            raise FabError("preview image is unexpectedly large")
        return response.content

    def _get_json(self, path: str, params: dict[str, Any], ttl_s: int) -> Any:
        key = hashlib.sha256(json.dumps([path, sorted(params.items())]).encode()).hexdigest()
        cache_file = self._cache_dir / f"{key}.json"
        try:
            if time.time() - cache_file.stat().st_mtime < ttl_s:
                return json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            data = self._send(path, params).json()
        except ValueError as exc:
            raise FabError(f"Fab returned something that is not JSON for {path}") from exc
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _send(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        for attempt in (1, 2):
            with self._lock:
                wait = self._min_interval_s - (time.monotonic() - self._last_request)
                if wait > 0:
                    time.sleep(wait)
                self._last_request = time.monotonic()
            try:
                response = self._http.get(url, params=params)
            except httpx.HTTPError as exc:
                raise FabError(f"could not reach Fab: {exc}") from exc
            if response.status_code in (429, 502, 503, 504) and attempt == 1:
                time.sleep(_retry_after(response))
                continue
            break
        if response.status_code == 404:
            raise FabError("no such listing on Fab")
        if response.status_code in (401, 403):
            raise FabError(
                f"Fab refused the request (HTTP {response.status_code}). This server does not "
                "work around that; search on fab.com instead, and try again later."
            )
        if response.status_code >= 400:
            raise FabError(f"Fab returned HTTP {response.status_code}")
        return response


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(float(response.headers.get("retry-after", "2")), 30.0)
    except ValueError:
        return 2.0
