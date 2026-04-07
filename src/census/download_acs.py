from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import (
    ACS_RAW_DIR,
    CENSUS_API_BASE,
    CENSUS_API_KEY,
    KING_COUNTY_FIPS,
    WA_STATE_FIPS,
    ensure_data_dirs,
)


# Variables selected to support vulnerability proxies in Phase 1.
ACS_VARIABLES = [
    "NAME",
    "B01001_001E",  # total population
    "C17002_001E",  # total for poverty ratio
    "C17002_002E",  # under 0.50 poverty ratio
    "C17002_003E",  # 0.50 to 0.99 poverty ratio
    "B08201_001E",  # households total
    "B08201_002E",  # households with no vehicles
    "B01001_020E",  # male 65-66
    "B01001_021E",  # male 67-69
    "B01001_022E",  # male 70-74
    "B01001_023E",  # male 75-79
    "B01001_024E",  # male 80-84
    "B01001_025E",  # male 85+
    "B01001_044E",  # female 65-66
    "B01001_045E",  # female 67-69
    "B01001_046E",  # female 70-74
    "B01001_047E",  # female 75-79
    "B01001_048E",  # female 80-84
    "B01001_049E",  # female 85+
    "C18108_001E",  # civilian noninstitutionalized population
    "C18108_007E",  # with a disability
]


def census_get(
    year: int,
    geo_for: str,
    geo_in: list[str],
    variables: list[str],
    api_key: str,
) -> list[list[str]]:
    endpoint = f"{CENSUS_API_BASE}/{year}/acs/acs5"
    params: list[tuple[str, str]] = [
        ("get", ",".join(variables)),
        ("for", geo_for),
    ]
    for clause in geo_in:
        params.append(("in", clause))
    if api_key:
        params.append(("key", api_key))

    response = requests.get(endpoint, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    if not payload or not isinstance(payload, list):
        raise RuntimeError("Census API returned an empty or invalid payload")
    return payload


def save_acs_payload(payload: list[list[str]], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    columns = payload[0]
    rows = payload[1:]
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(csv_path, index=False)


def download_text(url: str, output_path: Path) -> None:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    output_path.write_text(response.text, encoding="utf-8")


def download_tiger_tract_shapefile(year: int, state_fips: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"tl_{year}_{state_fips}_tract.zip"
    zip_path = output_dir / zip_name
    extract_dir = output_dir / f"tl_{year}_{state_fips}_tract"

    tiger_url = f"https://www2.census.gov/geo/tiger/TIGER{year}/TRACT/{zip_name}"
    response = requests.get(tiger_url, timeout=240)
    response.raise_for_status()
    with zip_path.open("wb") as fh:
        fh.write(response.content)

    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_dir)

    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download ACS 5-year tract/block-group data for King County and TIGER tract shapes"
    )
    parser.add_argument("--year", type=int, default=2023)
    parser.add_argument("--state-fips", default=WA_STATE_FIPS)
    parser.add_argument("--county-fips", default=KING_COUNTY_FIPS)
    parser.add_argument("--api-key", default=CENSUS_API_KEY)
    parser.add_argument(
        "--skip-shapefile",
        action="store_true",
        help="Skip TIGER tract shapefile download",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_data_dirs()
    ACS_RAW_DIR.mkdir(parents=True, exist_ok=True)

    tracts_payload = census_get(
        year=args.year,
        geo_for="tract:*",
        geo_in=[f"state:{args.state_fips}", f"county:{args.county_fips}"],
        variables=ACS_VARIABLES,
        api_key=args.api_key,
    )
    tracts_json = ACS_RAW_DIR / f"acs5_{args.year}_state{args.state_fips}_county{args.county_fips}_tracts.json"
    tracts_csv = ACS_RAW_DIR / f"acs5_{args.year}_state{args.state_fips}_county{args.county_fips}_tracts.csv"
    save_acs_payload(tracts_payload, tracts_json, tracts_csv)
    print(f"Saved ACS tracts data: {tracts_json}")

    block_payload = census_get(
        year=args.year,
        geo_for="block group:*",
        geo_in=[
            f"state:{args.state_fips}",
            f"county:{args.county_fips}",
            "tract:*",
        ],
        variables=ACS_VARIABLES,
        api_key=args.api_key,
    )
    block_json = (
        ACS_RAW_DIR / f"acs5_{args.year}_state{args.state_fips}_county{args.county_fips}_block_groups.json"
    )
    block_csv = (
        ACS_RAW_DIR / f"acs5_{args.year}_state{args.state_fips}_county{args.county_fips}_block_groups.csv"
    )
    save_acs_payload(block_payload, block_json, block_csv)
    print(f"Saved ACS block groups data: {block_json}")

    variables_url = f"https://api.census.gov/data/{args.year}/acs/acs5/variables.html"
    variables_file = ACS_RAW_DIR / f"acs5_{args.year}_variables.html"
    download_text(variables_url, variables_file)
    print(f"Saved ACS variable catalog: {variables_file}")

    if not args.skip_shapefile:
        shapefile_dir = ACS_RAW_DIR / "shapefiles"
        tiger_zip = download_tiger_tract_shapefile(
            year=args.year,
            state_fips=args.state_fips,
            output_dir=shapefile_dir,
        )
        print(f"Saved TIGER tract shapefile zip: {tiger_zip}")


if __name__ == "__main__":
    main()
