from argparse import ArgumentParser
from pathlib import Path
import sys


# Development-time utility for reproducibly rebuilding data/vehicles.json.
# The running application reads the generated file and does not invoke this script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.vehicles.ingestion import DEFAULT_MANUFACTURER_LIMITS, ingest


def manufacturer_limit(value: str) -> tuple[str, int]:
    try:
        manufacturer, raw_limit = value.rsplit("=", 1)
        limit = int(raw_limit)
    except ValueError as error:
        raise ValueError("manufacturer limits must use NAME=COUNT format") from error
    if not manufacturer or limit <= 0:
        raise ValueError("manufacturer limits require a name and a positive count")
    return manufacturer, limit


def main() -> None:
    parser = ArgumentParser(description="Normalize the OpenEV Data vehicle dataset.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/raw/open-ev-data-v1.24.0.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/vehicles.json"))
    parser.add_argument("--source-version", default="1.24.0")
    parser.add_argument(
        "--manufacturer-limit",
        action="append",
        metavar="NAME=COUNT",
        help="Override the default manufacturer selection; repeat for each manufacturer.",
    )
    args = parser.parse_args()

    limits = (
        dict(manufacturer_limit(value) for value in args.manufacturer_limit)
        if args.manufacturer_limit
        else DEFAULT_MANUFACTURER_LIMITS
    )

    dataset = ingest(args.source, args.output, args.source_version, limits)
    print(
        f"Normalized {dataset.metadata.normalized_record_count} vehicles "
        f"({dataset.metadata.duplicates_removed} duplicates removed) to {args.output}"
    )


if __name__ == "__main__":
    main()
