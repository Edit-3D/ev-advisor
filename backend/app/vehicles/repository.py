import json
from functools import lru_cache
from pathlib import Path

from backend.app.vehicles.models import Vehicle, VehicleDataset


DEFAULT_DATASET_PATH = Path("data/vehicles.json")


@lru_cache(maxsize=4)
def load_dataset(path: str | Path = DEFAULT_DATASET_PATH) -> VehicleDataset:
    dataset_path = Path(path)
    with dataset_path.open(encoding="utf-8") as dataset_file:
        return VehicleDataset.model_validate(json.load(dataset_file))


def load_vehicles(path: str | Path = DEFAULT_DATASET_PATH) -> list[Vehicle]:
    return load_dataset(path).vehicles
