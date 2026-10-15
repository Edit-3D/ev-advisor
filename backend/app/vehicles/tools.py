from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from backend.app.vehicles.models import Vehicle
from backend.app.vehicles.official_urls import get_official_model_url
from backend.app.vehicles.repository import DEFAULT_DATASET_PATH, load_vehicles


def _data(vehicles: Iterable[Vehicle] | None, dataset_path: str | Path) -> list[Vehicle]:
    return list(vehicles) if vehicles is not None else load_vehicles(dataset_path)


def _normalized_label(value: str) -> str:
    """Normalize user-facing labels without weakening exact field matching."""
    return " ".join(value.split()).casefold()


def _tool_vehicle(vehicle: Vehicle) -> dict[str, Any]:
    """Serialize a vehicle while preserving provenance and adding reviewed links."""
    data = vehicle.model_dump(mode="json")
    details = [vehicle.trim]
    if vehicle.variant and vehicle.variant.casefold() != vehicle.trim.casefold():
        details = (
            [vehicle.variant]
            if vehicle.trim.casefold() == "base"
            else [vehicle.trim, vehicle.variant]
        )
    configuration = " — ".join(details)
    data["configuration_label"] = (
        f"{vehicle.brand} {vehicle.model} {configuration} ({vehicle.year})"
    )
    data["official_model_url"] = get_official_model_url(vehicle.brand, vehicle.model)
    return data


def search_vehicles(
    *,
    manufacturer: str | None = None,
    model: str | None = None,
    model_year: int | None = None,
    trim: str | None = None,
    variant: str | None = None,
    max_price: float | None = None,
    currency: str | None = None,
    minimum_range_km: float | None = None,
    range_type: str | None = None,
    minimum_battery_kwh: float | None = None,
    body_type: str | None = None,
    vehicles: Iterable[Vehicle] | None = None,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> dict[str, Any]:
    """Filter vehicles without inferring absent values or converting currencies."""
    for name, value in (
        ("max_price", max_price),
        ("minimum_range_km", minimum_range_km),
        ("minimum_battery_kwh", minimum_battery_kwh),
    ):
        if value is not None and value < 0:
            raise ValueError(f"{name} cannot be negative")
    if max_price is not None and not currency:
        raise ValueError("currency is required when max_price is used")
    if currency and max_price is None:
        raise ValueError("max_price is required when currency is used")
    if range_type and minimum_range_km is None:
        raise ValueError("minimum_range_km is required when range_type is used")
    supported_range_types = {"wltp", "epa", "cltc", "nedc", "jc08", "other"}
    if range_type and range_type.casefold() not in supported_range_types:
        raise ValueError(f"unsupported range_type: {range_type}")

    requested_currency = currency.upper() if currency else None
    unavailable = {"price": 0, "range": 0}
    matches: list[Vehicle] = []
    for vehicle in _data(vehicles, dataset_path):
        if manufacturer and _normalized_label(vehicle.brand) != _normalized_label(manufacturer):
            continue
        if model and _normalized_label(vehicle.model) != _normalized_label(model):
            continue
        if model_year is not None and vehicle.year != model_year:
            continue
        if trim and _normalized_label(vehicle.trim) != _normalized_label(trim):
            continue
        if variant and (
            vehicle.variant is None
            or _normalized_label(vehicle.variant) != _normalized_label(variant)
        ):
            continue
        if body_type and _normalized_label(vehicle.body_type or "") != _normalized_label(body_type):
            continue
        if minimum_battery_kwh is not None and vehicle.battery_kwh < minimum_battery_kwh:
            continue
        if minimum_range_km is not None:
            ranges = vehicle.ranges
            if range_type:
                ranges = [item for item in ranges if item.type == range_type.casefold()]
            if not ranges:
                unavailable["range"] += 1
                continue
            if max(item.km for item in ranges) < minimum_range_km:
                continue
        if max_price is not None:
            prices = [p for p in vehicle.prices if p.currency == requested_currency]
            if not prices:
                unavailable["price"] += 1
                continue
            if min(price.amount for price in prices) > max_price:
                continue
        matches.append(vehicle)

    active_unavailable = {
        key: count
        for key, count in unavailable.items()
        if count and ((key == "price" and max_price is not None) or (key == "range" and minimum_range_km is not None))
    }
    return {
        "count": len(matches),
        "results": [_tool_vehicle(vehicle) for vehicle in matches],
        "unavailable_attribute_counts": active_unavailable,
    }


def compare_vehicles(
    vehicle_ids: list[str],
    *,
    vehicles: Iterable[Vehicle] | None = None,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> dict[str, Any]:
    if len(vehicle_ids) < 2:
        raise ValueError("at least two vehicle identifiers are required")
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise ValueError("vehicle identifiers must be unique")

    index = {vehicle.id: vehicle for vehicle in _data(vehicles, dataset_path)}
    comparisons = []
    for vehicle_id in vehicle_ids:
        vehicle = index.get(vehicle_id)
        if vehicle is None:
            continue
        data = _tool_vehicle(vehicle)
        missing = [
            field
            for field in ("variant", "dc_charging_kw", "body_type")
            if data[field] is None
        ]
        if not data["prices"]:
            missing.append("prices")
        data["missing_fields"] = missing
        comparisons.append(data)

    return {
        "requested_ids": vehicle_ids,
        "found_count": len(comparisons),
        "not_found_ids": [vehicle_id for vehicle_id in vehicle_ids if vehicle_id not in index],
        "vehicles": comparisons,
    }


def calculate_charging_cost(
    energy_kwh: float,
    electricity_price_per_kwh: float,
    charging_efficiency: float = 0.9,
) -> dict[str, float | dict[str, float]]:
    if energy_kwh <= 0:
        raise ValueError("energy_kwh must be greater than zero")
    if electricity_price_per_kwh < 0:
        raise ValueError("electricity_price_per_kwh cannot be negative")
    if not 0 < charging_efficiency <= 1:
        raise ValueError("charging_efficiency must be greater than zero and at most one")

    requested = Decimal(str(energy_kwh))
    efficiency = Decimal(str(charging_efficiency))
    unit_price = Decimal(str(electricity_price_per_kwh))
    grid_energy = requested / efficiency
    cost = grid_energy * unit_price
    return {
        "energy_added_kwh": float(requested),
        "energy_from_grid_kwh": float(grid_energy.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
        "estimated_cost": float(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "assumptions": {
            "electricity_price_per_kwh": float(unit_price),
            "charging_efficiency": float(efficiency),
        },
    }
