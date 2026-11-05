"""Turn Fab's raw listing JSON into the small, decision-ready shapes the tools return."""

from __future__ import annotations

import html
import re
from typing import Any

from .fab import BASE_URL

ASSET_TYPES = {"surface": "material", "3d": "3d-model", "decal": "decal", "brush": "brush"}
_TYPE_NAMES = {v: k for k, v in ASSET_TYPES.items()}

_USD_TIER = re.compile(r"_USD_(\d+)_")
_SPEC_LABELS = "Texel density|Scan Area|Physical size|Mesh type|Maps"
_SPEC = re.compile(rf"^\s*({_SPEC_LABELS})\s*:\s*(.+?)\s*$", re.I | re.S)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_RESOLUTION = re.compile(r"(?:^|_)(1|2|4|8|16)k(?:_|\.|$)", re.I)
_TIER = re.compile(r"(?:^|_)(raw|high|mid|low|nanite)(?:_|\.|$)", re.I)
# Fab's mesh file names pair each tier with a texture size (e.g. "..._4k_ue_high.zip").
_TIER_RESOLUTION = {"low": 1, "mid": 2, "high": 4, "raw": 8, "nanite": 8}
_PREFERRED_FORMAT = {"material": "texture-set", "decal": "texture-set", "3d-model": "fbx"}


def listing_url(listing_id: str) -> str:
    return f"{BASE_URL}/listings/{listing_id}"


def licence_status(licenses: list[dict]) -> dict[str, Any]:
    """Whether a licence that delivers source files is free.

    Fab's own signals can't answer this: `isFree` was false on every Megascans listing checked,
    while `startingPrice` and the `is_free` filter count the £0 "UEFN - Reference only" tier, which
    gives no source files. Each usable licence's price can. Search results carry it only inside the
    price tier id ("..._USD_199_..." is $1.99), so that format is parsed here.
    """
    usable: list[dict[str, Any]] = []
    for licence in licenses or []:
        if "reference" in str(licence.get("name") or licence.get("slug") or "").lower():
            continue
        tier = licence.get("priceTier")
        if isinstance(tier, dict):
            amount, currency = tier.get("price"), tier.get("currencyCode")
        else:
            match = _USD_TIER.search(str(tier or ""))
            amount, currency = (int(match.group(1)) / 100, "USD") if match else (None, None)
        if isinstance(amount, (int, float)):
            usable.append({"name": licence.get("name"), "price": amount, "currency": currency})
    if not usable:
        return {"free": None, "price": None}
    cheapest = min(usable, key=lambda item: item["price"])
    if cheapest["price"] == 0:
        return {"free": True, "price": None}
    return {"free": False, "price": f"{cheapest['price']:.2f} {cheapest['currency']}"}


def search_hit(raw: dict) -> dict[str, Any]:
    return {
        "listing_id": raw.get("uid"),
        "title": raw.get("title"),
        "type": _TYPE_NAMES.get(raw.get("listingType"), raw.get("listingType")),
        "category": (raw.get("category") or {}).get("path"),
        "tags": [t.get("slug") for t in raw.get("tags") or []][:8],
        "seller": (raw.get("user") or {}).get("sellerName"),
        **licence_status(raw.get("licenses") or []),
        "url": listing_url(raw.get("uid", "")),
    }


def parse_specs(description_html: str) -> dict[str, Any]:
    """Pull the spec lines out of the listing description; only ones it states are returned."""
    specs: dict[str, Any] = {}
    for block in re.findall(r"<p\b[^>]*>(.*?)</p>", description_html or "", re.S | re.I):
        text = html.unescape(re.sub(r"<[^>]+>", " ", block))
        match = _SPEC.match(re.sub(r"\s+", " ", text))
        if not match:
            continue
        label, value = match.group(1).lower(), match.group(2)
        numbers = [float(n) for n in _NUMBER.findall(value)]
        if label == "texel density" and numbers:
            specs["texel_density_px_per_m"] = int(numbers[0])
        elif label == "scan area" and numbers:
            specs["scan_area_m"] = numbers
        elif label == "physical size" and numbers:
            specs["physical_size_m"] = numbers
        elif label == "mesh type":
            specs["mesh_type"] = value
        elif label == "maps":
            specs["maps"] = re.sub(r"\([^)]*\)", " ", value).split()
    return specs


def _file_entry(format_code: str, raw: dict) -> dict[str, Any]:
    name = raw.get("name") or ""
    stem = name.rsplit(".", 1)[0]
    resolution = _RESOLUTION.search(stem + ".")
    tier = _TIER.search(stem + ".")
    return {
        "format": format_code,
        "name": name,
        "size_mb": round((raw.get("fileSize") or 0) / 1_000_000, 1),
        "resolution": f"{resolution.group(1)}k" if resolution else None,
        "tier": tier.group(1).lower() if tier else None,
    }


def parse_files(formats: list[dict]) -> list[dict[str, Any]]:
    return [
        _file_entry((group.get("assetFormatType") or {}).get("code") or "", raw)
        for group in formats or []
        for raw in group.get("files") or []
    ]


def _file_k(entry: dict) -> int | None:
    if entry["resolution"]:
        return int(entry["resolution"][:-1])
    return _TIER_RESOLUTION.get(entry["tier"] or "")


def recommend_file(files: list[dict], listing_type: str | None, target: str) -> dict | None:
    """The file to click for this target: the listing's main format, closest size not above target."""
    wanted = int(target.rstrip("kK"))
    preferred = _PREFERRED_FORMAT.get(listing_type or "")
    pool = [f for f in files if f["format"] == preferred and _file_k(f)]
    if not pool:
        pool = [f for f in files if _file_k(f)]
    if not pool:
        return None
    at_or_below = [f for f in pool if _file_k(f) <= wanted]
    if at_or_below:
        return max(at_or_below, key=lambda f: (_file_k(f), f["size_mb"]))
    return min(pool, key=lambda f: (_file_k(f), f["size_mb"]))


def preview_url(raw: dict, width: int = 640) -> str | None:
    """The catalogue image closest to `width` from the listing's thumbnail or first gallery image."""
    for media in list(raw.get("thumbnails") or []) + list(raw.get("medias") or []):
        images = [i for i in media.get("images") or [] if i.get("url") and i.get("width")]
        if images:
            return min(images, key=lambda i: abs(i["width"] - width))["url"]
        if media.get("type") in ("image", "thumbnail") and media.get("mediaUrl"):
            return media["mediaUrl"]
    return None


def asset_details(raw: dict, formats: list[dict], target: str = "2k") -> dict[str, Any]:
    files = parse_files(formats)
    return {
        **search_hit(raw),
        "specs": parse_specs(raw.get("description") or ""),
        "ai_forbidden_flag": raw.get("isAiForbidden"),
        "files": files,
        "recommended_file": recommend_file(files, raw.get("listingType"), target),
        "preview_url": preview_url(raw),
    }
