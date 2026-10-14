import json
from pathlib import Path

import pytest

from backend.app.vehicles.official_urls import (
    get_official_model_url,
    load_official_model_urls,
)


DATASET_PATH = Path(__file__).parents[2] / "data" / "vehicles.json"


def test_every_dataset_model_has_one_reviewed_official_url() -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    dataset_models = {(item["brand"], item["model"]) for item in payload["vehicles"]}

    assert dataset_models == set(load_official_model_urls())
    assert len(dataset_models) == 25


def test_model_configurations_share_the_same_reviewed_url() -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    ex30s = [
        item
        for item in payload["vehicles"]
        if item["brand"] == "Volvo" and item["model"] == "EX30"
    ]

    assert len(ex30s) > 1
    assert {
        get_official_model_url(item["brand"], item["model"]) for item in ex30s
    } == {"https://www.volvocars.com/se/cars/ex30-electric/"}


def test_unreviewed_model_has_no_official_url() -> None:
    assert get_official_model_url("Example Motors", "Imaginary EV") is None
    assert get_official_model_url("volvo", "ex30") is None


def test_malformed_and_duplicate_mapping_entries_are_rejected(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text(
        '{"Volvo":{"EX30":"http://example.com"}}', encoding="utf-8"
    )
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"Volvo":{"EX30":"https://example.com/one",'
        '"EX30":"https://example.com/two"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="malformed official model URL"):
        load_official_model_urls(malformed)
    with pytest.raises(ValueError, match="duplicate key"):
        load_official_model_urls(duplicate)
