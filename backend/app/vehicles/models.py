from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VehicleRange(StrictModel):
    type: Literal["wltp", "epa", "cltc", "nedc", "jc08", "other"]
    km: float = Field(gt=0)


class VehiclePrice(StrictModel):
    amount: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    year: int | None = Field(default=None, ge=1990, le=2100)


class Vehicle(StrictModel):
    id: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)
    year: int = Field(ge=1990, le=2100)
    trim: str = Field(min_length=1)
    variant: str | None = None
    battery_kwh: float = Field(gt=0)
    battery_capacity_type: Literal["net"] = "net"
    range_km: float = Field(gt=0)
    range_type: Literal["wltp", "epa", "cltc", "nedc", "jc08", "other"]
    ranges: list[VehicleRange] = Field(min_length=1)
    ac_charging_kw: float = Field(gt=0)
    dc_charging_kw: float | None = Field(default=None, gt=0)
    prices: list[VehiclePrice] = Field(default_factory=list)
    body_type: str | None = None
    source_url: HttpUrl

    @model_validator(mode="after")
    def selected_range_must_be_preserved(self) -> "Vehicle":
        if not any(
            item.type == self.range_type and item.km == self.range_km
            for item in self.ranges
        ):
            raise ValueError("range_km and range_type must reference an entry in ranges")
        return self


class DatasetMetadata(StrictModel):
    source: str
    source_version: str
    source_schema_version: str
    source_generated_at: str
    normalized_schema_version: str
    license: str
    source_record_count: int = Field(ge=0)
    selected_record_count: int = Field(ge=0)
    normalized_record_count: int = Field(ge=0)
    duplicates_removed: int = Field(ge=0)
    manufacturer_limits: dict[str, int] = Field(default_factory=dict)


class VehicleDataset(StrictModel):
    metadata: DatasetMetadata
    vehicles: list[Vehicle]

    @model_validator(mode="after")
    def counts_and_ids_must_match(self) -> "VehicleDataset":
        if self.metadata.normalized_record_count != len(self.vehicles):
            raise ValueError("normalized_record_count does not match vehicles")
        ids = [vehicle.id for vehicle in self.vehicles]
        if len(ids) != len(set(ids)):
            raise ValueError("vehicle IDs must be unique")
        if self.metadata.selected_record_count < self.metadata.normalized_record_count:
            raise ValueError("selected_record_count cannot be smaller than normalized_record_count")
        return self
