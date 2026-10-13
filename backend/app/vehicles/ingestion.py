from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from backend.app.vehicles.models import (
    DatasetMetadata,
    Vehicle,
    VehicleDataset,
    VehiclePrice,
    VehicleRange,
)


RANGE_PRIORITY = ("wltp", "epa", "cltc", "nedc", "jc08", "other")
DEFAULT_MANUFACTURER_LIMITS = {
    "Tesla": 18,
    "Volvo": 18,
    "BMW": 28,
    "Volkswagen": 20,
    "Hyundai": 16,
}


def _completeness(record: dict[str, Any]) -> int:
    return sum(
        value is not None
        for value in (
            record.get("battery", {}).get("pack_capacity_kwh_net"),
            record.get("range", {}).get("rated"),
            record.get("charging", {}).get("ac", {}).get("max_power_kw"),
            record.get("charging", {}).get("dc", {}).get("max_power_kw"),
        )
    )


def _difference_values(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("battery", {}).get("pack_capacity_kwh_net"),
        record.get("powertrain", {}).get("drivetrain"),
        record.get("charging", {}).get("ac", {}).get("max_power_kw"),
        record.get("charging", {}).get("dc", {}).get("max_power_kw"),
        record.get("trim", {}).get("name"),
        record.get("variant", {}).get("name"),
    )


def select_vehicle_records(
    records: list[dict[str, Any]], manufacturer_limits: Mapping[str, int]
) -> list[dict[str, Any]]:
    """Select broad model coverage, then differentiated recent configurations."""
    selected_all: list[dict[str, Any]] = []
    for manufacturer, limit in manufacturer_limits.items():
        if limit <= 0:
            raise ValueError(f"record limit for {manufacturer} must be greater than zero")
        candidates = [
            record
            for record in records
            if record.get("make", {}).get("name", "").casefold()
            == manufacturer.casefold()
        ]
        if len(candidates) < limit:
            raise ValueError(
                f"requested {limit} {manufacturer} records, but only {len(candidates)} are available"
            )

        by_model: dict[str, list[dict[str, Any]]] = {}
        for record in candidates:
            by_model.setdefault(record["model"]["name"], []).append(record)

        def base_key(record: dict[str, Any]) -> tuple[Any, ...]:
            return (-_completeness(record), -record["year"], record["unique_code"])

        model_representatives = [
            min(model_records, key=base_key) for model_records in by_model.values()
        ]
        model_representatives.sort(key=base_key)
        selected = model_representatives[:limit]
        selected_ids = {record["unique_code"] for record in selected}

        while len(selected) < limit:
            seen_by_dimension = [
                {values[index] for values in map(_difference_values, selected)}
                for index in range(6)
            ]
            seen_signatures = {_difference_values(record) for record in selected}

            def fill_key(record: dict[str, Any]) -> tuple[Any, ...]:
                values = _difference_values(record)
                novel_dimensions = sum(
                    value not in seen_by_dimension[index]
                    for index, value in enumerate(values)
                )
                return (
                    -(values not in seen_signatures),
                    -novel_dimensions,
                    -_completeness(record),
                    -record["year"],
                    record["unique_code"],
                )

            remaining = [
                record for record in candidates if record["unique_code"] not in selected_ids
            ]
            chosen = min(remaining, key=fill_key)
            selected.append(chosen)
            selected_ids.add(chosen["unique_code"])

        selected_all.extend(selected)
    return selected_all


def _required_name(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise ValueError(f"{field}.name is required")
    return value["name"]


def normalize_vehicle(record: dict[str, Any]) -> Vehicle:
    rated = record.get("range", {}).get("rated", [])
    ranges = [
        VehicleRange(type=item["cycle"], km=item["range_km"])
        for item in rated
    ]
    selected = min(ranges, key=lambda item: RANGE_PRIORITY.index(item.type))

    prices = [
        VehiclePrice(
            amount=item["amount"],
            currency=item["currency"],
            country=item.get("country"),
            year=item.get("year"),
        )
        for item in record.get("pricing", {}).get("msrp", [])
    ]
    sources = record.get("sources", [])
    if not sources or not sources[0].get("url"):
        raise ValueError("at least one source URL is required")

    variant = record.get("variant", {}).get("name")
    return Vehicle(
        id=record["unique_code"],
        brand=_required_name(record, "make"),
        model=_required_name(record, "model"),
        year=record["year"],
        trim=_required_name(record, "trim"),
        variant=variant,
        battery_kwh=record["battery"]["pack_capacity_kwh_net"],
        range_km=selected.km,
        range_type=selected.type,
        ranges=ranges,
        ac_charging_kw=record["charging"]["ac"]["max_power_kw"],
        dc_charging_kw=record["charging"].get("dc", {}).get("max_power_kw"),
        prices=prices,
        body_type=record.get("body", {}).get("style") or record.get("vehicle_type"),
        source_url=sources[0]["url"],
    )


def normalize_source(
    source: dict[str, Any],
    source_version: str,
    manufacturer_limits: Mapping[str, int] | None = None,
) -> VehicleDataset:
    records = source.get("vehicles")
    if not isinstance(records, list):
        raise ValueError("source vehicles must be a list")
    if source.get("vehicle_count") != len(records):
        raise ValueError("source vehicle_count does not match vehicles")

    selected_records = (
        select_vehicle_records(records, manufacturer_limits)
        if manufacturer_limits is not None
        else records
    )
    vehicles_by_id: dict[str, Vehicle] = {}
    for index, record in enumerate(selected_records):
        try:
            vehicle = normalize_vehicle(record)
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise ValueError(f"invalid source vehicle at index {index}: {error}") from error
        existing = vehicles_by_id.get(vehicle.id)
        if existing is not None and existing != vehicle:
            raise ValueError(f"conflicting duplicate vehicle ID at index {index}: {vehicle.id}")
        vehicles_by_id.setdefault(vehicle.id, vehicle)

    vehicles = list(vehicles_by_id.values())
    return VehicleDataset(
        metadata=DatasetMetadata(
            source="OpenEV Data",
            source_version=source_version,
            source_schema_version=source["schema_version"],
            source_generated_at=source["generated_at"],
            normalized_schema_version="1.0.0",
            license="CDLA-Permissive-2.0",
            source_record_count=len(records),
            selected_record_count=len(selected_records),
            normalized_record_count=len(vehicles),
            duplicates_removed=len(selected_records) - len(vehicles),
            manufacturer_limits=dict(manufacturer_limits or {}),
        ),
        vehicles=vehicles,
    )


def ingest(
    source_path: Path,
    output_path: Path,
    source_version: str,
    manufacturer_limits: Mapping[str, int] | None = DEFAULT_MANUFACTURER_LIMITS,
) -> VehicleDataset:
    with source_path.open(encoding="utf-8") as source_file:
        source = json.load(source_file)
    dataset = normalize_source(source, source_version, manufacturer_limits)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dataset.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dataset
