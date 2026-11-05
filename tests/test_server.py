"""Every tool, called the way an agent calls it: through an MCP client."""

import asyncio
import json
import zipfile

import httpx
import pytest
from conftest import FREE_ID, OTHER_SELLER_ID, PAID_ID, REFERENCE_ID
from fastmcp import Client
from fastmcp.exceptions import ToolError

from megascans_mcp.fab import FabClient, FabError
from megascans_mcp.server import build_server


@pytest.fixture
def server(client, tmp_path):
    return build_server(client, tmp_path / "state", tmp_path / "lib", tmp_path / "downloads")


def call(server, tool, **arguments):
    async def go():
        async with Client(server) as mcp:
            return await mcp.call_tool(tool, arguments)

    return asyncio.run(go())


def tools(server):
    async def go():
        async with Client(server) as mcp:
            return await mcp.list_tools()

    return asyncio.run(go())


def test_tool_surface_and_annotations(server):
    listed = {t.name: t for t in tools(server)}
    assert set(listed) == {
        "search_assets", "get_asset", "get_preview", "create_shortlist", "ingest_downloads", "list_local",
    }
    for tool in listed.values():
        assert tool.title and tool.annotations.read_only_hint is not None
        assert tool.annotations.destructive_hint is False
    for name in ("search_assets", "get_asset", "get_preview", "list_local"):
        assert listed[name].annotations.read_only_hint is True


def test_search_reports_true_free_status(server):
    hits = call(server, "search_assets", query="brick").structured_content["results"]
    assert {h["listing_id"]: h["free"] for h in hits} == {FREE_ID: True, PAID_ID: False, REFERENCE_ID: False}
    assert hits[0]["type"] == "surface" and hits[0]["url"].endswith(FREE_ID)


def test_free_only_drops_reference_only_listings(server):
    hits = call(server, "search_assets", query="brick", free_only=True).structured_content["results"]
    assert [h["listing_id"] for h in hits] == [FREE_ID]


def test_search_sends_type_and_seller(server, fake_fab):
    call(server, "search_assets", query="moss", asset_type="surface", source="megaplants")
    params = fake_fab.requests[-1].url.params
    assert params["q"] == "moss" and params["listing_types"] == "material"
    assert params["seller"] == "Quixel Megaplants"


def test_get_asset_returns_decision_data(server):
    asset = call(server, "get_asset", listing_id=FREE_ID, target_resolution="4k").structured_content
    assert asset["specs"]["scan_area_m"] == [4.0, 2.0]
    assert asset["free"] is True and asset["ai_forbidden_flag"] is True
    assert asset["recommended_file"]["name"] == "brick_wall_wgukbfj_4k.zip"
    assert asset["preview_url"] == "https://media.fab.com/mid.jpg"


def test_other_sellers_are_refused(server):
    with pytest.raises(ToolError, match="not Quixel"):
        call(server, "get_asset", listing_id=OTHER_SELLER_ID)


@pytest.mark.parametrize("bad", ["../../i/csrf", "abc", f"{FREE_ID}/ownership"])
def test_listing_ids_are_validated(server, bad):
    with pytest.raises(ToolError):
        call(server, "get_asset", listing_id=bad)


def test_preview_returns_an_image(server, fake_fab):
    result = call(server, "get_preview", listing_id=FREE_ID)
    assert result.content[0].type == "image"
    assert fake_fab.requests[-1].url.host == "media.fab.com"


def test_image_fetch_is_limited_to_fab_media(client, fake_fab):
    for url in ("https://evil.example/a.jpg", "http://media.fab.com/a.jpg", "file:///c:/secret"):
        with pytest.raises(FabError, match="refusing"):
            client.image(url)
    assert fake_fab.requests == []


def test_shortlist_writes_a_page_and_reports_failures(server, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    result = call(
        server,
        "create_shortlist",
        title="Courtyard walls",
        items=[
            {"listing_id": FREE_ID, "note": "Right scale"},
            {"listing_id": PAID_ID},
            {"listing_id": FREE_ID, "note": "duplicate"},
            {"listing_id": "00000000-0000-0000-0000-000000000000"},
        ],
    ).structured_content
    page = (tmp_path / "state" / "shortlists").glob("*courtyard-walls.html").__next__().read_text(encoding="utf-8")

    assert [i["rank"] for i in result["items"]] == [1, 2]
    assert result["items"][0]["suggested_file"] == "brick_wall_wgukbfj_2k.zip"
    assert len(result["failed"]) == 1
    assert "Right scale" in page and "duplicate" not in page
    assert opened and opened[0].startswith("file:") and result["opened_in_browser"] is True


def test_shortlist_can_stay_closed(server, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    result = call(
        server, "create_shortlist", title="x", items=[{"listing_id": FREE_ID}], open_in_browser=False
    ).structured_content
    assert opened == [] and result["opened_in_browser"] is False


def test_shortlist_with_nothing_loadable_is_an_error(server):
    with pytest.raises(ToolError, match="none of the listings"):
        call(
            server,
            "create_shortlist",
            title="x",
            items=[{"listing_id": "00000000-0000-0000-0000-000000000000"}],
            open_in_browser=False,
        )


def write_zip(path, members=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in (members or {"x_Normal.jpg": b"n"}).items():
            archive.writestr(name, data)


def test_shortlist_to_ingest_round_trip(server, tmp_path):
    call(server, "create_shortlist", title="x", items=[{"listing_id": FREE_ID}], open_in_browser=False)
    downloads = tmp_path / "downloads"
    write_zip(downloads / "brick_wall_wgukbfj_2k (1).zip")
    write_zip(downloads / "stranger_abcdefgh_2k.zip")
    write_zip(downloads / "holiday_photos.zip")

    result = call(server, "ingest_downloads").structured_content

    assert [f["file"] for f in result["filed"]] == ["brick_wall_wgukbfj_2k (1).zip"]
    assert result["unmatched"] == ["stranger_abcdefgh_2k.zip"], "unrelated files aren't mentioned"
    record = json.loads((tmp_path / "lib" / "brick_wall_wgukbfj" / "source.json").read_text(encoding="utf-8"))
    assert record["title"] == "Brick Wall" and record["listing_id"] == FREE_ID
    assert record["specs"]["texel_density_px_per_m"] == 2048

    assets = call(server, "list_local", query="brick").structured_content["assets"]
    assert assets[0]["title"] == "Brick Wall"


def test_ingest_one_file_needs_to_know_its_listing(server, tmp_path):
    path = tmp_path / "renamed.zip"
    write_zip(path)
    with pytest.raises(ToolError, match="pass the listing_id"):
        call(server, "ingest_downloads", file_path=str(path))
    result = call(server, "ingest_downloads", file_path=str(path), listing_id=FREE_ID).structured_content
    assert result["filed"][0]["status"] == "filed"


def test_ingest_still_files_when_fab_is_unavailable(server, fake_fab, tmp_path):
    path = tmp_path / "brick_wall_wgukbfj_2k.zip"
    write_zip(path)
    fake_fab.force_status = 403
    result = call(server, "ingest_downloads", file_path=str(path), listing_id=FREE_ID).structured_content
    assert result["filed"][0]["status"] == "filed"


def test_corrupt_download_is_reported_not_raised(server, tmp_path):
    call(server, "get_asset", listing_id=FREE_ID)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "brick_wall_wgukbfj_2k.zip").write_bytes(b"partial")
    result = call(server, "ingest_downloads").structured_content
    assert result["filed"] == [] and "still be downloading" in result["errors"][0]["error"]


def test_refusal_is_reported_plainly_without_retrying(server, fake_fab):
    fake_fab.force_status = 403
    with pytest.raises(ToolError, match="does not work around"):
        call(server, "search_assets", query="brick")
    assert len(fake_fab.requests) == 1


def test_client_is_honest_and_never_sends_credentials(server, fake_fab):
    call(server, "search_assets", query="brick")
    headers = fake_fab.requests[0].headers
    assert headers["user-agent"].startswith("quixel-megascans-mcp/")
    assert "authorization" not in headers and "cookie" not in headers


def test_responses_are_cached(server, fake_fab):
    call(server, "get_asset", listing_id=FREE_ID)
    count = len(fake_fab.requests)
    call(server, "get_asset", listing_id=FREE_ID)
    assert len(fake_fab.requests) == count


def test_rate_limit_gets_one_paced_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"results": []})

    client = FabClient(tmp_path, transport=httpx.MockTransport(handler), min_interval_s=0)
    assert client.search("x", None, "Quixel Megascans", None) == {"results": []}
    assert len(calls) == 2


@pytest.mark.live
def test_live_catalogue(tmp_path):
    """`uv run pytest -m live`. Fails if Fab has changed the undocumented endpoints."""
    client = FabClient(tmp_path / "cache")
    server = build_server(client, tmp_path / "state", tmp_path / "lib", tmp_path / "downloads")
    hits = call(server, "search_assets", query="brick wall", asset_type="surface").structured_content["results"]
    assert hits and all(h["type"] == "surface" and h["free"] is not None for h in hits)
    asset = call(server, "get_asset", listing_id=hits[0]["listing_id"]).structured_content
    assert asset["seller"] == "Quixel Megascans"
    assert asset["specs"].get("texel_density_px_per_m") and asset["specs"].get("maps")
    assert asset["recommended_file"]["format"] == "texture-set"
    assert call(server, "get_preview", listing_id=hits[0]["listing_id"]).content[0].type == "image"
