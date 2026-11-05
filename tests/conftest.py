"""A fake Fab, shaped like responses captured from fab.com on 2026-11-05."""

from __future__ import annotations

import httpx
import pytest

from megascans_mcp.fab import FabClient

FREE_ID = "5d318a8f-90b5-44c2-b805-0d563a512e4c"
PAID_ID = "7d5b8684-bd22-44a6-892d-b2c2d872a248"
REFERENCE_ID = "4ee0a983-01d1-4a7c-bea3-d11ba45ceb39"
OTHER_SELLER_ID = "84fda27a-c79f-49c9-8458-82401fb37cfb"

FREE_TIER = "45da_USD_0_1701881379100"
QUIXEL = {"sellerName": "Quixel Megascans"}
IMAGES = [
    {"url": "https://media.fab.com/small.jpg", "width": 144},
    {"url": "https://media.fab.com/mid.jpg", "width": 640},
    {"url": "https://media.fab.com/big.jpg", "width": 2560},
]


def search_result(uid, title, licences, listing_type="material"):
    return {
        "uid": uid,
        "title": title,
        "listingType": listing_type,
        "isFree": False,
        "startingPrice": {"price": 0.0},
        "category": {"path": "building-human-made/brick"},
        "tags": [{"slug": "brick"}, {"slug": "wall"}],
        "licenses": licences,
        "user": QUIXEL,
    }


SEARCH = {
    "cursors": {"next": None},
    "results": [
        search_result(
            FREE_ID,
            "Brick Wall",
            [{"name": "Personal", "priceTier": FREE_TIER}, {"name": "Professional", "priceTier": FREE_TIER}],
        ),
        search_result(
            PAID_ID,
            "Red Brick Wall",
            [{"name": "Personal", "priceTier": "45da_USD_99_1"}, {"name": "Professional", "priceTier": "45da_USD_999_1"}],
        ),
        search_result(
            REFERENCE_ID,
            "Concrete Brick",
            [
                {"name": "UEFN - Reference only", "priceTier": FREE_TIER},
                {"name": "Personal", "priceTier": "45da_USD_199_1"},
            ],
            "3d-model",
        ),
    ],
}


def detail(uid, title, description, licences, seller=QUIXEL, ai_forbidden=True):
    return {
        "uid": uid,
        "title": title,
        "listingType": "material",
        "description": description,
        "isAiForbidden": ai_forbidden,
        "category": {"path": "building-human-made/brick"},
        "tags": [{"slug": "brick"}],
        "licenses": licences,
        "thumbnails": [{"type": "thumbnail", "images": IMAGES}],
        "user": seller,
    }


def priced(slug, name, price):
    return {"slug": slug, "name": name, "priceTier": {"price": price, "currencyCode": "GBP"}}


SURFACE_DESCRIPTION = (
    "<p><strong>Texel density:</strong> 2048 px/m</p><p><strong>Scan Area:</strong> 4x2 m</p>"
    "<p><strong>Maps:</strong> Displacement Cavity Gloss Specular Basecolor AO Roughness Normal Bump</p>"
    '<p><span>Create high-quality 3D experiences. <a href="https://www.fab.com/sellers/Quixel">here</a></span></p>'
)
MESH_DESCRIPTION = (
    "<p><strong>Texel density:</strong> 1249 px/m</p><p><strong>Physical size:</strong> 0.1m x 0.2m x 0.08m</p>"
    "<p><strong>Mesh type:</strong> Closed mesh</p>"
    "<p><strong>Maps:</strong> AO Displacement<em>(high tier only)</em> Specular Basecolor</p>"
)

DETAILS = {
    FREE_ID: detail(
        FREE_ID,
        "Brick Wall",
        SURFACE_DESCRIPTION,
        [priced("personal", "Personal", 0.0), priced("professional", "Professional", 0.0)],
    ),
    PAID_ID: detail(PAID_ID, "Red Brick Wall", SURFACE_DESCRIPTION, [priced("personal", "Personal", 0.73)]),
    OTHER_SELLER_ID: detail(
        OTHER_SELLER_ID, "Ultra Dynamic Sky", "", [priced("personal", "Personal", 0.0)], seller={"sellerName": "Someone"}
    ),
}


def file_group(code, *files):
    return {
        "assetFormatType": {"code": code},
        "files": [{"name": name, "fileSize": size, "uid": name} for name, size in files],
    }


FORMATS = [
    file_group(
        "texture-set",
        ("brick_wall_wgukbfj_8k.zip", 153_600_000),
        ("brick_wall_wgukbfj_4k.zip", 50_300_000),
        ("brick_wall_wgukbfj_2k.zip", 13_100_000),
        ("brick_wall_wgukbfj_1k.zip", 3_300_000),
    ),
    file_group("gltf", ("brick_wall_wgukbfj_2k_ue_mid.zip", 10_700_000)),
    file_group("additional-files", ("brick_wall_wgukbfj_8k_exr.zip", 909_200_000)),
]


class FakeFab:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.force_status: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.force_status:
            return httpx.Response(self.force_status)
        path = request.url.path
        if path == "/i/listings/search":
            return httpx.Response(200, json=SEARCH)
        if path.endswith("/asset-formats"):
            return httpx.Response(200, json=FORMATS)
        uid = path.rsplit("/", 1)[-1]
        if path.startswith("/i/listings/") and uid in DETAILS:
            return httpx.Response(200, json=DETAILS[uid])
        if request.url.host == "media.fab.com":
            return httpx.Response(200, content=b"\xff\xd8\xff fake jpeg")
        return httpx.Response(404)


@pytest.fixture
def fake_fab():
    return FakeFab()


@pytest.fixture
def client(fake_fab, tmp_path):
    return FabClient(tmp_path / "cache", transport=httpx.MockTransport(fake_fab), min_interval_s=0)
