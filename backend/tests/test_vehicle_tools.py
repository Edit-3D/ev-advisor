import pytest

from backend.app.vehicles.models import Vehicle
from backend.app.vehicles.tools import (
    calculate_charging_cost,
    compare_vehicles,
    search_vehicles,
)


def vehicle(
    vehicle_id: str,
    *,
    brand: str = "Volvo",
    battery: float = 80,
    range_km: float = 500,
    body_type: str | None = "suv",
    prices: list[dict] | None = None,
    dc_charging_kw: float | None = 200,
) -> Vehicle:
    return Vehicle.model_validate(
        {
            "id": vehicle_id,
            "brand": brand,
            "model": "Example",
            "year": 2025,
            "trim": "Base",
            "variant": None,
            "battery_kwh": battery,
            "range_km": range_km,
            "range_type": "wltp",
            "ranges": [{"type": "wltp", "km": range_km}],
            "ac_charging_kw": 11,
            "dc_charging_kw": dc_charging_kw,
            "prices": prices or [],
            "body_type": body_type,
            "source_url": "https://example.com/vehicle",
        }
    )


@pytest.fixture
def vehicles() -> list[Vehicle]:
    return [
        vehicle("volvo:one", prices=[{"amount": 500_000, "currency": "SEK"}]),
        vehicle(
            "tesla:two",
            brand="Tesla",
            battery=60,
            range_km=400,
            body_type="sedan",
            prices=[{"amount": 45_000, "currency": "USD"}],
        ),
        vehicle("volvo:three", range_km=350, dc_charging_kw=None),
    ]


def test_search_filters_available_attributes(vehicles: list[Vehicle]) -> None:
    result = search_vehicles(
        manufacturer="volvo",
        minimum_range_km=400,
        minimum_battery_kwh=70,
        body_type="SUV",
        vehicles=vehicles,
    )
    assert [item["id"] for item in result["results"]] == ["volvo:one"]


def test_price_filter_is_currency_aware(vehicles: list[Vehicle]) -> None:
    result = search_vehicles(max_price=550_000, currency="SEK", vehicles=vehicles)

    assert [item["id"] for item in result["results"]] == ["volvo:one"]
    assert result["unavailable_attribute_counts"]["price"] == 2


def test_price_filter_requires_explicit_currency(vehicles: list[Vehicle]) -> None:
    with pytest.raises(ValueError, match="currency is required"):
        search_vehicles(max_price=500_000, vehicles=vehicles)


def test_range_filter_reports_missing_requested_cycle(vehicles: list[Vehicle]) -> None:
    result = search_vehicles(
        minimum_range_km=300,
        range_type="epa",
        vehicles=vehicles,
    )
    assert result["count"] == 0
    assert result["unavailable_attribute_counts"]["range"] == 3


def test_range_type_requires_a_supported_range_filter(vehicles: list[Vehicle]) -> None:
    with pytest.raises(ValueError, match="minimum_range_km is required"):
        search_vehicles(range_type="wltp", vehicles=vehicles)
    with pytest.raises(ValueError, match="unsupported range_type"):
        search_vehicles(minimum_range_km=300, range_type="invented", vehicles=vehicles)


def test_comparison_reports_missing_values_and_unknown_ids(vehicles: list[Vehicle]) -> None:
    result = compare_vehicles(
        ["volvo:one", "volvo:three", "missing:id"], vehicles=vehicles
    )

    assert result["found_count"] == 2
    assert result["not_found_ids"] == ["missing:id"]
    assert "prices" in result["vehicles"][1]["missing_fields"]
    assert "dc_charging_kw" in result["vehicles"][1]["missing_fields"]


def test_comparison_requires_two_unique_ids(vehicles: list[Vehicle]) -> None:
    with pytest.raises(ValueError, match="at least two"):
        compare_vehicles(["volvo:one"], vehicles=vehicles)
    with pytest.raises(ValueError, match="must be unique"):
        compare_vehicles(["volvo:one", "volvo:one"], vehicles=vehicles)


def test_charging_cost_accounts_for_losses() -> None:
    result = calculate_charging_cost(60, 2.5, charging_efficiency=0.9)

    assert result["energy_added_kwh"] == 60
    assert result["energy_from_grid_kwh"] == 66.667
    assert result["estimated_cost"] == 166.67


@pytest.mark.parametrize(
    "args",
    [
        (0, 2.5, 0.9),
        (60, -1, 0.9),
        (60, 2.5, 0),
        (60, 2.5, 1.1),
    ],
)
def test_charging_cost_rejects_invalid_inputs(args: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        calculate_charging_cost(*args)
