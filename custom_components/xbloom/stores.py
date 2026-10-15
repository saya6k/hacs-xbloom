"""XBloom's web stores per region — where the panel's shop links go.

The official app picks the store from the account's region (jadx
2026-10-15, BlurSlideHome's shop button): China → the Tmall store, Korea →
xBloom Korea's Cafe24 store, everywhere else → xbloom.com, each opened as a
web page. The panel follows the same rule, with the region chosen in its
settings or, by default, taken from Home Assistant's country.

Only xbloom.com is matched product-by-product (an official recipe named
after the bean it sells — see XBloomCloudClient.find_store_product); the
Korean store sells under Korean names and only a handful of xPods
(2026-10-15), so its links go to the store's xPod category instead.
"""
from __future__ import annotations

STORES: dict[str, dict[str, str]] = {
    "global": {
        "home": "https://xbloom.com",
        "pods": "https://xbloom.com/collections/xpods",
    },
    "kr": {
        "home": "https://xbloomkorea.cafe24.com",
        "pods": "https://xbloomkorea.cafe24.com/category/xPod/25/",
    },
    "cn": {
        "home": "https://xbloomcfdq.m.tmall.com/",
        "pods": "https://xbloomcfdq.m.tmall.com/",
    },
}
STORE_REGIONS = tuple(STORES)
_COUNTRY_REGIONS = {"KR": "kr", "CN": "cn"}


def region_for_country(country: str | None) -> str:
    """The app's rule: Korea and China have their own store."""
    return _COUNTRY_REGIONS.get((country or "").upper(), "global")


def effective_region(setting: str | None, country: str | None) -> str:
    """The chosen region, or the one Home Assistant's country implies."""
    return setting if setting in STORES else region_for_country(country)
