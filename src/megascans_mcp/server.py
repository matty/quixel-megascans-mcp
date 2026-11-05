"""The MCP server: tools to search, inspect, shortlist and file Megascans assets."""

from __future__ import annotations

import json
import os
import re
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image
from pydantic import BaseModel, Field

from . import ingest, parse, shortlist
from .fab import SELLERS, FabClient, FabError

ListingId = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$",
        description="The listing_id from search_assets.",
    ),
]
Resolution = Literal["1k", "2k", "4k", "8k"]

INSTRUCTIONS = (
    "Search Quixel Megascans on Fab and build a visual shortlist the user reviews in their browser. "
    "The user adds assets to their Fab library and downloads them on fab.com; this server cannot do "
    "that. Afterwards ingest_downloads files what they downloaded into a local library."
)


class ShortlistItem(BaseModel):
    listing_id: ListingId
    note: Annotated[
        str | None,
        Field(max_length=300, description="One line on why this asset fits; shown on its card."),
    ] = None


def _default_state_dir() -> Path:
    if override := os.environ.get("MEGASCANS_STATE_DIR"):
        return Path(override)
    root = os.environ.get("LOCALAPPDATA")
    return (Path(root) if root else Path.home() / ".local" / "state") / "quixel-megascans-mcp"


def _default_library() -> Path:
    return Path(os.environ.get("MEGASCANS_LIBRARY") or Path.home() / "Megascans")


def _default_downloads() -> Path:
    return Path(os.environ.get("MEGASCANS_DOWNLOADS") or Path.home() / "Downloads")


def build_server(
    client: FabClient | None = None,
    state_dir: Path | None = None,
    library: Path | None = None,
    downloads: Path | None = None,
) -> FastMCP:
    state = state_dir or _default_state_dir()
    default_library = library or _default_library()
    downloads_dir = downloads or _default_downloads()
    fab = client or FabClient(state / "cache")
    known_files_path = state / "known_files.json"
    mcp = FastMCP("quixel-megascans", instructions=INSTRUCTIONS)

    def load_known_files() -> dict[str, dict]:
        try:
            return json.loads(known_files_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def remember_files(details: dict) -> None:
        """Remember which listing each file belongs to, so a later download can be recognised."""
        known = load_known_files()
        entry = {"listing_id": details["listing_id"]}
        known.update({f["name"].lower(): entry for f in details["files"] if f["name"]})
        state.mkdir(parents=True, exist_ok=True)
        known_files_path.write_text(json.dumps(known), encoding="utf-8")

    def load_details(listing_id: str, target: str = "2k") -> dict[str, Any]:
        raw = fab.listing(listing_id)
        seller = (raw.get("user") or {}).get("sellerName")
        if seller not in SELLERS.values():
            raise FabError(f"listing {listing_id} is sold by {seller!r}, not Quixel")
        details = parse.asset_details(raw, fab.formats(listing_id), target)
        remember_files(details)
        return details

    @mcp.tool(
        title="Search Megascans",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    def search_assets(
        query: Annotated[str, Field(max_length=200, description="Keywords, e.g. 'mossy cobblestone'.")],
        asset_type: Annotated[
            Literal["surface", "3d", "decal", "brush"] | None,
            Field(description="Limit to one type. 'surface' is a tiling PBR material."),
        ] = None,
        source: Annotated[
            Literal["megascans", "megaplants"],
            Field(description="'megaplants' searches the Quixel Megaplants catalogue."),
        ] = "megascans",
        free_only: Annotated[
            bool, Field(description="Keep only assets whose usable licence is free right now.")
        ] = False,
        cursor: Annotated[
            str | None, Field(description="next_cursor from an earlier call, for more results.")
        ] = None,
    ) -> dict[str, Any]:
        """Search the Quixel catalogue on Fab. Returns one page of up to 24 assets with title, type,
        tags and whether they are free (with free_only, up to three pages are read to fill the list).
        Search results have no physical size or map list: use get_asset for those."""
        listing_type = parse.ASSET_TYPES.get(asset_type) if asset_type else None
        hits: list[dict] = []
        next_cursor = cursor
        try:
            for _ in range(3 if free_only else 1):
                page = fab.search(query, listing_type, SELLERS[source], next_cursor)
                found = [parse.search_hit(raw) for raw in page.get("results") or []]
                hits += [h for h in found if h["free"] or not free_only]
                next_cursor = (page.get("cursors") or {}).get("next")
                if not next_cursor or len(hits) >= 12:
                    break
        except FabError as exc:
            raise ToolError(str(exc)) from exc
        return {"results": hits, "next_cursor": next_cursor}

    @mcp.tool(
        title="Get Megascans asset",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    def get_asset(
        listing_id: ListingId,
        target_resolution: Annotated[
            Resolution, Field(description="Used to pick recommended_file.")
        ] = "2k",
    ) -> dict[str, Any]:
        """One asset's decision data: physical size or scan area, texel density, map list, licence
        price, every downloadable file with its size, a recommended file for the target resolution,
        and Fab's AI-use flag. Use get_preview to see it."""
        try:
            return load_details(listing_id, target_resolution)
        except FabError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        title="Preview Megascans asset",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    def get_preview(
        listing_id: ListingId,
        width: Annotated[int, Field(ge=144, le=1280, description="Approximate width in pixels.")] = 640,
    ) -> Image:
        """The asset's catalogue preview image, to judge how it looks. This is Fab's marketing render,
        not the texture itself."""
        try:
            url = parse.preview_url(fab.listing(listing_id), width)
            if not url:
                raise ToolError("this listing has no preview image")
            return Image(data=fab.image(url), format="jpeg")
        except FabError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        title="Create Megascans shortlist",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    def create_shortlist(
        title: Annotated[str, Field(min_length=1, max_length=120, description="Heading for the page.")],
        items: Annotated[
            list[ShortlistItem],
            Field(min_length=1, max_length=48, description="Assets in rank order, best first."),
        ],
        target_resolution: Annotated[
            Resolution, Field(description="Sets which file each card suggests downloading.")
        ] = "2k",
        open_in_browser: Annotated[
            bool, Field(description="Open the page in the user's default browser.")
        ] = True,
    ) -> dict[str, Any]:
        """Write an HTML gallery of the chosen assets (preview, free status, size, maps, suggested file
        and a link to each Fab page), and open it for the user to review. Does not download or claim
        anything. Returns the page's path and any listings that could not be loaded."""
        cards: list[dict] = []
        failed: list[dict] = []
        seen: set[str] = set()
        for item in items:
            key = item.listing_id.lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                cards.append({**load_details(key, target_resolution), "note": item.note})
            except FabError as exc:
                failed.append({"listing_id": item.listing_id, "error": str(exc)})
        if not cards:
            raise ToolError(f"none of the listings could be loaded: {failed}")

        now = datetime.now()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "shortlist"
        out_dir = state / "shortlists"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{now:%Y%m%d-%H%M%S}-{slug}.html"
        path.write_text(shortlist.render(title, cards, f"{now:%d %b %Y, %H:%M}"), encoding="utf-8")
        opened = webbrowser.open(path.as_uri()) if open_in_browser else False
        return {
            "path": str(path),
            "opened_in_browser": opened,
            "items": [
                {
                    "rank": rank,
                    "listing_id": card["listing_id"],
                    "title": card["title"],
                    "free": card["free"],
                    "suggested_file": (card["recommended_file"] or {}).get("name"),
                }
                for rank, card in enumerate(cards, 1)
            ],
            "failed": failed,
        }

    @mcp.tool(
        title="File downloaded Megascans assets",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    )
    def ingest_downloads(
        file_path: Annotated[
            str | None, Field(description="One file to ingest. Needs listing_id if it isn't recognised.")
        ] = None,
        listing_id: Annotated[
            ListingId | None, Field(description="The listing file_path came from.")
        ] = None,
        library_dir: Annotated[
            str | None, Field(description="Where to file assets. Defaults to the configured library.")
        ] = None,
    ) -> dict[str, Any]:
        """File assets the user downloaded from Fab: unpack each into its own library folder, name its
        maps consistently and write a source.json. With no file_path, looks in the downloads folder for
        files belonging to assets seen through get_asset or create_shortlist. Leaves originals in place.
        Unrecognised Fab-looking files are listed under unmatched and left alone."""
        target_library = Path(library_dir) if library_dir else default_library
        known = load_known_files()
        filed: list[dict] = []
        errors: list[dict] = []
        unmatched: list[str] = []

        if file_path:
            path = Path(file_path)
            entry = {"listing_id": listing_id} if listing_id else known.get(
                ingest.canonical_name(path.name).lower()
            )
            if not entry:
                raise ToolError(f"{path.name} isn't recognised: pass the listing_id it came from")
            candidates = [(path, entry["listing_id"])]
        else:
            candidates = []
            if downloads_dir.is_dir():
                for path in sorted(downloads_dir.iterdir()):
                    if path.suffix.lower() not in ingest.INGESTIBLE_EXT or not path.is_file():
                        continue
                    if entry := known.get(ingest.canonical_name(path.name).lower()):
                        candidates.append((path, entry["listing_id"]))
                    elif ingest.LOOKS_LIKE_FAB.search(path.name):
                        unmatched.append(path.name)

        for path, owner in candidates:
            try:
                filed.append(ingest.ingest_file(path, target_library, describe_listing(owner)))
            except ingest.IngestError as exc:
                errors.append({"file": path.name, "error": str(exc)})
        return {"filed": filed, "errors": errors, "unmatched": unmatched, "library": str(target_library)}

    def describe_listing(listing_id: str) -> dict[str, Any]:
        """What to record about a listing. Filing still works if Fab can't be reached."""
        base = {"listing_id": listing_id, "url": parse.listing_url(listing_id)}
        try:
            details = load_details(listing_id)
        except FabError:
            return base
        return {
            **base,
            "title": details["title"],
            "seller": details["seller"],
            "tags": details["tags"],
            "specs": details["specs"],
            "ai_forbidden_flag_at_filing": details["ai_forbidden_flag"],
        }

    @mcp.tool(
        title="List local Megascans library",
        annotations={"readOnlyHint": True, "destructiveHint": False},
    )
    def list_local(
        query: Annotated[
            str, Field(max_length=200, description="Words to match in title or tags. Empty lists all.")
        ] = "",
        library_dir: Annotated[
            str | None, Field(description="Library to read. Defaults to the configured library.")
        ] = None,
    ) -> dict[str, Any]:
        """Assets already filed locally by ingest_downloads, with their folders. Worth checking before
        searching Fab, as the asset may already be on disk."""
        target = Path(library_dir) if library_dir else default_library
        return {"library": str(target), "assets": ingest.list_library(target, query)}

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
