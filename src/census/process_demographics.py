from __future__ import annotations

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import (
    ACS_RAW_DIR,
    KING_COUNTY_FIPS,
    PROCESSED_DATA_DIR,
    PROJECT_ROOT,
    WA_STATE_FIPS,
    ensure_data_dirs,
)

TRACT_REQUIRED_COLUMNS = [
    "state",
    "county",
    "tract",
    "B01001_001E",  # total population
    "C17002_001E",  # total poverty denominator
    "C17002_002E",  # below 0.5 poverty ratio
    "C17002_003E",  # 0.5-0.99 poverty ratio
    "B08201_001E",  # total households
    "B08201_002E",  # zero-vehicle households
    "B01001_020E",
    "B01001_021E",
    "B01001_022E",
    "B01001_023E",
    "B01001_024E",
    "B01001_025E",
    "B01001_044E",
    "B01001_045E",
    "B01001_046E",
    "B01001_047E",
    "B01001_048E",
    "B01001_049E",
    "C18108_001E",  # civilian noninstitutionalized population
    "C18108_007E",  # population with disability
]

ELDERLY_COLUMNS = [
    "B01001_020E",
    "B01001_021E",
    "B01001_022E",
    "B01001_023E",
    "B01001_024E",
    "B01001_025E",
    "B01001_044E",
    "B01001_045E",
    "B01001_046E",
    "B01001_047E",
    "B01001_048E",
    "B01001_049E",
]

METRIC_COLUMNS = [
    "pct_low_income",
    "pct_zero_vehicle_households",
    "pct_elderly_disabled",
]

OUTPUT_COLUMNS = [
    "geoid",
    "year",
    "pct_low_income",
    "pct_zero_vehicle_households",
    "pct_elderly",
    "pct_disabled",
    "pct_elderly_disabled",
    "pctile_low_income",
    "pctile_zero_vehicle_households",
    "pctile_elderly_disabled",
    "vulnerability_score",
    "vulnerability_decile",
    "vulnerable",
    "centroid_lon",
    "centroid_lat",
    "centroid_x_m",
    "centroid_y_m",
    "centroid_wkt",
    "geometry",
]


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Process ACS tract demographics, compute vulnerability metrics, and output "
            "a centroid-enhanced GeoJSON for connectivity modeling."
        )
    )
    parser.add_argument("--year", type=int, default=0, help="ACS/TIGER year (0=auto latest)")
    parser.add_argument("--state-fips", default=WA_STATE_FIPS)
    parser.add_argument("--county-fips", default=KING_COUNTY_FIPS)
    parser.add_argument(
        "--acs-dir",
        default=str(ACS_RAW_DIR),
        help="Directory containing ACS CSV files",
    )
    parser.add_argument(
        "--projected-crs",
        default="EPSG:2285",
        help="Local projected CRS for centroid distance-friendly coordinates",
    )
    parser.add_argument(
        "--output-path",
        default=str(PROCESSED_DATA_DIR / "acs_demographics_centroids.geojson"),
    )
    return parser.parse_args()


def detect_latest_acs_year(acs_dir: Path, state_fips: str, county_fips: str) -> int:
    pattern = re.compile(
        rf"^acs5_(\d{{4}})_state{state_fips}_county{county_fips}_tracts\.csv$"
    )
    years: list[int] = []
    for file_path in acs_dir.glob("acs5_*_tracts.csv"):
        match = pattern.match(file_path.name)
        if match:
            years.append(int(match.group(1)))

    if not years:
        raise FileNotFoundError(
            "No ACS tract CSV found for the provided state/county FIPS in raw ACS directory"
        )
    return max(years)


def load_acs_tract(acs_dir: Path, year: int, state_fips: str, county_fips: str) -> pd.DataFrame:
    acs_path = acs_dir / f"acs5_{year}_state{state_fips}_county{county_fips}_tracts.csv"
    if not acs_path.exists():
        raise FileNotFoundError(f"ACS tract file not found: {acs_path}")

    acs_df = pd.read_csv(acs_path, dtype=str)
    missing = [col for col in TRACT_REQUIRED_COLUMNS if col not in acs_df.columns]
    if missing:
        raise ValueError(f"ACS tract file is missing required columns: {missing}")

    acs_df["state"] = acs_df["state"].str.zfill(2)
    acs_df["county"] = acs_df["county"].str.zfill(3)
    acs_df["tract"] = acs_df["tract"].str.zfill(6)
    acs_df["geoid"] = acs_df["state"] + acs_df["county"] + acs_df["tract"]

    return acs_df


def resolve_tract_shapefile(acs_dir: Path, year: int, state_fips: str) -> Path:
    candidate = acs_dir / "shapefiles" / f"tl_{year}_{state_fips}_tract" / f"tl_{year}_{state_fips}_tract.shp"
    if candidate.exists():
        return candidate

    fallback_candidates = sorted((acs_dir / "shapefiles").glob(f"**/tl_{year}_{state_fips}_tract.shp"))
    if fallback_candidates:
        return fallback_candidates[0]

    raise FileNotFoundError(
        "Could not find tract shapefile for year/state. "
        f"Expected path similar to {candidate}"
    )


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    den = denominator.replace({0: np.nan})
    return numerator / den


def build_metric_frame(acs_df: pd.DataFrame) -> pd.DataFrame:
    frame = acs_df.copy()

    numeric_columns = [
        column
        for column in TRACT_REQUIRED_COLUMNS
        if column not in {"state", "county", "tract"}
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    low_income_numerator = frame["C17002_002E"].fillna(0) + frame["C17002_003E"].fillna(0)
    frame["pct_low_income"] = safe_divide(low_income_numerator, frame["C17002_001E"])
    frame["pct_zero_vehicle_households"] = safe_divide(frame["B08201_002E"], frame["B08201_001E"])

    frame["elderly_population"] = frame[ELDERLY_COLUMNS].fillna(0).sum(axis=1)
    frame["pct_elderly"] = safe_divide(frame["elderly_population"], frame["B01001_001E"])
    frame["pct_disabled"] = safe_divide(frame["C18108_007E"], frame["C18108_001E"])
    frame["pct_elderly_disabled"] = frame[["pct_elderly", "pct_disabled"]].mean(axis=1, skipna=True)

    for metric in METRIC_COLUMNS:
        percentile_column = metric.replace("pct_", "pctile_")
        frame[percentile_column] = frame[metric].rank(pct=True, method="average")

    percentile_columns = [metric.replace("pct_", "pctile_") for metric in METRIC_COLUMNS]
    frame["vulnerability_score"] = frame[percentile_columns].mean(axis=1, skipna=True)

    score_rank = frame["vulnerability_score"].rank(pct=True, method="average")
    frame["vulnerability_decile"] = np.ceil(score_rank * 10).astype("Int64")

    threshold = frame["vulnerability_score"].quantile(0.75)
    if pd.isna(threshold):
        frame["vulnerable"] = False
    else:
        frame["vulnerable"] = frame["vulnerability_score"] >= float(threshold)

    return frame


def merge_with_geometry(
    metric_df: pd.DataFrame,
    shapefile_path: Path,
    state_fips: str,
    county_fips: str,
    projected_crs: str,
) -> gpd.GeoDataFrame:
    tracts = gpd.read_file(shapefile_path)
    tracts = tracts[
        (tracts["STATEFP"].astype(str).str.zfill(2) == str(state_fips).zfill(2))
        & (tracts["COUNTYFP"].astype(str).str.zfill(3) == str(county_fips).zfill(3))
    ].copy()

    tracts["geoid"] = tracts["GEOID"].astype(str)

    merged = tracts.merge(metric_df, on="geoid", how="inner")
    if merged.empty:
        raise ValueError("No tract geometry matched ACS GEOID values")

    merged_gdf = gpd.GeoDataFrame(merged, geometry="geometry", crs=tracts.crs)

    projected = merged_gdf.to_crs(projected_crs)
    projected_centroids = projected.geometry.centroid
    centroid_wgs84 = gpd.GeoSeries(projected_centroids, crs=projected_crs).to_crs("EPSG:4326")

    merged_gdf["centroid_x_m"] = projected_centroids.x
    merged_gdf["centroid_y_m"] = projected_centroids.y
    merged_gdf["centroid_lon"] = centroid_wgs84.x
    merged_gdf["centroid_lat"] = centroid_wgs84.y
    merged_gdf["centroid_wkt"] = centroid_wgs84.to_wkt()

    merged_gdf = merged_gdf.to_crs("EPSG:4326")

    return merged_gdf


def main() -> None:
    args = parse_args()
    ensure_data_dirs()

    acs_dir = resolve_project_path(args.acs_dir)
    output_path = resolve_project_path(args.output_path)

    year = args.year if args.year > 0 else detect_latest_acs_year(acs_dir, args.state_fips, args.county_fips)

    acs_df = load_acs_tract(
        acs_dir=acs_dir,
        year=year,
        state_fips=args.state_fips,
        county_fips=args.county_fips,
    )
    metric_df = build_metric_frame(acs_df)

    shapefile_path = resolve_tract_shapefile(acs_dir=acs_dir, year=year, state_fips=args.state_fips)
    output_gdf = merge_with_geometry(
        metric_df=metric_df,
        shapefile_path=shapefile_path,
        state_fips=args.state_fips,
        county_fips=args.county_fips,
        projected_crs=args.projected_crs,
    )

    output_gdf["year"] = year

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_gdf[OUTPUT_COLUMNS].to_file(output_path, driver="GeoJSON")

    vulnerable_count = int(output_gdf["vulnerable"].fillna(False).sum())
    print(f"Year: {year}")
    print(f"ACS rows: {len(acs_df)}")
    print(f"Output rows: {len(output_gdf)}")
    print(f"Vulnerable tracts: {vulnerable_count}")
    print(f"Output CRS: {output_gdf.crs}")
    print(f"Output file: {output_path}")


if __name__ == "__main__":
    main()
