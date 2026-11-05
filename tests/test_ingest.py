import json
import zipfile

import pytest

from megascans_mcp import ingest

LISTING = {"listing_id": "abc", "title": "Brick Wall", "url": "https://www.fab.com/listings/abc", "tags": ["brick"]}


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def test_maps_get_consistent_names_and_a_record(tmp_path):
    source = make_zip(
        tmp_path / "brick_wall_wgukbfj_2k.zip",
        {
            "wgukbfj_2K_BaseColor.jpg": b"c",
            "sub/wgukbfj_2K_Normal.jpg": b"n",
            "wgukbfj_2K_Displacement.exr": b"h",
            "wgukbfj.json": b"{}",
        },
    )
    result = ingest.ingest_file(source, tmp_path / "lib", LISTING)
    folder = tmp_path / "lib" / "brick_wall_wgukbfj"

    assert result["status"] == "filed"
    assert result["maps"] == ["BaseColor", "Height", "Normal"]
    assert (folder / "brick_wall_wgukbfj_2k_BaseColor.jpg").read_bytes() == b"c"
    assert (folder / "brick_wall_wgukbfj_2k_Normal.jpg").read_bytes() == b"n"
    assert (folder / "brick_wall_wgukbfj_2k_Height.exr").read_bytes() == b"h"
    assert (folder / "2k" / "wgukbfj.json").exists()

    record = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    assert record["title"] == "Brick Wall"
    assert "Fab Standard License" in record["licence"]
    assert record["normal_convention"].startswith("unverified")
    assert record["downloads"][0]["file"] == source.name
    assert source.exists(), "the original download must stay where it was"


def test_second_resolution_adds_to_the_same_asset(tmp_path):
    lib = tmp_path / "lib"
    two = make_zip(tmp_path / "brick_wall_wgukbfj_2k.zip", {"x_Normal.jpg": b"2"})
    four = make_zip(tmp_path / "brick_wall_wgukbfj_4k.zip", {"x_Normal.jpg": b"4"})
    ingest.ingest_file(two, lib, LISTING)
    ingest.ingest_file(four, lib, LISTING)
    folder = lib / "brick_wall_wgukbfj"
    assert (folder / "brick_wall_wgukbfj_2k_Normal.jpg").read_bytes() == b"2"
    assert (folder / "brick_wall_wgukbfj_4k_Normal.jpg").read_bytes() == b"4"
    record = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    assert [d["file"] for d in record["downloads"]] == [two.name, four.name]


def test_same_file_twice_is_a_no_op(tmp_path):
    source = make_zip(tmp_path / "brick_wall_wgukbfj_2k.zip", {"x_Normal.jpg": b"n"})
    ingest.ingest_file(source, tmp_path / "lib", LISTING)
    assert ingest.ingest_file(source, tmp_path / "lib", LISTING)["status"] == "already_filed"


def test_scene_files_keep_their_texture_names(tmp_path):
    source = make_zip(tmp_path / "brick_wall_wgukbfj_2k_ue_mid.zip", {"a.gltf": b"{}", "tex/a_Normal.jpg": b"n"})
    result = ingest.ingest_file(source, tmp_path / "lib", LISTING)
    folder = tmp_path / "lib" / "brick_wall_wgukbfj" / "2k_ue_mid"
    assert (folder / "a.gltf").exists() and (folder / "tex" / "a_Normal.jpg").exists()
    assert result["maps"] == [] and result["notes"]


@pytest.mark.parametrize("member", ["../evil.jpg", "..\\evil.jpg", "/evil.jpg", "C:/evil.jpg", "a/../../evil.jpg"])
@pytest.mark.parametrize("extra", [{}, {"scene.gltf": b"{}"}])
def test_archive_paths_cannot_escape(tmp_path, member, extra):
    source = make_zip(tmp_path / "evil_wgukbfj_2k.zip", {member: b"x", **extra})
    with pytest.raises(ingest.IngestError, match="unsafe path"):
        ingest.ingest_file(source, tmp_path / "lib", LISTING)
    assert not (tmp_path / "evil.jpg").exists()
    assert not (tmp_path / "lib" / "evil.jpg").exists()


def test_executables_are_not_unpacked(tmp_path):
    source = make_zip(tmp_path / "brick_wall_wgukbfj_2k.zip", {"x_Normal.jpg": b"n", "setup.exe": b"MZ"})
    result = ingest.ingest_file(source, tmp_path / "lib", LISTING)
    assert not list((tmp_path / "lib").rglob("setup.exe"))
    assert any("setup.exe" in note for note in result["notes"])


def test_partial_download_is_reported(tmp_path):
    source = tmp_path / "brick_wall_wgukbfj_2k.zip"
    source.write_bytes(b"not a zip yet")
    with pytest.raises(ingest.IngestError, match="still be downloading"):
        ingest.ingest_file(source, tmp_path / "lib", LISTING)


def test_oversized_archive_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_UNPACKED_BYTES", 3)
    source = make_zip(tmp_path / "brick_wall_wgukbfj_2k.zip", {"x_Normal.jpg": b"too big"})
    with pytest.raises(ingest.IngestError, match="refusing"):
        ingest.ingest_file(source, tmp_path / "lib", LISTING)


def test_browser_copy_name_maps_to_the_listed_name():
    assert ingest.canonical_name("brick_wall_wgukbfj_2k (1).zip") == "brick_wall_wgukbfj_2k.zip"
    assert ingest.asset_slug("brick_wall_wgukbfj_2k (1).zip") == "brick_wall_wgukbfj"
    assert ingest.asset_slug("concrete_brick_udtgcdwva_gltf_raw.zip") == "concrete_brick_udtgcdwva_gltf"


def test_list_library_filters_by_title_and_tags(tmp_path):
    source = make_zip(tmp_path / "brick_wall_wgukbfj_2k.zip", {"x_Normal.jpg": b"n"})
    ingest.ingest_file(source, tmp_path / "lib", LISTING)
    assert [a["title"] for a in ingest.list_library(tmp_path / "lib", "brick")] == ["Brick Wall"]
    assert ingest.list_library(tmp_path / "lib", "marble") == []
    assert ingest.list_library(tmp_path / "missing") == []
