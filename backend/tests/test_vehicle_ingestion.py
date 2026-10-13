import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.vehicles.ingestion import (
    DEFAULT_MANUFACTURER_LIMITS,
    ingest,
    normalize_source,
    select_vehicle_records,
)
from backend.app.vehicles.models import Vehicle


RAW_DATASET = Path("data/raw/open-ev-data-v1.24.0.json")


def source_vehicle(vehicle_id: str = "test:model:2025:base") -> dict:
    return {
        "unique_code": vehicle_id,
        "make": {"name": "Test"},
        "model": {"name": "Model"},
        "year": 2025,
        "trim": {"name": "Base"},
        "battery": {"pack_capacity_kwh_net": 70},
        "range": {"rated": [{"cycle": "wltp", "range_km": 450}]},
        "charging": {"ac": {"max_power_kw": 11}, "dc": {}},
        "sources": [{"url": "https://example.com/vehicle"}],
    }


def source_document(vehicles: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "generated_at": "2025-01-01T00:00:00Z",
        "vehicle_count": len(vehicles),
        "vehicles": vehicles,
    }


def test_actual_dataset_normalizes_deterministically(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    dataset = ingest(RAW_DATASET, first, "1.24.0")
    ingest(RAW_DATASET, second, "1.24.0")

    assert dataset.metadata.source_record_count == 1189
    assert dataset.metadata.selected_record_count == 100
    assert dataset.metadata.normalized_record_count == 100
    assert dataset.metadata.manufacturer_limits == DEFAULT_MANUFACTURER_LIMITS
    assert first.read_bytes() == second.read_bytes()


def test_default_selection_has_exact_quotas_and_all_models() -> None:
    source = json.loads(RAW_DATASET.read_text(encoding="utf-8"))
    selected = select_vehicle_records(source["vehicles"], DEFAULT_MANUFACTURER_LIMITS)

    assert Counter(record["make"]["name"] for record in selected) == Counter(
        DEFAULT_MANUFACTURER_LIMITS
    )
    for manufacturer in DEFAULT_MANUFACTURER_LIMITS:
        available_models = {
            record["model"]["name"]
            for record in source["vehicles"]
            if record["make"]["name"] == manufacturer
        }
        selected_models = {
            record["model"]["name"]
            for record in selected
            if record["make"]["name"] == manufacturer
        }
        assert selected_models == available_models


def test_selection_limits_are_configurable_and_reproducible() -> None:
    source = json.loads(RAW_DATASET.read_text(encoding="utf-8"))
    limits = {"Tesla": 2, "Volvo": 3}

    first = select_vehicle_records(source["vehicles"], limits)
    second = select_vehicle_records(source["vehicles"], limits)

    assert [record["unique_code"] for record in first] == [
        record["unique_code"] for record in second
    ]
    assert Counter(record["make"]["name"] for record in first) == Counter(limits)
    assert len({record["model"]["name"] for record in first[:2]}) == 2


def test_duplicate_ids_are_removed_in_source_order() -> None:
    duplicate = source_vehicle()
    dataset = normalize_source(source_document([duplicate, duplicate]), "test")

    assert len(dataset.vehicles) == 1
    assert dataset.metadata.duplicates_removed == 1


def test_conflicting_duplicate_ids_are_rejected() -> None:
    first = source_vehicle()
    second = source_vehicle()
    second["battery"]["pack_capacity_kwh_net"] = 80

    with pytest.raises(ValueError, match="conflicting duplicate"):
        normalize_source(source_document([first, second]), "test")


def test_invalid_source_record_reports_its_index() -> None:
    record = source_vehicle()
    del record["battery"]["pack_capacity_kwh_net"]

    with pytest.raises(ValueError, match="index 0"):
        normalize_source(source_document([record]), "test")


def test_invalid_normalized_vehicle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Vehicle.model_validate(
            {
                "id": "invalid",
                "brand": "Test",
                "model": "Model",
                "year": 2025,
                "trim": "Base",
                "battery_kwh": -1,
                "range_km": 400,
                "range_type": "wltp",
                "ranges": [{"type": "wltp", "km": 400}],
                "ac_charging_kw": 11,
                "source_url": "not-a-url",
            }
        )


def test_generated_dataset_is_valid_json() -> None:
    document = json.loads(Path("data/vehicles.json").read_text(encoding="utf-8"))
    assert document["metadata"]["source_version"] == "1.24.0"
    assert document["metadata"]["source_record_count"] == 1189
    assert document["metadata"]["selected_record_count"] == 100
    assert len(document["vehicles"]) == 100
