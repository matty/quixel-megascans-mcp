"""File what the user downloaded from Fab into a local library, with a record of where it came from.

Originals in the downloads folder are never moved or deleted. Downloads are untrusted data: members
are only ever written inside the destination folder, nothing is run, and executables are skipped.

The contents of real Fab zips had not been seen when this was written, so map renaming is tolerant,
anything unrecognised keeps its name, and the normal map convention is recorded as unverified.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_UNPACKED_BYTES = 30 * 1024**3
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff", ".tga"}
SCENE_EXT = {".gltf", ".glb", ".fbx", ".obj", ".usd", ".usda", ".usdc", ".usdz", ".blend", ".uasset", ".mtlx"}
SKIPPED_EXT = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr", ".lnk", ".py", ".sh"}
INGESTIBLE_EXT = {".zip", ".glb", ".gltf", ".fbx", ".exr", ".usdz"}
LOOKS_LIKE_FAB = re.compile(r"_[a-z0-9]{7,}_.*(1k|2k|4k|8k|16k|raw|high|mid|low)\b", re.I)
_BROWSER_COPY = re.compile(r" \(\d+\)(?=\.[^.]+$)")

# Fab/Megascans map word -> the naming used by the pbr-texture-sources skill.
MAP_NAMES = {
    "basecolor": "BaseColor", "albedo": "BaseColor", "diffuse": "BaseColor", "color": "BaseColor",
    "normal": "Normal", "normalbump": "Normal", "roughness": "Roughness", "metalness": "Metallic",
    "metallic": "Metallic", "ao": "AO", "displacement": "Height", "height": "Height", "cavity": "Cavity",
    "gloss": "Gloss", "specular": "Specular", "bump": "Bump", "opacity": "Opacity", "mask": "Mask",
    "translucency": "Translucency", "fuzz": "Fuzz",
}


class IngestError(Exception):
    """This file could not be filed. The message is safe to show to the user."""


def canonical_name(file_name: str) -> str:
    """The name Fab lists, from a browser's name for it ('x (1).zip' is 'x.zip')."""
    return _BROWSER_COPY.sub("", file_name)


def asset_slug(file_name: str) -> str:
    """'brick_wall_wgukbfj_2k.zip' -> 'brick_wall_wgukbfj' (everything up to the size marker)."""
    stem = canonical_name(file_name).rsplit(".", 1)[0].lower()
    head = re.split(r"_(?:1k|2k|4k|8k|16k|raw|high|mid|low)(?:_|$)", stem, maxsplit=1)[0]
    return re.sub(r"[^a-z0-9_-]+", "_", head).strip("_-") or "asset"


def file_tag(file_name: str, slug: str) -> str:
    stem = canonical_name(file_name).rsplit(".", 1)[0].lower()
    tag = stem[len(slug):].strip("_") if stem.startswith(slug) else stem
    return re.sub(r"[^a-z0-9_-]+", "_", tag) or "file"


def _safe_target(root: Path, member: str) -> Path:
    rel = member.replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or ".." in parts:
        raise IngestError(f"refusing unsafe path in archive: {member!r}")
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise IngestError(f"refusing unsafe path in archive: {member!r}")
    return target


def _map_name(member_stem: str) -> str | None:
    tokens = re.split(r"[_\-. ]+", member_stem.lower())
    return MAP_NAMES.get(tokens[-1]) if tokens else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, target.open("wb") as out:
        shutil.copyfileobj(source, out, 1 << 20)


def _extract_zip(path: Path, dest: Path, slug: str, tag: str) -> tuple[list[dict], list[str]]:
    written: list[dict] = []
    notes: list[str] = []
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise IngestError(f"{path.name} is not a readable zip; it may still be downloading") from exc
    with archive:
        members = [i for i in archive.infolist() if not i.is_dir()]
        unpacked = sum(i.file_size for i in members)
        if unpacked > MAX_UNPACKED_BYTES:
            raise IngestError(f"{path.name} would unpack to {unpacked / 1024**3:.0f} GB; refusing")
        dest.mkdir(parents=True, exist_ok=True)
        if unpacked > shutil.disk_usage(dest).free:
            raise IngestError(f"not enough free disk space to unpack {path.name}")
        if bad := archive.testzip():
            raise IngestError(f"{path.name} is corrupt at {bad}; download it again")
        suffixes = {Path(i.filename).suffix.lower() for i in members}
        # Scene files point at their textures by name, so renaming those would break them.
        keep_names = bool(suffixes & SCENE_EXT)
        if keep_names:
            base = dest / tag
            notes.append(f"{path.name} contains a scene file, so its own names and layout were kept")
        else:
            base = dest
        used: set[str] = set()
        for info in members:
            suffix = Path(info.filename).suffix.lower()
            if suffix in SKIPPED_EXT:
                notes.append(f"skipped executable-type file {info.filename}")
                continue
            map_name = None
            if keep_names:
                target = _safe_target(base, info.filename)
            else:
                _safe_target(base, info.filename)  # reject traversal even when flattening
                stem = Path(info.filename.replace("\\", "/")).stem
                map_name = _map_name(stem) if suffix in IMAGE_EXT else None
                if map_name and f"{map_name}{suffix}" not in used:
                    used.add(f"{map_name}{suffix}")
                    target = _safe_target(base, f"{slug}_{tag}_{map_name}{suffix}")
                else:
                    map_name = None
                    target = _safe_target(base / tag, info.filename)
            _copy_member(archive, info, target)
            written.append(
                {
                    "path": str(target.relative_to(dest)).replace("\\", "/"),
                    "map": map_name,
                    "original_name": info.filename,
                    "size": info.file_size,
                }
            )
    return written, notes


def ingest_file(path: Path, library: Path, listing: dict[str, Any]) -> dict[str, Any]:
    """File one download. `listing` is what's known about it: id, title, url, seller and flags."""
    if not path.is_file():
        raise IngestError(f"no such file: {path}")
    slug = asset_slug(path.name)
    tag = file_tag(path.name, slug)
    dest = library / slug
    record_path = dest / "source.json"
    record: dict[str, Any] = {}
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
    digest = _sha256(path)
    if any(d.get("sha256") == digest for d in record.get("downloads", [])):
        return {"status": "already_filed", "file": path.name, "folder": str(dest)}

    if path.suffix.lower() == ".zip":
        written, notes = _extract_zip(path, dest, slug, tag)
    else:
        target = _safe_target(dest / tag, path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        written = [
            {
                "path": str(target.relative_to(dest)).replace("\\", "/"),
                "map": None,
                "original_name": path.name,
                "size": path.stat().st_size,
            }
        ]
        notes = []

    now = datetime.now(UTC).isoformat(timespec="seconds")
    record = {
        "source": "Fab / Quixel Megascans",
        "licence": "Fab Standard License (https://www.fab.com/eula)",
        "licence_note": "Add the asset to your Fab library: downloading alone may not apply the licence.",
        "normal_convention": "unverified: check before use",
        **{k: v for k, v in record.items() if k != "downloads"},
        **{k: v for k, v in listing.items() if v is not None},
        "downloads": [
            *record.get("downloads", []),
            {"file": path.name, "sha256": digest, "filed_at": now, "written": written},
        ],
    }
    dest.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {
        "status": "filed",
        "file": path.name,
        "folder": str(dest),
        "maps": sorted({w["map"] for w in written if w["map"]}),
        "files_written": len(written),
        "notes": notes,
    }


def list_library(library: Path, query: str = "") -> list[dict[str, Any]]:
    words = query.lower().split()
    assets = []
    if not library.is_dir():
        return assets
    for record_path in sorted(library.glob("*/source.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        text = " ".join(
            [record_path.parent.name, str(record.get("title", "")), *map(str, record.get("tags", []))]
        ).lower()
        if all(word in text for word in words):
            assets.append(
                {
                    "title": record.get("title"),
                    "folder": str(record_path.parent),
                    "url": record.get("url"),
                    "specs": record.get("specs"),
                    "downloads": [d.get("file") for d in record.get("downloads", [])],
                }
            )
    return assets
