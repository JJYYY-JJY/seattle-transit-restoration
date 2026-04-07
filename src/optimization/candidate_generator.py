from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from tqdm import tqdm

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import ACS_RAW_DIR, GTFS_CURRENT_DIR, PROCESSED_DATA_DIR, PROJECT_ROOT, ensure_data_dirs
from src.gtfs.crosswalk import read_gtfs_table, resolve_project_path
from src.routing.connectivity_engine import (
    TIME_PERIOD_WINDOWS,
    load_stop_coordinates,
    load_tract_centroids,
    parse_gtfs_seconds,
)


GAP_KEYS = ["route_id", "direction_id", "time_period"]
SERVICE_PANEL_REQUIRED_COLUMNS = [
    "version_id",
    "route_id",
    "direction_id",
    "time_period",
    "trip_count",
    "avg_headway",
    "service_hours",
]
BASELINE_REQUIRED_COLUMNS = ["tract_id", "weather_scenario", "connectivity_score"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Phase 6 restoration candidates and precompute marginal "
            "connectivity gains for optimization."
        )
    )
    parser.add_argument(
        "--service-panel-path",
        default=str(PROCESSED_DATA_DIR / "service_panel_route_period.csv"),
        help="Route-period service panel from Phase 2",
    )
    parser.add_argument(
        "--baseline-connectivity-path",
        default=str(PROCESSED_DATA_DIR / "baseline_connectivity_scores.csv"),
        help="Baseline tract weather connectivity scores from Phase 5",
    )
    parser.add_argument(
        "--weather-probability-path",
        default=str(PROCESSED_DATA_DIR / "weather_probabilities.csv"),
        help="Weather scenario probability table from Phase 4 (optional but recommended)",
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
        help="Weather friction parameter JSON from Phase 4",
    )
    parser.add_argument(
        "--candidate-output",
        default=str(PROCESSED_DATA_DIR / "candidate_library.csv"),
        help="Output candidate library CSV",
    )
    parser.add_argument(
        "--delta-output",
        default=str(PROCESSED_DATA_DIR / "marginal_gains_delta.csv"),
        help="Output marginal gains CSV",
    )
    parser.add_argument(
        "--current-version-id",
        default="",
        help="Override current GTFS version_id. If empty, inferred from panel.",
    )
    parser.add_argument(
        "--increment-trip-size",
        type=float,
        default=2.0,
        help="Discrete candidate increment size in trips per period",
    )
    parser.add_argument(
        "--min-gap-threshold",
        type=float,
        default=1e-6,
        help="Minimum positive gap to keep",
    )
    parser.add_argument(
        "--projected-crs",
        default="EPSG:2285",
        help="Projected CRS for distance calculations",
    )
    parser.add_argument(
        "--exposure-decay-m",
        type=float,
        default=900.0,
        help="Distance decay scale in meters for route exposure",
    )
    parser.add_argument(
        "--exposure-cutoff-m",
        type=float,
        default=4000.0,
        help="Distance cutoff in meters beyond which exposure is zero",
    )
    parser.add_argument(
        "--delta-scale",
        type=float,
        default=0.08,
        help="Global calibration factor for marginal gains",
    )
    parser.add_argument(
        "--sparsity-threshold",
        type=float,
        default=1e-9,
        help="Drop delta rows with score <= threshold",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bars",
    )
    return parser.parse_args()


def normalize_period_label(raw_label: str) -> str:
    token = str(raw_label).strip().lower().replace("_", " ").replace("-", " ")
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
    for key in TIME_PERIOD_WINDOWS:
        if token == key.lower():
            return key

    valid = ", ".join(TIME_PERIOD_WINDOWS.keys())
    raise ValueError(f"Unsupported time period '{raw_label}'. Expected one of: {valid}")


def assign_time_periods(departure_seconds: pd.Series) -> pd.Series:
    labels: list[str] = []
    conditions: list[pd.Series] = []
    for label, (start_sec, end_sec, _) in TIME_PERIOD_WINDOWS.items():
        labels.append(label)
        conditions.append((departure_seconds >= start_sec) & (departure_seconds < end_sec))

    result = pd.Series(np.select(conditions, labels, default=""), index=departure_seconds.index)
    result.loc[result == ""] = pd.NA
    return result


def load_service_panel(service_panel_path: Path) -> pd.DataFrame:
    panel = pd.read_csv(service_panel_path, dtype=str)
    missing_cols = [col for col in SERVICE_PANEL_REQUIRED_COLUMNS if col not in panel.columns]
    if missing_cols:
        raise ValueError(f"service panel missing required columns: {missing_cols}")

    panel = panel[SERVICE_PANEL_REQUIRED_COLUMNS].copy()
    panel["version_id"] = panel["version_id"].astype(str).str.strip()
    panel["route_id"] = panel["route_id"].astype(str).str.strip()
    panel["direction_id"] = panel["direction_id"].fillna("-1").astype(str).str.strip()
    panel["time_period"] = panel["time_period"].astype(str).map(normalize_period_label)

    panel["trip_count"] = pd.to_numeric(panel["trip_count"], errors="coerce").fillna(0.0)
    panel["avg_headway"] = pd.to_numeric(panel["avg_headway"], errors="coerce")
    panel["service_hours"] = pd.to_numeric(panel["service_hours"], errors="coerce").fillna(0.0)

    panel = panel.dropna(subset=["route_id", "direction_id", "time_period", "version_id"]).copy()
    if panel.empty:
        raise ValueError("service panel is empty after required-field cleaning")
    return panel


def infer_current_version_id(panel_df: pd.DataFrame, requested_version_id: str) -> str:
    available = panel_df["version_id"].astype(str)
    if requested_version_id:
        token = str(requested_version_id).strip()
        if token not in set(available):
            raise ValueError(
                f"Requested --current-version-id '{token}' not found in service panel"
            )
        return token

    lower = available.str.lower()
    if lower.eq("current").any():
        return available.loc[lower.eq("current")].iloc[0]

    numeric = pd.to_numeric(available, errors="coerce")
    if numeric.notna().any():
        idx = numeric.idxmax()
        return str(available.loc[idx])

    return sorted(set(available))[-1]


def build_gap_table(panel_df: pd.DataFrame, current_version_id: str, min_gap_threshold: float) -> pd.DataFrame:
    panel = panel_df.copy()
    panel["runtime_h_per_trip"] = np.where(
        panel["trip_count"] > 0,
        panel["service_hours"] / panel["trip_count"],
        np.nan,
    )

    runtime_df = panel[(panel["trip_count"] > 0) & (panel["service_hours"] > 0)].copy()
    global_runtime = runtime_df["runtime_h_per_trip"].median()
    if not np.isfinite(global_runtime) or global_runtime <= 0:
        global_runtime = 0.5

    runtime_by_key = (
        runtime_df.groupby(GAP_KEYS, as_index=False)
        .agg(total_service_hours=("service_hours", "sum"), total_trip_count=("trip_count", "sum"))
        .assign(avg_trip_runtime_h=lambda x: x["total_service_hours"] / x["total_trip_count"])
    )

    max_service = (
        panel.groupby(GAP_KEYS, as_index=False)
        .agg(q_max=("trip_count", "max"), best_headway=("avg_headway", "min"))
    )

    current_service = (
        panel[panel["version_id"] == current_version_id]
        .groupby(GAP_KEYS, as_index=False)
        .agg(q_current=("trip_count", "sum"), current_headway=("avg_headway", "mean"))
    )

    gaps = max_service.merge(current_service, on=GAP_KEYS, how="left")
    gaps["q_current"] = gaps["q_current"].fillna(0.0)
    gaps["service_gap_u"] = (gaps["q_max"] - gaps["q_current"]).clip(lower=0.0)
    gaps = gaps[gaps["service_gap_u"] > float(min_gap_threshold)].copy()

    if gaps.empty:
        raise ValueError("No positive historical service gaps were found")

    gaps = gaps.merge(runtime_by_key[GAP_KEYS + ["avg_trip_runtime_h"]], on=GAP_KEYS, how="left")
    gaps["avg_trip_runtime_h"] = (
        gaps["avg_trip_runtime_h"].fillna(float(global_runtime)).clip(lower=1e-4)
    )

    period_minutes = {name: duration for name, (_, _, duration) in TIME_PERIOD_WINDOWS.items()}
    gaps["period_minutes"] = gaps["time_period"].map(period_minutes).astype(float)
    gaps["headway_at_qmax"] = np.where(
        gaps["q_max"] > 0,
        gaps["period_minutes"] / gaps["q_max"],
        np.nan,
    )

    gaps = gaps.sort_values(
        ["service_gap_u", "route_id", "direction_id", "time_period"],
        ascending=[False, True, True, True],
    )
    return gaps.reset_index(drop=True)


def discretize_candidates(
    gap_df: pd.DataFrame,
    increment_trip_size: float,
    min_gap_threshold: float,
) -> pd.DataFrame:
    if increment_trip_size <= 0:
        raise ValueError("--increment-trip-size must be > 0")

    rows: list[dict[str, object]] = []
    candidate_seq = 1

    for row in gap_df.itertuples(index=False):
        remaining = float(row.service_gap_u)
        step_idx = 1

        while remaining > min_gap_threshold:
            increment = min(float(increment_trip_size), remaining)
            q_after = float(row.q_current) + increment
            service_gain_scalar = increment / max(q_after, 1e-6)
            cost_cj = increment * float(row.avg_trip_runtime_h)

            rows.append(
                {
                    "candidate_id": f"C{candidate_seq:06d}",
                    "route_id": str(row.route_id),
                    "direction_id": str(row.direction_id),
                    "time_period": str(row.time_period),
                    "step_index": int(step_idx),
                    "increment_trips": float(increment),
                    "cost_cj": float(cost_cj),
                    "q_current": float(row.q_current),
                    "q_max": float(row.q_max),
                    "service_gap_u": float(row.service_gap_u),
                    "avg_trip_runtime_h": float(row.avg_trip_runtime_h),
                    "service_gain_scalar": float(service_gain_scalar),
                }
            )

            remaining -= increment
            step_idx += 1
            candidate_seq += 1

    candidates = pd.DataFrame(rows)
    if candidates.empty:
        raise ValueError("Candidate library is empty after discretization")

    period_minutes = {name: duration for name, (_, _, duration) in TIME_PERIOD_WINDOWS.items()}
    candidates["period_minutes"] = candidates["time_period"].map(period_minutes).astype(float)
    candidates["headway_before_mins"] = np.where(
        candidates["q_current"] > 0,
        candidates["period_minutes"] / candidates["q_current"],
        np.nan,
    )
    candidates["headway_after_mins"] = np.where(
        (candidates["q_current"] + candidates["increment_trips"]) > 0,
        candidates["period_minutes"] / (candidates["q_current"] + candidates["increment_trips"]),
        np.nan,
    )
    candidates["headway_improvement_mins"] = (
        candidates["headway_before_mins"] - candidates["headway_after_mins"]
    )

    return candidates


def load_baseline_matrix(baseline_path: Path) -> tuple[list[str], list[str], np.ndarray]:
    baseline = pd.read_csv(baseline_path, dtype=str)
    missing_cols = [col for col in BASELINE_REQUIRED_COLUMNS if col not in baseline.columns]
    if missing_cols:
        raise ValueError(f"baseline connectivity missing required columns: {missing_cols}")

    baseline = baseline[BASELINE_REQUIRED_COLUMNS].copy()
    baseline["tract_id"] = baseline["tract_id"].astype(str)
    baseline["weather_scenario"] = baseline["weather_scenario"].astype(str)
    baseline["connectivity_score"] = pd.to_numeric(
        baseline["connectivity_score"], errors="coerce"
    ).fillna(0.0)

    pivot = (
        baseline.pivot_table(
            index="tract_id",
            columns="weather_scenario",
            values="connectivity_score",
            aggfunc="mean",
            fill_value=0.0,
        )
        .sort_index(axis=0)
        .sort_index(axis=1)
    )

    if pivot.empty:
        raise ValueError("baseline connectivity table is empty")

    tract_ids = pivot.index.astype(str).tolist()
    scenario_names = pivot.columns.astype(str).tolist()
    matrix = pivot.to_numpy(dtype=float)
    return tract_ids, scenario_names, matrix


def load_weather_gain_factors(friction_json_path: Path, scenario_names: list[str]) -> np.ndarray:
    if not friction_json_path.exists():
        return np.ones(len(scenario_names), dtype=float)

    with friction_json_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict) or not payload:
        return np.ones(len(scenario_names), dtype=float)

    raw_scores: dict[str, float] = {}
    for name, config in payload.items():
        if not isinstance(config, dict):
            continue
        walk_speed = float(config.get("walk_speed_multiplier", 1.0))
        max_walk = float(config.get("max_walk_distance_m", 800.0))
        transfer_penalty = float(config.get("transfer_penalty_mins", 5.0))
        raw = (walk_speed * max_walk) / max(1.0 + transfer_penalty, 1e-6)
        raw_scores[str(name)] = max(raw, 1e-9)

    reference = raw_scores.get("Dry / Normal")
    if reference is None:
        reference = max(raw_scores.values()) if raw_scores else 1.0

    factors: list[float] = []
    for scenario in scenario_names:
        raw_value = raw_scores.get(scenario)
        if raw_value is None:
            factors.append(1.0)
        else:
            factors.append(float(np.clip(raw_value / reference, 0.25, 1.25)))

    return np.array(factors, dtype=float)


def load_scenario_probabilities(probability_path: Path, scenario_names: list[str]) -> np.ndarray:
    if not probability_path.exists():
        return np.full(len(scenario_names), 1.0 / max(len(scenario_names), 1), dtype=float)

    table = pd.read_csv(probability_path)
    expected_cols = {"season_or_month", "weather_state", "probability"}
    if not expected_cols.issubset(set(table.columns)):
        return np.full(len(scenario_names), 1.0 / max(len(scenario_names), 1), dtype=float)

    annual = table[table["season_or_month"].astype(str).str.lower() == "annual"].copy()
    if annual.empty:
        return np.full(len(scenario_names), 1.0 / max(len(scenario_names), 1), dtype=float)

    annual["weather_state"] = annual["weather_state"].astype(str)
    annual["probability"] = pd.to_numeric(annual["probability"], errors="coerce").fillna(0.0)
    lookup = annual.set_index("weather_state")["probability"].to_dict()

    probs = np.array([float(max(lookup.get(name, 0.0), 0.0)) for name in scenario_names], dtype=float)
    total = float(probs.sum())
    if total <= 0:
        return np.full(len(scenario_names), 1.0 / max(len(scenario_names), 1), dtype=float)
    return probs / total


def build_route_stop_indexes(
    feed_path: Path,
    relevant_routes: set[str],
) -> tuple[
    dict[tuple[str, str, str], list[str]],
    dict[tuple[str, str], list[str]],
    dict[str, list[str]],
]:
    trips = read_gtfs_table(
        feed_path=feed_path,
        table_name="trips.txt",
        usecols=["trip_id", "route_id", "direction_id"],
    )
    trips["trip_id"] = trips["trip_id"].astype(str)
    trips["route_id"] = trips["route_id"].astype(str)
    trips["direction_id"] = trips["direction_id"].fillna("-1").astype(str)
    trips = trips[trips["route_id"].isin(relevant_routes)].copy()
    if trips.empty:
        raise ValueError("No trips found in current GTFS for routes present in service gaps")

    stop_times = read_gtfs_table(
        feed_path=feed_path,
        table_name="stop_times.txt",
        usecols=["trip_id", "stop_id", "stop_sequence", "departure_time"],
    )
    stop_times["trip_id"] = stop_times["trip_id"].astype(str)
    stop_times["stop_id"] = stop_times["stop_id"].astype(str)
    stop_times["stop_sequence_num"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")
    stop_times["departure_secs"] = parse_gtfs_seconds(stop_times["departure_time"])

    stop_times = stop_times.merge(
        trips[["trip_id", "route_id", "direction_id"]],
        on="trip_id",
        how="inner",
    )
    if stop_times.empty:
        raise ValueError("No stop_times rows matched the relevant current GTFS routes")

    route_stop_index: dict[str, list[str]] = {
        str(route_id): sorted(group["stop_id"].dropna().astype(str).unique().tolist())
        for route_id, group in stop_times.groupby("route_id", sort=False)
    }

    route_dir_stop_index: dict[tuple[str, str], list[str]] = {
        (str(route_id), str(direction_id)): sorted(group["stop_id"].dropna().astype(str).unique().tolist())
        for (route_id, direction_id), group in stop_times.groupby(["route_id", "direction_id"], sort=False)
    }

    departure_rows = stop_times.dropna(subset=["stop_sequence_num", "departure_secs"])
    if departure_rows.empty:
        return {}, route_dir_stop_index, route_stop_index

    first_idx = departure_rows.groupby("trip_id")["stop_sequence_num"].idxmin()
    first_departure = departure_rows.loc[first_idx, ["trip_id", "departure_secs"]]

    trip_periods = trips.merge(first_departure, on="trip_id", how="left")
    trip_periods["time_period"] = assign_time_periods(trip_periods["departure_secs"])
    trip_periods = trip_periods.dropna(subset=["time_period"]).copy()

    period_stop_times = stop_times[["trip_id", "stop_id"]].merge(
        trip_periods[["trip_id", "route_id", "direction_id", "time_period"]],
        on="trip_id",
        how="inner",
    )

    route_dir_period_index: dict[tuple[str, str, str], list[str]] = {
        (str(route_id), str(direction_id), str(time_period)): sorted(
            group["stop_id"].dropna().astype(str).unique().tolist()
        )
        for (route_id, direction_id, time_period), group in period_stop_times.groupby(
            ["route_id", "direction_id", "time_period"], sort=False
        )
    }

    return route_dir_period_index, route_dir_stop_index, route_stop_index


def resolve_key_stops(
    key: tuple[str, str, str],
    route_dir_period_index: dict[tuple[str, str, str], list[str]],
    route_dir_stop_index: dict[tuple[str, str], list[str]],
    route_stop_index: dict[str, list[str]],
) -> list[str]:
    if key in route_dir_period_index:
        return route_dir_period_index[key]

    route_id, direction_id, _ = key
    route_dir_key = (route_id, direction_id)
    if route_dir_key in route_dir_stop_index:
        return route_dir_stop_index[route_dir_key]

    return route_stop_index.get(route_id, [])


def compute_exposure_by_key(
    unique_keys: list[tuple[str, str, str]],
    tract_ids: list[str],
    tract_xy: np.ndarray,
    valid_tract_mask: np.ndarray,
    stop_xy_lookup: dict[str, tuple[float, float]],
    route_dir_period_index: dict[tuple[str, str, str], list[str]],
    route_dir_stop_index: dict[tuple[str, str], list[str]],
    route_stop_index: dict[str, list[str]],
    exposure_decay_m: float,
    exposure_cutoff_m: float,
    show_progress: bool,
) -> dict[tuple[str, str, str], np.ndarray]:
    if exposure_decay_m <= 0:
        raise ValueError("--exposure-decay-m must be > 0")
    if exposure_cutoff_m <= 0:
        raise ValueError("--exposure-cutoff-m must be > 0")

    zero_vector = np.zeros(len(tract_ids), dtype=float)
    exposure_by_key: dict[tuple[str, str, str], np.ndarray] = {}
    signature_cache: dict[tuple[str, ...], np.ndarray] = {}

    iterator: list[tuple[str, str, str]] | tqdm = unique_keys
    if show_progress:
        iterator = tqdm(unique_keys, desc="Computing route exposure")

    for key in iterator:
        stop_ids = resolve_key_stops(
            key=key,
            route_dir_period_index=route_dir_period_index,
            route_dir_stop_index=route_dir_stop_index,
            route_stop_index=route_stop_index,
        )

        valid_stop_ids = sorted({stop_id for stop_id in stop_ids if stop_id in stop_xy_lookup})
        if not valid_stop_ids:
            exposure_by_key[key] = zero_vector.copy()
            continue

        signature = tuple(valid_stop_ids)
        cached = signature_cache.get(signature)
        if cached is not None:
            exposure_by_key[key] = cached
            continue

        stop_xy = np.array([stop_xy_lookup[stop_id] for stop_id in valid_stop_ids], dtype=float)
        if stop_xy.size == 0:
            exposure = zero_vector.copy()
            signature_cache[signature] = exposure
            exposure_by_key[key] = exposure
            continue

        tree = cKDTree(stop_xy)
        distances = np.full(len(tract_ids), np.inf, dtype=float)

        if valid_tract_mask.any():
            nearest_distances, _ = tree.query(tract_xy[valid_tract_mask], k=1)
            distances[valid_tract_mask] = nearest_distances

        exposure = np.exp(-distances / exposure_decay_m)
        exposure[~np.isfinite(distances)] = 0.0
        exposure[distances > exposure_cutoff_m] = 0.0
        exposure = np.clip(exposure, 0.0, 1.0)

        signature_cache[signature] = exposure
        exposure_by_key[key] = exposure

    return exposure_by_key


def write_marginal_gains(
    candidates_df: pd.DataFrame,
    tract_ids: list[str],
    scenario_names: list[str],
    baseline_matrix: np.ndarray,
    weather_gain_factors: np.ndarray,
    scenario_probabilities: np.ndarray,
    exposure_by_key: dict[tuple[str, str, str], np.ndarray],
    delta_scale: float,
    sparsity_threshold: float,
    output_path: Path,
    show_progress: bool,
) -> tuple[dict[str, float], dict[str, float], dict[str, int], int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    candidate_total_raw: dict[str, float] = {}
    candidate_total_expected: dict[str, float] = {}
    candidate_nonzero_rows: dict[str, int] = {}

    tract_array = np.array(tract_ids, dtype=object)
    total_written_rows = 0

    iterator: object = candidates_df.itertuples(index=False)
    if show_progress:
        iterator = tqdm(iterator, total=len(candidates_df), desc="Writing marginal gains")

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("tract_g,candidate_j,weather_s,delta_score\n")

        for candidate in iterator:
            key = (str(candidate.route_id), str(candidate.direction_id), str(candidate.time_period))
            candidate_id = str(candidate.candidate_id)
            exposure = exposure_by_key.get(key)
            if exposure is None:
                exposure = np.zeros(len(tract_ids), dtype=float)

            candidate_scale = float(delta_scale) * float(candidate.service_gain_scalar)
            total_raw = 0.0
            total_expected = 0.0
            nonzero_rows = 0
            export_chunks: list[pd.DataFrame] = []

            for scenario_idx, scenario_name in enumerate(scenario_names):
                scenario_scale = candidate_scale * float(weather_gain_factors[scenario_idx])
                if scenario_scale <= 0:
                    continue

                delta_values = baseline_matrix[:, scenario_idx] * exposure * scenario_scale
                valid_mask = delta_values > float(sparsity_threshold)
                if not np.any(valid_mask):
                    continue

                scenario_values = delta_values[valid_mask]
                scenario_total = float(scenario_values.sum())

                total_raw += scenario_total
                total_expected += scenario_total * float(scenario_probabilities[scenario_idx])
                nonzero_count = int(valid_mask.sum())
                nonzero_rows += nonzero_count

                export_chunks.append(
                    pd.DataFrame(
                        {
                            "tract_g": tract_array[valid_mask],
                            "candidate_j": candidate_id,
                            "weather_s": scenario_name,
                            "delta_score": scenario_values,
                        }
                    )
                )

            candidate_total_raw[candidate_id] = total_raw
            candidate_total_expected[candidate_id] = total_expected
            candidate_nonzero_rows[candidate_id] = nonzero_rows

            if export_chunks:
                batch = pd.concat(export_chunks, ignore_index=True)
                total_written_rows += len(batch)
                batch.to_csv(fh, index=False, header=False, float_format="%.10f")

    return candidate_total_raw, candidate_total_expected, candidate_nonzero_rows, total_written_rows


def validate_candidate_output(candidates_df: pd.DataFrame) -> None:
    if candidates_df.empty:
        raise ValueError("candidate library is empty")

    if candidates_df["candidate_id"].duplicated().any():
        raise ValueError("candidate_id is not unique")

    if (candidates_df["cost_cj"] <= 0).any():
        raise ValueError("candidate library contains non-positive cost_cj")

    if (candidates_df["increment_trips"] <= 0).any():
        raise ValueError("candidate library contains non-positive increment_trips")

    if (candidates_df["aggregate_delta_expected"] < 0).any():
        raise ValueError("candidate library contains negative aggregate_delta_expected")


def validate_delta_output(delta_output_path: Path) -> None:
    if not delta_output_path.exists():
        raise FileNotFoundError(f"delta output not found: {delta_output_path}")

    sample = pd.read_csv(delta_output_path, nrows=20000)
    required = ["tract_g", "candidate_j", "weather_s", "delta_score"]
    missing = [col for col in required if col not in sample.columns]
    if missing:
        raise ValueError(f"delta output missing required columns: {missing}")

    if sample.empty:
        raise ValueError("delta output is empty")

    sample["delta_score"] = pd.to_numeric(sample["delta_score"], errors="coerce")
    if (sample["delta_score"].isna()).any():
        raise ValueError("delta output sample contains non-numeric delta_score values")
    if (sample["delta_score"] < 0).any():
        raise ValueError("delta output sample contains negative delta_score values")


def main() -> None:
    args = parse_args()
    ensure_data_dirs()

    show_progress = not args.no_progress

    service_panel_path = resolve_project_path(args.service_panel_path)
    baseline_connectivity_path = resolve_project_path(args.baseline_connectivity_path)
    weather_probability_path = resolve_project_path(args.weather_probability_path)
    centroids_path = resolve_project_path(args.centroids_path)
    gtfs_feed_path = resolve_project_path(args.gtfs_feed_path)
    friction_json_path = resolve_project_path(args.friction_json)
    candidate_output_path = resolve_project_path(args.candidate_output)
    delta_output_path = resolve_project_path(args.delta_output)

    if args.min_gap_threshold <= 0:
        raise ValueError("--min-gap-threshold must be > 0")
    if args.delta_scale <= 0:
        raise ValueError("--delta-scale must be > 0")
    if args.sparsity_threshold < 0:
        raise ValueError("--sparsity-threshold must be >= 0")

    panel_df = load_service_panel(service_panel_path)
    current_version_id = infer_current_version_id(panel_df, args.current_version_id)

    gap_df = build_gap_table(
        panel_df=panel_df,
        current_version_id=current_version_id,
        min_gap_threshold=float(args.min_gap_threshold),
    )
    candidates_df = discretize_candidates(
        gap_df=gap_df,
        increment_trip_size=float(args.increment_trip_size),
        min_gap_threshold=float(args.min_gap_threshold),
    )

    tract_ids, scenario_names, baseline_matrix = load_baseline_matrix(baseline_connectivity_path)
    weather_gain_factors = load_weather_gain_factors(friction_json_path, scenario_names)
    scenario_probabilities = load_scenario_probabilities(weather_probability_path, scenario_names)

    tracts_df = load_tract_centroids(
        centroids_path=centroids_path,
        projected_crs=args.projected_crs,
        acs_dir=resolve_project_path(str(ACS_RAW_DIR)),
        max_tracts=0,
    )
    tract_coord_df = (
        tracts_df[["tract_id", "x_m", "y_m"]]
        .drop_duplicates(subset=["tract_id"])
        .set_index("tract_id")
        .reindex(tract_ids)
    )
    tract_xy = tract_coord_df[["x_m", "y_m"]].to_numpy(dtype=float)
    valid_tract_mask = np.isfinite(tract_xy).all(axis=1)

    stops_df = load_stop_coordinates(feed_path=gtfs_feed_path, projected_crs=args.projected_crs)
    stop_xy_lookup = {
        str(row.stop_id): (float(row.x_m), float(row.y_m))
        for row in stops_df.itertuples(index=False)
    }

    unique_keys = (
        candidates_df[["route_id", "direction_id", "time_period"]]
        .drop_duplicates()
        .sort_values(["route_id", "direction_id", "time_period"])
    )
    key_tuples = [
        (str(row.route_id), str(row.direction_id), str(row.time_period))
        for row in unique_keys.itertuples(index=False)
    ]
    relevant_routes = set(unique_keys["route_id"].astype(str).tolist())

    route_dir_period_index, route_dir_stop_index, route_stop_index = build_route_stop_indexes(
        feed_path=gtfs_feed_path,
        relevant_routes=relevant_routes,
    )

    exposure_by_key = compute_exposure_by_key(
        unique_keys=key_tuples,
        tract_ids=tract_ids,
        tract_xy=tract_xy,
        valid_tract_mask=valid_tract_mask,
        stop_xy_lookup=stop_xy_lookup,
        route_dir_period_index=route_dir_period_index,
        route_dir_stop_index=route_dir_stop_index,
        route_stop_index=route_stop_index,
        exposure_decay_m=float(args.exposure_decay_m),
        exposure_cutoff_m=float(args.exposure_cutoff_m),
        show_progress=show_progress,
    )

    coverage_by_key = {
        key: float(np.mean(exposure > 0))
        for key, exposure in exposure_by_key.items()
    }

    (
        candidate_total_raw,
        candidate_total_expected,
        candidate_nonzero_rows,
        total_delta_rows,
    ) = write_marginal_gains(
        candidates_df=candidates_df,
        tract_ids=tract_ids,
        scenario_names=scenario_names,
        baseline_matrix=baseline_matrix,
        weather_gain_factors=weather_gain_factors,
        scenario_probabilities=scenario_probabilities,
        exposure_by_key=exposure_by_key,
        delta_scale=float(args.delta_scale),
        sparsity_threshold=float(args.sparsity_threshold),
        output_path=delta_output_path,
        show_progress=show_progress,
    )

    key_df = candidates_df[["route_id", "direction_id", "time_period"]].astype(str)
    key_as_tuple = list(key_df.itertuples(index=False, name=None))

    candidates_df["aggregate_delta_raw"] = candidates_df["candidate_id"].map(candidate_total_raw).fillna(0.0)
    candidates_df["aggregate_delta_expected"] = (
        candidates_df["candidate_id"].map(candidate_total_expected).fillna(0.0)
    )
    candidates_df["nonzero_delta_rows"] = (
        candidates_df["candidate_id"].map(candidate_nonzero_rows).fillna(0).astype(int)
    )
    candidates_df["coverage_share"] = [
        float(coverage_by_key.get(key, 0.0)) for key in key_as_tuple
    ]

    validate_candidate_output(candidates_df)
    validate_delta_output(delta_output_path)

    candidate_output_path.parent.mkdir(parents=True, exist_ok=True)
    export_columns = [
        "candidate_id",
        "route_id",
        "direction_id",
        "time_period",
        "step_index",
        "increment_trips",
        "cost_cj",
        "q_current",
        "q_max",
        "service_gap_u",
        "avg_trip_runtime_h",
        "service_gain_scalar",
        "headway_before_mins",
        "headway_after_mins",
        "headway_improvement_mins",
        "coverage_share",
        "nonzero_delta_rows",
        "aggregate_delta_raw",
        "aggregate_delta_expected",
    ]
    candidates_df[export_columns].to_csv(candidate_output_path, index=False)

    top_cost = candidates_df.nlargest(10, "cost_cj")[
        ["candidate_id", "route_id", "direction_id", "time_period", "increment_trips", "cost_cj"]
    ]
    top_gain = candidates_df.nlargest(10, "aggregate_delta_expected")[
        [
            "candidate_id",
            "route_id",
            "direction_id",
            "time_period",
            "increment_trips",
            "aggregate_delta_expected",
        ]
    ]

    print("Phase 6 candidate generation complete")
    print(f"  Current version_id: {current_version_id}")
    print(f"  Positive gaps: {len(gap_df)}")
    print(f"  Candidate count: {len(candidates_df)}")
    print(f"  Tracts: {len(tract_ids)}")
    print(f"  Weather scenarios: {len(scenario_names)} -> {', '.join(scenario_names)}")
    print(f"  Marginal delta rows written: {total_delta_rows}")
    print(f"  Candidate output: {candidate_output_path}")
    print(f"  Delta output: {delta_output_path}")
    print("\nTop 10 most expensive candidates:")
    print(top_cost.to_string(index=False))
    print("\nTop 10 highest expected aggregate delta candidates:")
    print(top_gain.to_string(index=False))


if __name__ == "__main__":
    main()