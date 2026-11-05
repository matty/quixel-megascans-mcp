import pytest
from conftest import FORMATS, FREE_ID, MESH_DESCRIPTION, SURFACE_DESCRIPTION

from megascans_mcp import parse, shortlist


@pytest.mark.parametrize(
    ("licences", "expected"),
    [
        ([{"name": "Personal", "priceTier": "x_USD_0_1"}], {"free": True, "price": None}),
        ([{"name": "Personal", "priceTier": "x_USD_199_1"}], {"free": False, "price": "1.99 USD"}),
        (
            [{"name": "UEFN - Reference only", "priceTier": "x_USD_0_1"}, {"name": "Personal", "priceTier": "x_USD_199_1"}],
            {"free": False, "price": "1.99 USD"},
        ),
        (
            [{"slug": "personal", "name": "Personal", "priceTier": {"price": 1.47, "currencyCode": "GBP"}}],
            {"free": False, "price": "1.47 GBP"},
        ),
        ([{"name": "Personal", "priceTier": {"price": 0.0, "currencyCode": "GBP"}}], {"free": True, "price": None}),
        ([{"name": "UEFN - Reference only", "priceTier": "x_USD_0_1"}], {"free": None, "price": None}),
        ([{"name": "Personal", "priceTier": "unexpected"}], {"free": None, "price": None}),
        ([], {"free": None, "price": None}),
    ],
)
def test_licence_status_ignores_reference_only_and_admits_unknowns(licences, expected):
    assert parse.licence_status(licences) == expected


def test_surface_specs():
    assert parse.parse_specs(SURFACE_DESCRIPTION) == {
        "texel_density_px_per_m": 2048,
        "scan_area_m": [4.0, 2.0],
        "maps": ["Displacement", "Cavity", "Gloss", "Specular", "Basecolor", "AO", "Roughness", "Normal", "Bump"],
    }


def test_mesh_specs_drop_tier_notes_from_map_names():
    specs = parse.parse_specs(MESH_DESCRIPTION)
    assert specs["physical_size_m"] == [0.1, 0.2, 0.08]
    assert specs["mesh_type"] == "Closed mesh"
    assert specs["maps"] == ["AO", "Displacement", "Specular", "Basecolor"]


def test_specs_absent_rather_than_invented():
    assert parse.parse_specs("<p>Just marketing copy.</p>") == {}
    assert parse.parse_specs("") == {}


@pytest.mark.parametrize(
    ("target", "expected"),
    [("1k", "brick_wall_wgukbfj_1k.zip"), ("2k", "brick_wall_wgukbfj_2k.zip"), ("8k", "brick_wall_wgukbfj_8k.zip")],
)
def test_recommends_texture_set_at_target(target, expected):
    files = parse.parse_files(FORMATS)
    assert parse.recommend_file(files, "material", target)["name"] == expected


def test_recommendation_never_jumps_up_when_a_smaller_file_exists():
    files = [f for f in parse.parse_files(FORMATS) if f["resolution"] in ("1k", "8k")]
    assert parse.recommend_file(files, "material", "4k")["resolution"] == "1k"


def test_mesh_tiers_map_to_sizes():
    files = [
        {"format": "fbx", "name": "a_raw.zip", "size_mb": 99, "resolution": None, "tier": "raw"},
        {"format": "fbx", "name": "a_high.zip", "size_mb": 57, "resolution": None, "tier": "high"},
        {"format": "fbx", "name": "a_mid.zip", "size_mb": 9, "resolution": None, "tier": "mid"},
    ]
    assert parse.recommend_file(files, "3d-model", "2k")["name"] == "a_mid.zip"


def test_no_recommendation_when_nothing_is_sized():
    files = [{"format": "x", "name": "extras.zip", "size_mb": 1, "resolution": None, "tier": None}]
    assert parse.recommend_file(files, "material", "2k") is None


def test_preview_picks_closest_width_and_falls_back_to_media_url():
    raw = {"thumbnails": [{"images": [{"url": "a", "width": 144}, {"url": "b", "width": 640}]}]}
    assert parse.preview_url(raw, 600) == "b"
    assert parse.preview_url({"medias": [{"type": "image", "images": [], "mediaUrl": "c"}]}) == "c"
    assert parse.preview_url({"medias": [{"type": "model", "images": [], "mediaUrl": "d"}]}) is None


def _card(**overrides):
    return {
        "url": parse.listing_url(FREE_ID),
        "title": "Brick Wall",
        "free": True,
        "price": None,
        "specs": {},
        "recommended_file": None,
        "preview_url": None,
        "note": None,
        **overrides,
    }


def test_page_escapes_everything_it_is_given():
    attack = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
    page = shortlist.render(
        attack,
        [_card(title=attack, note=attack, preview_url=f'https://media.fab.com/a.jpg"{attack}', price=attack, free=False)],
        attack,
    )
    assert "<script>" not in page
    assert "<img src=x" not in page
    assert "Content-Security-Policy" in page


def test_page_states_status_and_details():
    page = shortlist.render(
        "Walls",
        [
            _card(
                note="Right scale for the courtyard",
                specs={"scan_area_m": [4.0, 2.0], "texel_density_px_per_m": 2048, "maps": ["AO", "Normal"]},
                recommended_file={"name": "brick_2k.zip", "size_mb": 13.1},
            ),
            _card(free=False, price="0.99 USD"),
            _card(free=None),
        ],
        "5 Nov 2026",
    )
    assert "3 Megascans assets, 1 free right now" in page
    assert "4 × 2 m scan" in page and "2048 px/m" in page and "brick_2k.zip (13.1 MB)" in page
    assert "Not free yet (0.99 USD)" in page and "Price unknown" in page
    assert "Right scale for the courtyard" in page
    assert parse.listing_url(FREE_ID) in page
