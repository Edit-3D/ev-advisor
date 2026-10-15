from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from backend.app.rag import search_ev_knowledge
from backend.app.vehicles.tools import (
    calculate_charging_cost,
    compare_vehicles,
    search_vehicles,
)


class VehicleSearchInput(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    model_year: int | None = Field(default=None, ge=1990, le=2100)
    trim: str | None = None
    variant: str | None = None
    max_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    minimum_range_km: float | None = Field(default=None, ge=0)
    range_type: str | None = None
    minimum_battery_kwh: float | None = Field(default=None, ge=0)
    body_type: str | None = None
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def price_arguments_match(self) -> "VehicleSearchInput":
        if (self.max_price is None) != (self.currency is None):
            raise ValueError("max_price and currency must be provided together")
        return self


@tool("search_vehicles", args_schema=VehicleSearchInput)
def vehicle_search_tool(**arguments: Any) -> dict[str, Any]:
    """Search curated EV configurations by identity and specification filters."""
    limit = arguments.pop("limit", 5)
    result = search_vehicles(**arguments)
    result["results"] = result["results"][:limit]
    result["returned_count"] = len(result["results"])
    return result


class VehicleComparisonInput(BaseModel):
    vehicle_ids: list[str] = Field(min_length=2, max_length=6)


@tool("compare_vehicles", args_schema=VehicleComparisonInput)
def vehicle_comparison_tool(vehicle_ids: list[str]) -> dict[str, Any]:
    """Compare two to six exact vehicle IDs returned by vehicle search."""
    return compare_vehicles(vehicle_ids)


class ChargingCostInput(BaseModel):
    energy_kwh: float = Field(gt=0)
    electricity_price_per_kwh: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    charging_efficiency: float = Field(default=0.9, gt=0, le=1)


@tool("calculate_charging_cost", args_schema=ChargingCostInput)
def charging_cost_tool(
    energy_kwh: float,
    electricity_price_per_kwh: float,
    currency: str,
    charging_efficiency: float = 0.9,
) -> dict[str, Any]:
    """Estimate charging cost using caller-provided energy, tariff, currency, and efficiency."""
    result = calculate_charging_cost(
        energy_kwh, electricity_price_per_kwh, charging_efficiency
    )
    result["currency"] = currency.upper()
    return result


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=5)


@tool("search_ev_knowledge", args_schema=KnowledgeSearchInput)
def knowledge_search_tool(query: str, top_k: int = 3) -> dict[str, Any]:
    """Retrieve citation-ready passages from the local EV knowledge base."""
    return search_ev_knowledge(query, top_k)


VEHICLE_TOOLS = [vehicle_search_tool, vehicle_comparison_tool, charging_cost_tool]
RESEARCH_TOOLS = [knowledge_search_tool]
