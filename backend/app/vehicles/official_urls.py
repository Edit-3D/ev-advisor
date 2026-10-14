"""Load curated manufacturer model pages separately from vehicle provenance."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_OFFICIAL_URLS_PATH = Path("data/official_model_urls.json")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key in official model URL mapping: {key}")
        result[key] = value
    return result


@lru_cache(maxsize=4)
def load_official_model_urls(
    path: str | Path = DEFAULT_OFFICIAL_URLS_PATH,
) -> dict[tuple[str, str], str]:
    """Load exact brand/model mappings and reject malformed or duplicate entries."""
    with Path(path).open(encoding="utf-8") as mapping_file:
        raw = json.load(mapping_file, object_pairs_hook=_unique_object)

    if not isinstance(raw, dict):
        raise ValueError("official model URL mapping must be a JSON object")

    flattened: dict[tuple[str, str], str] = {}
    for brand, models in raw.items():
        if not isinstance(brand, str) or not brand or not isinstance(models, dict):
            raise ValueError("official model URL mapping has an invalid manufacturer")
        for model, url in models.items():
            if not isinstance(model, str) or not model or not isinstance(url, str):
                raise ValueError(f"invalid official model URL entry for {brand}/{model}")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc or not parsed.path.strip("/"):
                raise ValueError(f"malformed official model URL for {brand}/{model}: {url}")
            flattened[(brand, model)] = url
    return flattened


def get_official_model_url(
    manufacturer: str,
    model: str,
    *,
    mapping_path: str | Path = DEFAULT_OFFICIAL_URLS_PATH,
) -> str | None:
    """Return only an exact curated brand/model match; never construct a URL."""
    return load_official_model_urls(mapping_path).get((manufacturer, model))
