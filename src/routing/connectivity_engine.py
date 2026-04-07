from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from tqdm import tqdm

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import ACS_RAW_DIR, GTFS_CURRENT_DIR, PROCESSED_DATA_DIR, PROJECT_ROOT, ensure_data_dirs
from src.gtfs.crosswalk import read_gtfs_table, resolve_project_path
from src.gtfs.service_calculator import (
    WEEKDAY_COLUMNS,
    compute_service_day_weights,
    load_calendar_dates_optional,
    parse_weekday_selection,
    prepare_calendar_df,
)


TIME_PERIOD_WINDOWS: dict[str, tuple[int, int, int]] = {
    "AM Peak": (6 * 3600, 9 * 3600, 180),
    "Midday": (9 * 3600, 15 * 3600, 360),
    "PM Peak": (15 * 3600, 18 * 3600, 180),
    "Evening": (18 * 3600, 24 * 3600, 360),
}

DEFAULT_HALF_LIFE_MINUTES = 30.0
DEFAULT_WALK_SPEED_MPS = 1.34


@dataclass(frozen=True)
class WeatherScenario:
    name: str
    walk_speed_multiplier: float
    max_walk_distance_m: float
    transfer_penalty_mins: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute schedule-based baseline tract connectivity for current GTFS "
            "under multiple weather friction scenarios."
        )
    )
    parser.add_argument(
        "--centroids-path",
        default=str(PROCESSED_DATA_DIR / "acs_demographics_centroids.geojson"),
        help="Tract centroid GeoJSON from Phase 3",
    )
    parser.add_argument(
        "--gtfs-feed-path",
        default=str(GTFS_CURRENT_DIR / "google_transit_current"),
        help="Current GTFS folder or zip",
    )
    parser.add_argument(
        "--friction-json",
        default=str(PROJECT_ROOT / "src" / "weather" / "friction_params.json"),
        help="Weather friction parameter JSON",
    )
    parser.add_argument(
        "--output-csv",
        default=str(PROCESSED_DATA_DIR / "baseline_connectivity_scores.csv"),
        help="Output baseline connectivity CSV",
    )
    parser.add_argument(
        "--time-period",
        default="AM Peak",
        help="Service time period label (AM Peak, Midday, PM Peak, Evening)",
    )
    parser.add_argument(
        "--weekday",
        default="average_weekday",
        help="Weekday mode: average_weekday or a specific weekday name",
    )
    parser.add_argument(
        "--nearest-k",
        type=int,
        default=5,
        help="Nearest candidate stops per tract",
    )
    parser.add_argument(
        "--projected-crs",
        default="EPSG:2285",
        help="Projected CRS used for distance calculations",
    )
    parser.add_argument(
        "--walk-speed-mps",
        type=float,
        default=DEFAULT_WALK_SPEED_MPS,
        help="Base walking speed in meters per second",
    )
    parser.add_argument(
        "--half-life-minutes",
        type=float,
        default=DEFAULT_HALF_LIFE_MINUTES,
        help="Half-life in minutes for accessibility decay (used when beta <= 0)",
    )
    parser.add_argument(
        "--beta",
        type=float,
        default=0.0,
        help="Direct beta value (1/min). If <= 0, beta = ln(2)/half_life_minutes",
    )
    parser.add_argument(
        "--max-ride-minutes",
        type=float,
        default=120.0,
        help="Maximum in-vehicle minutes to keep when building ride legs",
    )
    parser.add_argument(
        "--max-tracts",
        type=int,
        default=0,
        help="Optional debug cap on number of tracts (0 means all)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bars",
    )
    return parser.parse_args()


def normalize_period_label(raw_label: str) -> str:
    token = raw_label.strip().lower().replace("_", " ").replace("-", " ")
    token = " ".join(token.split())

    aliases = {
        "am peak": "AM Peak",
        "am": "AM Peak",
        "midday": "Midday",
        "pm peak": "PM Peak",
        "pm": "PM Peak",
        "evening": "Evening",
    }
    if token in aliases:
        return aliases[token]

    for name in TIME_PERIOD_WINDOWS:
        if token == name.lower():
            return name

    valid = ", ".join(TIME_PERIOD_WINDOWS)
    raise ValueError(f"Unsupported --time-period '{raw_label}'. Expected one of: {valid}")


def compute_beta(beta_arg: float, half_life_minutes: float) -> float:
    if beta_arg > 0:
        return float(beta_arg)
    if half_life_minutes <= 0:
        raise ValueError("--half-life-minutes must be > 0 when --beta <= 0")
    return float(math.log(2.0) / half_life_minutes)


def detect_latest_acs_tract_file(acs_dir: Path) -> Path:
    pattern = re.compile(r"^acs5_(\d{4})_state\d{2}_county\d{3}_tracts\.csv$")
    matched: list[tuple[int, Path]] = []

    for path in acs_dir.glob("acs5_*_tracts.csv"):
        hit = pattern.match(path.name)
        if hit:
            matched.append((int(hit.group(1)), path))

    if not matched:
        raise FileNotFoundError(f"No ACS tract file found in {acs_dir}")

    matched.sort(key=lambda item: item[0])
    return matched[-1][1]


def load_population_weights(tracts_gdf: gpd.GeoDataFrame, acs_dir: Path) -> pd.Series:
    direct_candidates = ["B01001_001E", "total_population", "population"]
    for column in direct_candidates:
        if column in tracts_gdf.columns:
            values = pd.to_numeric(tracts_gdf[column], errors="coerce").fillna(0.0)
            return values.clip(lower=0)

    latest_acs_path = detect_latest_acs_tract_file(acs_dir)
    acs_df = pd.read_csv(
        latest_acs_path,
        dtype=str,
        usecols=["state", "county", "tract", "B01001_001E"],
    )
    acs_df["geoid"] = (
        acs_df["state"].astype(str).str.zfill(2)
        + acs_df["county"].astype(str).str.zfill(3)
        + acs_df["tract"].astype(str).str.zfill(6)
    )
    acs_df["population"] = pd.to_numeric(acs_df["B01001_001E"], errors="coerce").fillna(0.0)

    lookup = acs_df.set_index("geoid")["population"]
    population = tracts_gdf["geoid"].astype(str).map(lookup).fillna(0.0)
    return population.clip(lower=0)


def load_tract_centroids(
    centroids_path: Path,
    projected_crs: str,
    acs_dir: Path,
    max_tracts: int,
) -> pd.DataFrame:
    tracts = gpd.read_file(centroids_path)
    if "geoid" not in tracts.columns:
        raise ValueError(f"Centroid file missing required column 'geoid': {centroids_path}")

    tracts = tracts.copy()
    tracts["tract_id"] = tracts["geoid"].astype(str)
    tracts = tracts.sort_values("tract_id").reset_index(drop=True)

    if max_tracts > 0:
        tracts = tracts.head(max_tracts).copy()

    population = load_population_weights(tracts, acs_dir=acs_dir)

    if {"centroid_x_m", "centroid_y_m"}.issubset(tracts.columns):
        x_values = pd.to_numeric(tracts["centroid_x_m"], errors="coerce")
        y_values = pd.to_numeric(tracts["centroid_y_m"], errors="coerce")
        valid_mask = x_values.notna() & y_values.notna()
        if not valid_mask.all():
            tracts = tracts.loc[valid_mask].copy()
            population = population.loc[valid_mask]
            x_values = x_values.loc[valid_mask]
            y_values = y_values.loc[valid_mask]
        x_m = x_values.astype(float).to_numpy()
        y_m = y_values.astype(float).to_numpy()
    elif {"centroid_lon", "centroid_lat"}.issubset(tracts.columns):
        lon = pd.to_numeric(tracts["centroid_lon"], errors="coerce")
        lat = pd.to_numeric(tracts["centroid_lat"], errors="coerce")
        valid_mask = lon.notna() & lat.notna()
        tracts = tracts.loc[valid_mask].copy()
        population = population.loc[valid_mask]

        centroid_points = gpd.GeoSeries(
            gpd.points_from_xy(lon.loc[valid_mask], lat.loc[valid_mask]),
            crs="EPSG:4326",
        ).to_crs(projected_crs)
        x_m = centroid_points.x.to_numpy()
        y_m = centroid_points.y.to_numpy()
    else:
        projected = tracts.to_crs(projected_crs)
        centroid_points = projected.geometry.centroid
        x_m = centroid_points.x.to_numpy()
        y_m = centroid_points.y.to_numpy()

    output = pd.DataFrame(
        {
            "tract_id": tracts["tract_id"].astype(str).to_numpy(),
            "population": population.to_numpy(dtype=float),
            "x_m": x_m,
            "y_m": y_m,
        }
    )
    output["population"] = output["population"].clip(lower=0)
    return output.reset_index(drop=True)


def load_stop_coordinates(feed_path: Path, projected_crs: str) -> pd.DataFrame:
    stops = read_gtfs_table(
        feed_path=feed_path,
        table_name="stops.txt",
        usecols=["stop_id", "stop_lat", "stop_lon"],
    )
    stops = stops.dropna(subset=["stop_id", "stop_lat", "stop_lon"]).copy()
    stops["stop_id"] = stops["stop_id"].astype(str)
    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    stops = stops.dropna(subset=["stop_lat", "stop_lon"]).copy()

    stop_gdf = gpd.GeoDataFrame(
        stops,
        geometry=gpd.points_from_xy(stops["stop_lon"], stops["stop_lat"]),
        crs="EPSG:4326",
    ).to_crs(projected_crs)

    output = pd.DataFrame(
        {
            "stop_id": stop_gdf["stop_id"].astype(str).to_numpy(),
            "x_m": stop_gdf.geometry.x.to_numpy(),
            "y_m": stop_gdf.geometry.y.to_numpy(),
        }
    )
    return output.drop_duplicates(subset=["stop_id"]).reset_index(drop=True)


def build_nearest_stop_links(tracts_df: pd.DataFrame, stops_df: pd.DataFrame, nearest_k: int) -> pd.DataFrame:
    if nearest_k <= 0:
        raise ValueError("--nearest-k must be > 0")
    if stops_df.empty:
        raise ValueError("No GTFS stops available for nearest-stop search")

    k_value = min(int(nearest_k), len(stops_df))

    tract_xy = tracts_df[["x_m", "y_m"]].to_numpy(dtype=float)
    stop_xy = stops_df[["x_m", "y_m"]].to_numpy(dtype=float)
    tree = cKDTree(stop_xy)

    distances, indices = tree.query(tract_xy, k=k_value)
    if k_value == 1:
        distances = distances[:, np.newaxis]
        indices = indices[:, np.newaxis]

    tract_ids = np.repeat(tracts_df["tract_id"].to_numpy(), k_value)
    flat_indices = indices.reshape(-1)
    flat_distances = distances.reshape(-1)

    links = pd.DataFrame(
        {
            "tract_id": tract_ids,
            "stop_id": stops_df.iloc[flat_indices]["stop_id"].to_numpy(),
            "distance_m": flat_distances,
        }
    )

    links = (
        links.groupby(["tract_id", "stop_id"], as_index=False)
        .agg(distance_m=("distance_m", "min"))
        .sort_values(["tract_id", "distance_m", "stop_id"])
    )
    return links.reset_index(drop=True)


def load_weather_scenarios(friction_json_path: Path) -> list[WeatherScenario]:
    with friction_json_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"Invalid friction JSON format: {friction_json_path}")

    scenarios: list[WeatherScenario] = []
    required_keys = {"walk_speed_multiplier", "max_walk_distance_m", "transfer_penalty_mins"}

    for state_name, config in payload.items():
        if not isinstance(config, dict):
            raise ValueError(f"Friction config for {state_name} must be an object")
        if set(config.keys()) != required_keys:
            raise ValueError(
                f"Friction config for {state_name} must contain keys {sorted(required_keys)}"
            )

        scenario = WeatherScenario(
            name=str(state_name),
            walk_speed_multiplier=float(config["walk_speed_multiplier"]),
            max_walk_distance_m=float(config["max_walk_distance_m"]),
            transfer_penalty_mins=float(config["transfer_penalty_mins"]),
        )
        if scenario.walk_speed_multiplier <= 0:
            raise ValueError(f"walk_speed_multiplier must be > 0 for scenario {state_name}")
        if scenario.max_walk_distance_m <= 0:
            raise ValueError(f"max_walk_distance_m must be > 0 for scenario {state_name}")
        if scenario.transfer_penalty_mins < 0:
            raise ValueError(f"transfer_penalty_mins must be >= 0 for scenario {state_name}")

        scenarios.append(scenario)

    return scenarios


def parse_gtfs_seconds(series: pd.Series) -> pd.Series:
    return pd.to_timedelta(series, errors="coerce").dt.total_seconds()


def load_active_trips(feed_path: Path, weekday_raw: str) -> tuple[pd.DataFrame, str, int]:
    trips = read_gtfs_table(
        feed_path=feed_path,
        table_name="trips.txt",
        usecols=["trip_id", "route_id", "service_id", "direction_id"],
    )
    calendar = read_gtfs_table(
        feed_path=feed_path,
        table_name="calendar.txt",
        usecols=["service_id", *WEEKDAY_COLUMNS, "start_date", "end_date"],
    )
    calendar_dates = load_calendar_dates_optional(feed_path)

    weekday_indices, weekday_mode = parse_weekday_selection(weekday_raw)
    prepared_calendar = prepare_calendar_df(calendar)
    service_day_weights, averaging_day_count = compute_service_day_weights(
        calendar_df=prepared_calendar,
        calendar_dates_df=calendar_dates,
        weekday_indices=weekday_indices,
    )

    if averaging_day_count <= 0 or service_day_weights.empty:
        raise ValueError(
            f"No active service IDs found for weekday mode '{weekday_mode}' in feed {feed_path}"
        )

    active = trips.copy()
    active["trip_id"] = active["trip_id"].astype(str)
    active["route_id"] = active["route_id"].astype(str)
    active["service_id"] = active["service_id"].astype(str)
    active["direction_id"] = active["direction_id"].fillna("-1").astype(str)
    active["line_id"] = active["route_id"] + "|" + active["direction_id"]
    active["service_weight"] = active["service_id"].map(service_day_weights).fillna(0.0)
    active = active[active["service_weight"] > 0].copy()

    if active.empty:
        raise ValueError(f"No active trips after calendar filtering for mode '{weekday_mode}'")

    active["trip_weight"] = active["service_weight"] / float(averaging_day_count)
    return active[["trip_id", "line_id", "trip_weight"]], weekday_mode, averaging_day_count


def load_filtered_stop_times(feed_path: Path, active_trips: pd.DataFrame) -> pd.DataFrame:
    stop_times = read_gtfs_table(
        feed_path=feed_path,
        table_name="stop_times.txt",
        usecols=["trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"],
    )
    stop_times["trip_id"] = stop_times["trip_id"].astype(str)
    stop_times["stop_id"] = stop_times["stop_id"].astype(str)
    stop_times["stop_sequence_num"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")
    stop_times["departure_secs"] = parse_gtfs_seconds(stop_times["departure_time"])
    stop_times["arrival_secs"] = parse_gtfs_seconds(stop_times["arrival_time"])

    merged = stop_times.merge(active_trips, on="trip_id", how="inner")
    merged = merged.dropna(subset=["stop_sequence_num", "departure_secs", "arrival_secs"]).copy()
    merged = merged.sort_values(["trip_id", "stop_sequence_num"])

    if merged.empty:
        raise ValueError("No stop_times rows remain after filtering active trips")
    return merged


def build_wait_time_table(
    stop_times: pd.DataFrame,
    period_start_secs: int,
    period_end_secs: int,
    period_duration_mins: int,
) -> dict[tuple[str, str], float]:
    period_rows = stop_times[
        (stop_times["departure_secs"] >= period_start_secs)
        & (stop_times["departure_secs"] < period_end_secs)
    ].copy()

    if period_rows.empty:
        return {}

    departures = (
        period_rows.groupby(["stop_id", "line_id"], as_index=False)
        .agg(weighted_departures=("trip_weight", "sum"))
        .sort_values(["stop_id", "line_id"])
    )
    departures = departures[departures["weighted_departures"] > 0].copy()
    departures["avg_headway_mins"] = period_duration_mins / departures["weighted_departures"]
    departures["wait_mins"] = departures["avg_headway_mins"] / 2.0

    result: dict[tuple[str, str], float] = {}
    for row in departures.itertuples(index=False):
        result[(str(row.stop_id), str(row.line_id))] = float(row.wait_mins)
    return result


def update_min(target: dict[str, float], key: str, value: float) -> None:
    previous = target.get(key)
    if previous is None or value < previous:
        target[key] = value


def build_ride_leg_maps(
    stop_times: pd.DataFrame,
    period_start_secs: int,
    period_end_secs: int,
    origin_candidates: set[str],
    destination_candidates: set[str],
    max_ride_minutes: float,
    show_progress: bool,
) -> tuple[dict[tuple[str, str], dict[str, float]], dict[tuple[str, str], dict[str, float]]]:
    rides_from: dict[tuple[str, str], dict[str, float]] = {}
    rides_to: dict[tuple[str, str], dict[str, float]] = {}

    grouped = stop_times.groupby("trip_id", sort=False)
    iterator = grouped
    if show_progress:
        iterator = tqdm(grouped, total=stop_times["trip_id"].nunique(), desc="Building ride legs")

    for _, trip_df in iterator:
        stop_ids = trip_df["stop_id"].to_numpy(dtype=str)
        departures = trip_df["departure_secs"].to_numpy(dtype=float)
        arrivals = trip_df["arrival_secs"].to_numpy(dtype=float)
        if len(stop_ids) < 2:
            continue

        line_id = str(trip_df["line_id"].iloc[0])

        in_period = (departures >= period_start_secs) & (departures < period_end_secs)
        period_indices = np.flatnonzero(in_period)
        if period_indices.size == 0:
            continue

        destination_mask = np.array([stop_id in destination_candidates for stop_id in stop_ids], dtype=bool)
        destination_suffix = np.cumsum(destination_mask[::-1])[::-1]

        n_stops = len(stop_ids)
        for origin_idx in period_indices:
            origin_stop = stop_ids[origin_idx]
            origin_departure = departures[origin_idx]
            track_first_leg = origin_stop in origin_candidates

            if origin_idx + 1 >= n_stops:
                continue
            if (not track_first_leg) and (destination_suffix[origin_idx + 1] == 0):
                continue

            for downstream_idx in range(origin_idx + 1, n_stops):
                ride_mins = (arrivals[downstream_idx] - origin_departure) / 60.0
                if not np.isfinite(ride_mins) or ride_mins <= 0:
                    continue
                if ride_mins > max_ride_minutes:
                    break

                downstream_stop = stop_ids[downstream_idx]

                if track_first_leg:
                    key_from = (origin_stop, line_id)
                    if key_from not in rides_from:
                        rides_from[key_from] = {}
                    update_min(rides_from[key_from], downstream_stop, float(ride_mins))

                if destination_mask[downstream_idx]:
                    key_to = (downstream_stop, line_id)
                    if key_to not in rides_to:
                        rides_to[key_to] = {}
                    update_min(rides_to[key_to], origin_stop, float(ride_mins))

    return rides_from, rides_to


def build_first_second_leg_costs(
    rides_from: dict[tuple[str, str], dict[str, float]],
    rides_to: dict[tuple[str, str], dict[str, float]],
    wait_by_stop_line: dict[tuple[str, str], float],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    first_leg_costs: dict[str, dict[str, float]] = {}
    second_leg_costs: dict[str, dict[str, float]] = {}

    for (origin_stop, line_id), to_map in rides_from.items():
        wait = wait_by_stop_line.get((origin_stop, line_id))
        if wait is None:
            continue

        origin_map = first_leg_costs.setdefault(origin_stop, {})
        update_min(origin_map, origin_stop, float(wait))
        for destination_stop, ride_mins in to_map.items():
            update_min(origin_map, destination_stop, float(wait + ride_mins))

    for (destination_stop, line_id), from_map in rides_to.items():
        destination_map = second_leg_costs.setdefault(destination_stop, {})
        for transfer_stop, ride_mins in from_map.items():
            wait_transfer = wait_by_stop_line.get((transfer_stop, line_id))
            if wait_transfer is None:
                continue
            update_min(destination_map, transfer_stop, float(wait_transfer + ride_mins))

    return first_leg_costs, second_leg_costs


def invert_second_leg_costs(
    second_leg_costs: dict[str, dict[str, float]]
) -> dict[str, dict[str, float]]:
    inverted: dict[str, dict[str, float]] = {}
    for destination_stop, transfer_map in second_leg_costs.items():
        for transfer_stop, cost in transfer_map.items():
            transfer_outbound = inverted.setdefault(transfer_stop, {})
            update_min(transfer_outbound, destination_stop, float(cost))
    return inverted


def build_stop_cost_matrices(
    candidate_stops: list[str],
    first_leg_costs: dict[str, dict[str, float]],
    second_leg_from_transfer: dict[str, dict[str, float]],
    show_progress: bool,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    stop_index = {stop_id: idx for idx, stop_id in enumerate(candidate_stops)}
    size = len(candidate_stops)

    direct_costs = np.full((size, size), np.inf, dtype=float)
    transfer_base_costs = np.full((size, size), np.inf, dtype=float)

    iterator = candidate_stops
    if show_progress:
        iterator = tqdm(candidate_stops, desc="Precomputing stop-level costs")

    for origin_stop in iterator:
        origin_idx = stop_index[origin_stop]
        first_map = first_leg_costs.get(origin_stop)
        if not first_map:
            continue

        direct_row = direct_costs[origin_idx]
        for destination_stop, cost in first_map.items():
            dest_idx = stop_index.get(destination_stop)
            if dest_idx is None:
                continue
            if cost < direct_row[dest_idx]:
                direct_row[dest_idx] = float(cost)

        transfer_row = transfer_base_costs[origin_idx]
        for transfer_stop, first_cost in first_map.items():
            second_map = second_leg_from_transfer.get(transfer_stop)
            if not second_map:
                continue
            for destination_stop, second_cost in second_map.items():
                dest_idx = stop_index.get(destination_stop)
                if dest_idx is None:
                    continue
                candidate_cost = float(first_cost + second_cost)
                if candidate_cost < transfer_row[dest_idx]:
                    transfer_row[dest_idx] = candidate_cost

    return direct_costs, transfer_base_costs, stop_index


def build_scenario_access_options(
    nearest_links: pd.DataFrame,
    scenario: WeatherScenario,
    stop_index: dict[str, int],
    walk_speed_mps: float,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    walk_speed_mpm = walk_speed_mps * 60.0
    effective_speed = walk_speed_mpm * scenario.walk_speed_multiplier
    if effective_speed <= 0:
        raise ValueError(f"Invalid effective walk speed for scenario {scenario.name}")

    reachable = nearest_links[nearest_links["distance_m"] <= scenario.max_walk_distance_m].copy()
    if reachable.empty:
        return {}

    reachable["access_time_mins"] = reachable["distance_m"] / effective_speed

    options: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for tract_id, group in reachable.groupby("tract_id", sort=False):
        best_by_stop: dict[int, float] = {}
        for row in group.itertuples(index=False):
            stop_id = str(row.stop_id)
            stop_idx = stop_index.get(stop_id)
            if stop_idx is None:
                continue
            access_time = float(row.access_time_mins)
            previous = best_by_stop.get(stop_idx)
            if previous is None or access_time < previous:
                best_by_stop[stop_idx] = access_time

        if not best_by_stop:
            continue

        stop_indices = np.fromiter(best_by_stop.keys(), dtype=int)
        access_times = np.fromiter(best_by_stop.values(), dtype=float)
        options[str(tract_id)] = (stop_indices, access_times)

    return options


def compute_scores_for_scenario(
    tract_ids: list[str],
    population_weights: np.ndarray,
    access_options: dict[str, tuple[np.ndarray, np.ndarray]],
    direct_costs: np.ndarray,
    transfer_base_costs: np.ndarray,
    transfer_penalty_mins: float,
    beta: float,
    show_progress: bool,
) -> tuple[np.ndarray, np.ndarray]:
    tract_count = len(tract_ids)
    stop_count = direct_costs.shape[0]

    scenario_transit = np.minimum(direct_costs, transfer_base_costs + transfer_penalty_mins)
    destination_stop_indices: list[np.ndarray] = []
    destination_access_times: list[np.ndarray] = []

    for tract_id in tract_ids:
        options = access_options.get(tract_id)
        if options is None:
            destination_stop_indices.append(np.array([], dtype=int))
            destination_access_times.append(np.array([], dtype=float))
        else:
            destination_stop_indices.append(options[0])
            destination_access_times.append(options[1])

    scores = np.zeros(tract_count, dtype=float)
    reachable_tract_counts = np.zeros(tract_count, dtype=int)

    origin_iter: list[tuple[int, str]] | tqdm = list(enumerate(tract_ids))
    if show_progress:
        origin_iter = tqdm(origin_iter, desc="Scoring tracts")

    for origin_idx, origin_tract in origin_iter:
        best_to_stop = np.full(stop_count, np.inf, dtype=float)
        origin_options = access_options.get(origin_tract)

        if origin_options is not None:
            origin_stop_indices, origin_access_times = origin_options
            for stop_idx, access_time in zip(origin_stop_indices, origin_access_times):
                candidate = scenario_transit[stop_idx] + float(access_time)
                best_to_stop = np.minimum(best_to_stop, candidate)

        best_to_tract = np.full(tract_count, np.inf, dtype=float)
        best_to_tract[origin_idx] = 0.0

        for destination_idx in range(tract_count):
            if destination_idx == origin_idx:
                continue
            d_stops = destination_stop_indices[destination_idx]
            if d_stops.size == 0:
                continue
            d_access = destination_access_times[destination_idx]
            total_values = best_to_stop[d_stops] + d_access
            best_value = float(np.min(total_values))
            if np.isfinite(best_value):
                best_to_tract[destination_idx] = best_value

        decay = np.exp(-beta * best_to_tract)
        decay[~np.isfinite(best_to_tract)] = 0.0
        scores[origin_idx] = float(np.dot(population_weights, decay))
        reachable_tract_counts[origin_idx] = int(np.isfinite(best_to_tract).sum())

    return scores, reachable_tract_counts


def validate_score_output(scores_df: pd.DataFrame) -> None:
    if scores_df.empty:
        raise ValueError("Connectivity output is empty")
    if (scores_df["connectivity_score"] < 0).any():
        raise ValueError("Connectivity scores contain negative values")
    if (~np.isfinite(scores_df["connectivity_score"])).any():
        raise ValueError("Connectivity scores contain non-finite values")

    pivot = scores_df.pivot(index="tract_id", columns="weather_scenario", values="connectivity_score")
    if "Dry / Normal" in pivot.columns and "Heavy Rain" in pivot.columns:
        reduced_count = int((pivot["Heavy Rain"] < pivot["Dry / Normal"]).sum())
        if reduced_count <= 0:
            raise ValueError("Validation failed: Heavy Rain did not reduce connectivity for any tract")


def main() -> None:
    args = parse_args()
    ensure_data_dirs()

    centroids_path = resolve_project_path(args.centroids_path)
    gtfs_feed_path = resolve_project_path(args.gtfs_feed_path)
    friction_json_path = resolve_project_path(args.friction_json)
    output_csv_path = resolve_project_path(args.output_csv)
    acs_dir = resolve_project_path(str(ACS_RAW_DIR))

    show_progress = not args.no_progress
    period_label = normalize_period_label(args.time_period)
    period_start_secs, period_end_secs, period_duration_mins = TIME_PERIOD_WINDOWS[period_label]

    beta = compute_beta(beta_arg=args.beta, half_life_minutes=float(args.half_life_minutes))
    if args.walk_speed_mps <= 0:
        raise ValueError("--walk-speed-mps must be > 0")
    if args.max_ride_minutes <= 0:
        raise ValueError("--max-ride-minutes must be > 0")

    tracts_df = load_tract_centroids(
        centroids_path=centroids_path,
        projected_crs=args.projected_crs,
        acs_dir=acs_dir,
        max_tracts=int(args.max_tracts),
    )
    if tracts_df.empty:
        raise ValueError("No tract centroids were loaded")

    stops_df = load_stop_coordinates(feed_path=gtfs_feed_path, projected_crs=args.projected_crs)
    nearest_links = build_nearest_stop_links(tracts_df=tracts_df, stops_df=stops_df, nearest_k=int(args.nearest_k))
    candidate_stops = sorted(nearest_links["stop_id"].astype(str).unique().tolist())
    candidate_set = set(candidate_stops)

    active_trips, weekday_mode, averaging_day_count = load_active_trips(
        feed_path=gtfs_feed_path,
        weekday_raw=args.weekday,
    )
    stop_times = load_filtered_stop_times(feed_path=gtfs_feed_path, active_trips=active_trips)

    wait_by_stop_line = build_wait_time_table(
        stop_times=stop_times,
        period_start_secs=period_start_secs,
        period_end_secs=period_end_secs,
        period_duration_mins=period_duration_mins,
    )
    if not wait_by_stop_line:
        raise ValueError(
            "No departures found in selected time period. Adjust --time-period or --weekday."
        )

    rides_from, rides_to = build_ride_leg_maps(
        stop_times=stop_times,
        period_start_secs=period_start_secs,
        period_end_secs=period_end_secs,
        origin_candidates=candidate_set,
        destination_candidates=candidate_set,
        max_ride_minutes=float(args.max_ride_minutes),
        show_progress=show_progress,
    )

    first_leg_costs, second_leg_costs = build_first_second_leg_costs(
        rides_from=rides_from,
        rides_to=rides_to,
        wait_by_stop_line=wait_by_stop_line,
    )
    second_leg_from_transfer = invert_second_leg_costs(second_leg_costs)

    direct_costs, transfer_base_costs, stop_index = build_stop_cost_matrices(
        candidate_stops=candidate_stops,
        first_leg_costs=first_leg_costs,
        second_leg_from_transfer=second_leg_from_transfer,
        show_progress=show_progress,
    )

    scenarios = load_weather_scenarios(friction_json_path=friction_json_path)
    tract_ids = tracts_df["tract_id"].astype(str).tolist()
    population_weights = tracts_df["population"].to_numpy(dtype=float)

    output_rows: list[dict[str, object]] = []

    for scenario in scenarios:
        access_options = build_scenario_access_options(
            nearest_links=nearest_links,
            scenario=scenario,
            stop_index=stop_index,
            walk_speed_mps=float(args.walk_speed_mps),
        )

        scenario_scores, reachable_counts = compute_scores_for_scenario(
            tract_ids=tract_ids,
            population_weights=population_weights,
            access_options=access_options,
            direct_costs=direct_costs,
            transfer_base_costs=transfer_base_costs,
            transfer_penalty_mins=scenario.transfer_penalty_mins,
            beta=beta,
            show_progress=show_progress,
        )

        for tract_id, score, reachable in zip(tract_ids, scenario_scores, reachable_counts):
            output_rows.append(
                {
                    "tract_id": tract_id,
                    "weather_scenario": scenario.name,
                    "connectivity_score": float(score),
                    "reachable_destination_tracts": int(reachable),
                }
            )

    results = pd.DataFrame(output_rows)
    validate_score_output(results)

    export = results[["tract_id", "weather_scenario", "connectivity_score"]].copy()
    export = export.sort_values(["tract_id", "weather_scenario"]).reset_index(drop=True)

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_csv_path, index=False)

    print("Baseline connectivity computation complete")
    print(f"  Tracts: {len(tract_ids)}")
    print(f"  Candidate stops (k={args.nearest_k}): {len(candidate_stops)}")
    print(f"  Weekday mode: {weekday_mode}; sampled days: {averaging_day_count}")
    print(f"  Time period: {period_label}")
    print(f"  Scenarios: {', '.join(s.name for s in scenarios)}")
    print(f"  Beta: {beta:.6f} (1/min)")
    print(f"  Output: {output_csv_path}")


if __name__ == "__main__":
    main()
