from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

GTFS_CURRENT_DIR = RAW_DATA_DIR / "gtfs_current"
GTFS_ARCHIVE_DIR = RAW_DATA_DIR / "gtfs_archive"
ACS_RAW_DIR = RAW_DATA_DIR / "acs"
NOAA_RAW_DIR = RAW_DATA_DIR / "noaa"


KCM_GTFS_URL = os.getenv(
    "KCM_GTFS_URL",
    "https://metro.kingcounty.gov/GTFS/google_transit.zip",
)
KCM_GTFS_FALLBACK_URL = os.getenv(
    "KCM_GTFS_FALLBACK_URL",
    "https://kingcounty.gov/~/media/transportation/kcdot/MetroTransit/data/google_transit.zip",
)

TRANSITLAND_API_BASE = os.getenv("TRANSITLAND_API_BASE", "https://transit.land/api/v2/rest")
TRANSITLAND_FEED_ID = os.getenv("TRANSITLAND_FEED_ID", "f-c23-metrokingcounty")
TRANSITLAND_API_KEY = os.getenv("TRANSITLAND_API_KEY", "")

CENSUS_API_BASE = os.getenv("CENSUS_API_BASE", "https://api.census.gov/data")
CENSUS_API_KEY = os.getenv("CENSUS_KEY", "")

NOAA_CDO_API_BASE = os.getenv("NOAA_CDO_API_BASE", "https://www.ncei.noaa.gov/cdo-web/api/v2")
NOAA_TOKEN = os.getenv("NOAA_TOKEN", "")
NOAA_STATION_ID = os.getenv("NOAA_STATION_ID", "GHCND:USW00024233")


WA_STATE_FIPS = os.getenv("ACS_STATE_FIPS", "53")
KING_COUNTY_FIPS = os.getenv("ACS_COUNTY_FIPS", "033")


@dataclass(frozen=True)
class BoundingBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


# Approximate King County Metro service area bounding box.
SEATTLE_SERVICE_BBOX = BoundingBox(
    min_lon=-122.53,
    min_lat=47.08,
    max_lon=-121.07,
    max_lat=47.88,
)


def ensure_data_dirs() -> None:
    for path in (
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        GTFS_CURRENT_DIR,
        GTFS_ARCHIVE_DIR,
        ACS_RAW_DIR,
        NOAA_RAW_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
