from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import GTFS_CURRENT_DIR, PROCESSED_DATA_DIR
from src.gtfs.crosswalk import (
    build_current_route_index,
    load_routes_table,
    map_routes_to_current,
    read_gtfs_table,
    resolve_project_path,
)


WEEKDAY_NAME_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

WEEKDAY_COLUMNS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

TIME_PERIODS = [
    ("AM Peak", 6 * 3600, 9 * 3600, 180),
    ("Midday", 9 * 3600, 15 * 3600, 360),
    ("PM Peak", 15 * 3600, 18 * 3600, 180),
    ("Evening", 18 * 3600, 24 * 3600, 360),
]

ROUTE_PANEL_COLUMNS = [
    "version_id",
    "route_id",
    "direction_id",
    "time_period",
    "trip_count",
    "avg_headway",
    "service_hours",
]

STOP_PANEL_COLUMNS = ["version_id", "stop_id", "stop_level_service_count"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Construct longitudinal GTFS service panels by route-direction-time_period "
            "and stop-level daily arrival counts."
        )
    )
    parser.add_argument("--manifest-path", default=str(PROCESSED_DATA_DIR / "feeds_manifest.csv"))
    parser.add_argument(
        "--current-feed-path",
        default=str(GTFS_CURRENT_DIR / "google_transit_current"),
        help="Current GTFS folder or zip used as canonical route_id reference",
    )
    parser.add_argument(
        "--route-panel-output",
        default=str(PROCESSED_DATA_DIR / "service_panel_route_period.csv"),
    )
    parser.add_argument(
        "--stop-panel-output",
        default=str(PROCESSED_DATA_DIR / "service_panel_stop_level.csv"),
    )
    parser.add_argument(
        "--crosswalk-output",
        default=str(PROCESSED_DATA_DIR / "route_id_crosswalk.csv"),
        help="Optional route ID crosswalk export path",
    )
    parser.add_argument(
        "--weekday",
        default="average_weekday",
        help=(
            "Service-day mode: one weekday (e.g., monday) or average_weekday "
            "for Mon-Fri averaging"
        ),
    )
    parser.add_argument(
        "--max-versions",
        type=int,
        default=0,
        help="Optional max number of versions to process (0 means all)",
    )
    return parser.parse_args()


def parse_gtfs_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str), format="%Y%m%d", errors="coerce")


def load_calendar_dates_optional(feed_path: Path) -> pd.DataFrame:
    try:
        return read_gtfs_table(
            feed_path,
            "calendar_dates.txt",
            usecols=["service_id", "date", "exception_type"],
        )
    except FileNotFoundError:
        return pd.DataFrame(columns=["service_id", "date", "exception_type"])


def prepare_calendar_df(calendar_df: pd.DataFrame) -> pd.DataFrame:
    prepared = calendar_df.copy()
    prepared["start_date_parsed"] = parse_gtfs_date(prepared["start_date"])
    prepared["end_date_parsed"] = parse_gtfs_date(prepared["end_date"])
    for weekday_col in WEEKDAY_COLUMNS:
        prepared[weekday_col] = prepared[weekday_col].fillna("0").astype(str)
    return prepared


def active_service_ids_for_date(
    service_date: pd.Timestamp,
    calendar_df: pd.DataFrame,
    calendar_dates_df: pd.DataFrame,
    weekday_col: str,
) -> set[str]:
    base_mask = (
        (calendar_df[weekday_col] == "1")
        & (calendar_df["start_date_parsed"] <= service_date)
        & (calendar_df["end_date_parsed"] >= service_date)
    )
    active_ids = set(calendar_df.loc[base_mask, "service_id"].dropna().astype(str))

    if calendar_dates_df.empty:
        return active_ids

    day_token = service_date.strftime("%Y%m%d")
    day_exceptions = calendar_dates_df[calendar_dates_df["date"].astype(str) == day_token]
    if day_exceptions.empty:
        return active_ids

    exception_type = pd.to_numeric(day_exceptions["exception_type"], errors="coerce")
    to_add = set(day_exceptions.loc[exception_type == 1, "service_id"].dropna().astype(str))
    to_remove = set(day_exceptions.loc[exception_type == 2, "service_id"].dropna().astype(str))

    return (active_ids | to_add) - to_remove


def build_candidate_dates(
    calendar_df: pd.DataFrame,
    calendar_dates_df: pd.DataFrame,
    weekday_indices: list[int],
) -> list[pd.Timestamp]:
    start_candidates: list[pd.Timestamp] = []
    end_candidates: list[pd.Timestamp] = []

    if not calendar_df.empty:
        start_series = parse_gtfs_date(calendar_df["start_date"])
        end_series = parse_gtfs_date(calendar_df["end_date"])
        if start_series.notna().any():
            start_candidates.append(start_series.min())
        if end_series.notna().any():
            end_candidates.append(end_series.max())

    if not calendar_dates_df.empty:
        dates = parse_gtfs_date(calendar_dates_df["date"])
        if dates.notna().any():
            start_candidates.append(dates.min())
            end_candidates.append(dates.max())

    if not start_candidates or not end_candidates:
        return []

    start_date = min(start_candidates)
    end_date = max(end_candidates)
    all_days = pd.date_range(start=start_date, end=end_date, freq="D")
    weekday_index_set = set(weekday_indices)
    return [day for day in all_days if day.weekday() in weekday_index_set]


def compute_service_day_weights(
    calendar_df: pd.DataFrame,
    calendar_dates_df: pd.DataFrame,
    weekday_indices: list[int],
) -> tuple[pd.Series, int]:
    candidate_dates = build_candidate_dates(
        calendar_df=calendar_df,
        calendar_dates_df=calendar_dates_df,
        weekday_indices=weekday_indices,
    )
    if not candidate_dates:
        return pd.Series(dtype=float), 0

    service_day_count: dict[str, int] = {}

    for service_date in candidate_dates:
        weekday_col = WEEKDAY_COLUMNS[service_date.weekday()]
        active_ids = active_service_ids_for_date(
            service_date=service_date,
            calendar_df=calendar_df,
            calendar_dates_df=calendar_dates_df,
            weekday_col=weekday_col,
        )
        for service_id in active_ids:
            service_day_count[service_id] = service_day_count.get(service_id, 0) + 1

    return pd.Series(service_day_count, dtype=float), len(candidate_dates)


def build_trip_profile(stop_times_df: pd.DataFrame) -> pd.DataFrame:
    stop_times = stop_times_df.copy()
    stop_times["stop_sequence_num"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")
    stop_times["departure_secs"] = pd.to_timedelta(stop_times["departure_time"], errors="coerce").dt.total_seconds()
    stop_times["arrival_secs"] = pd.to_timedelta(stop_times["arrival_time"], errors="coerce").dt.total_seconds()

    stop_times = stop_times.dropna(
        subset=["trip_id", "stop_sequence_num", "departure_secs", "arrival_secs"]
    )
    if stop_times.empty:
        return pd.DataFrame(columns=["trip_id", "trip_departure_secs", "trip_duration_hours"])

    idx_first = stop_times.groupby("trip_id")["stop_sequence_num"].idxmin()
    idx_last = stop_times.groupby("trip_id")["stop_sequence_num"].idxmax()

    first_stop = stop_times.loc[idx_first, ["trip_id", "departure_secs"]].rename(
        columns={"departure_secs": "trip_departure_secs"}
    )
    last_stop = stop_times.loc[idx_last, ["trip_id", "arrival_secs"]].rename(
        columns={"arrival_secs": "trip_arrival_secs"}
    )

    profile = first_stop.merge(last_stop, on="trip_id", how="inner")
    profile["trip_duration_hours"] = (
        (profile["trip_arrival_secs"] - profile["trip_departure_secs"]).clip(lower=0) / 3600.0
    )
    return profile[["trip_id", "trip_departure_secs", "trip_duration_hours"]]


def assign_time_periods(trips_df: pd.DataFrame) -> pd.DataFrame:
    enriched = trips_df.copy()
    departure = enriched["trip_departure_secs"]

    conditions = [
        (departure >= start) & (departure < end)
        for _, start, end, _ in TIME_PERIODS
    ]
    labels = [name for name, _, _, _ in TIME_PERIODS]
    enriched["time_period"] = np.select(conditions, labels, default="")
    enriched.loc[enriched["time_period"] == "", "time_period"] = pd.NA
    return enriched


def build_route_period_panel(
    version_id: str,
    trips_df: pd.DataFrame,
    stop_times_df: pd.DataFrame,
    canonical_route_map: dict[str, str],
    service_day_weights: pd.Series,
    averaging_day_count: int,
) -> pd.DataFrame:
    if averaging_day_count <= 0 or service_day_weights.empty:
        return pd.DataFrame(columns=ROUTE_PANEL_COLUMNS)

    active_trips = trips_df.copy()
    active_trips["service_id"] = active_trips["service_id"].astype(str)
    active_trips["service_weight"] = active_trips["service_id"].map(service_day_weights).fillna(0.0)
    active_trips = active_trips[active_trips["service_weight"] > 0].copy()
    if active_trips.empty:
        return pd.DataFrame(columns=ROUTE_PANEL_COLUMNS)

    active_trips["trip_id"] = active_trips["trip_id"].astype(str)
    active_trips["route_id"] = active_trips["route_id"].astype(str)
    active_trips["route_id"] = active_trips["route_id"].map(canonical_route_map).fillna(active_trips["route_id"])
    active_trips["direction_id"] = active_trips["direction_id"].fillna("-1").astype(str)

    profile = build_trip_profile(stop_times_df)
    merged = active_trips.merge(profile, on="trip_id", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=ROUTE_PANEL_COLUMNS)

    merged = assign_time_periods(merged)
    merged = merged.dropna(subset=["time_period"])
    if merged.empty:
        return pd.DataFrame(columns=ROUTE_PANEL_COLUMNS)

    merged["weighted_trip_count"] = merged["service_weight"]
    merged["weighted_service_hours"] = merged["trip_duration_hours"] * merged["service_weight"]

    panel = (
        merged.groupby(["route_id", "direction_id", "time_period"], as_index=False)
        .agg(
            weighted_trip_count=("weighted_trip_count", "sum"),
            weighted_service_hours=("weighted_service_hours", "sum"),
        )
        .sort_values(["route_id", "direction_id", "time_period"])
    )

    panel["trip_count"] = panel["weighted_trip_count"] / float(averaging_day_count)
    panel["service_hours"] = panel["weighted_service_hours"] / float(averaging_day_count)

    period_minutes = {name: duration for name, _, _, duration in TIME_PERIODS}
    panel["avg_headway"] = np.where(
        panel["trip_count"] > 0,
        panel["time_period"].map(period_minutes) / panel["trip_count"],
        np.nan,
    )
    panel.insert(0, "version_id", version_id)

    return panel[ROUTE_PANEL_COLUMNS]


def build_stop_level_panel(
    version_id: str,
    trips_df: pd.DataFrame,
    stop_times_df: pd.DataFrame,
    service_day_weights: pd.Series,
    averaging_day_count: int,
) -> pd.DataFrame:
    if averaging_day_count <= 0 or service_day_weights.empty:
        return pd.DataFrame(columns=STOP_PANEL_COLUMNS)

    active_trips = trips_df.copy()
    active_trips["service_id"] = active_trips["service_id"].astype(str)
    active_trips["service_weight"] = active_trips["service_id"].map(service_day_weights).fillna(0.0)
    active_trips = active_trips[active_trips["service_weight"] > 0].copy()
    if active_trips.empty:
        return pd.DataFrame(columns=STOP_PANEL_COLUMNS)

    active_trip_weights = active_trips[["trip_id", "service_weight"]].dropna().copy()
    active_trip_weights["trip_id"] = active_trip_weights["trip_id"].astype(str)
    active_trip_weights = active_trip_weights.drop_duplicates(subset=["trip_id"])

    stop_times = stop_times_df.copy()
    stop_times["trip_id"] = stop_times["trip_id"].astype(str)

    active_stop_times = stop_times.merge(active_trip_weights, on="trip_id", how="inner")
    if active_stop_times.empty:
        return pd.DataFrame(columns=STOP_PANEL_COLUMNS)

    active_stop_times["weighted_arrivals"] = active_stop_times["service_weight"]

    stop_panel = (
        active_stop_times.groupby("stop_id", as_index=False)
        .agg(stop_level_service_count=("weighted_arrivals", "sum"))
        .sort_values("stop_id")
    )
    stop_panel["stop_level_service_count"] = (
        stop_panel["stop_level_service_count"] / float(averaging_day_count)
    )
    stop_panel.insert(0, "version_id", version_id)

    return stop_panel[STOP_PANEL_COLUMNS]


def load_feed_tables(feed_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trips_df = read_gtfs_table(
        feed_path,
        "trips.txt",
        usecols=["trip_id", "route_id", "service_id", "direction_id"],
    )
    stop_times_df = read_gtfs_table(
        feed_path,
        "stop_times.txt",
        usecols=["trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"],
    )
    calendar_df = read_gtfs_table(
        feed_path,
        "calendar.txt",
        usecols=["service_id", *WEEKDAY_COLUMNS, "start_date", "end_date"],
    )
    calendar_dates_df = load_calendar_dates_optional(feed_path)
    routes_df = load_routes_table(feed_path)

    return trips_df, stop_times_df, calendar_df, calendar_dates_df, routes_df


def parse_weekday_selection(raw_weekday: str) -> tuple[list[int], str]:
    normalized = raw_weekday.strip().lower()
    if normalized in {"average_weekday", "avg_weekday", "weekday", "weekdays"}:
        return [0, 1, 2, 3, 4], "average_weekday"

    if normalized not in WEEKDAY_NAME_TO_INDEX:
        valid = ", ".join([*WEEKDAY_NAME_TO_INDEX, "average_weekday"])
        raise ValueError(f"Invalid weekday '{raw_weekday}'. Expected one of: {valid}")
    return [WEEKDAY_NAME_TO_INDEX[normalized]], normalized


def main() -> None:
    args = parse_args()

    manifest_path = resolve_project_path(args.manifest_path)
    current_feed_path = resolve_project_path(args.current_feed_path)
    route_panel_output = resolve_project_path(args.route_panel_output)
    stop_panel_output = resolve_project_path(args.stop_panel_output)
    crosswalk_output = resolve_project_path(args.crosswalk_output)

    weekday_indices, weekday_mode = parse_weekday_selection(args.weekday)

    manifest_df = pd.read_csv(manifest_path, dtype=str)
    manifest_df = manifest_df[manifest_df["file_path"].notna() & (manifest_df["file_path"].str.strip() != "")]

    if args.max_versions > 0:
        manifest_df = manifest_df.head(args.max_versions)

    current_short_name_index, current_route_ids = build_current_route_index(current_feed_path)

    route_panels: list[pd.DataFrame] = []
    stop_panels: list[pd.DataFrame] = []
    crosswalk_frames: list[pd.DataFrame] = []

    for _, row in manifest_df.iterrows():
        version_id = str(row["version_id"])
        feed_path = resolve_project_path(str(row["file_path"]))
        if not feed_path.exists():
            print(f"Skipping version {version_id}: missing file {feed_path}")
            continue

        print(f"Processing version {version_id}: {feed_path.name}")

        trips_df, stop_times_df, calendar_df, calendar_dates_df, routes_df = load_feed_tables(feed_path)

        prepared_calendar_df = prepare_calendar_df(calendar_df)

        service_day_weights, averaging_day_count = compute_service_day_weights(
            calendar_df=prepared_calendar_df,
            calendar_dates_df=calendar_dates_df,
            weekday_indices=weekday_indices,
        )

        if averaging_day_count <= 0 or service_day_weights.empty:
            print(f"  No active service_ids found for mode '{weekday_mode}'; skipping version {version_id}")
            continue

        print(
            "  Averaging mode: "
            f"{weekday_mode}; sampled days={averaging_day_count}; "
            f"active service_ids={service_day_weights.index.nunique()}"
        )

        mapped_routes = map_routes_to_current(routes_df, current_short_name_index, current_route_ids)
        mapped_routes.insert(0, "version_id", version_id)
        crosswalk_frames.append(mapped_routes)

        canonical_route_map = dict(
            zip(mapped_routes["historic_route_id"].astype(str), mapped_routes["canonical_route_id"].astype(str))
        )

        route_panel = build_route_period_panel(
            version_id=version_id,
            trips_df=trips_df,
            stop_times_df=stop_times_df,
            canonical_route_map=canonical_route_map,
            service_day_weights=service_day_weights,
            averaging_day_count=averaging_day_count,
        )

        stop_panel = build_stop_level_panel(
            version_id=version_id,
            trips_df=trips_df,
            stop_times_df=stop_times_df,
            service_day_weights=service_day_weights,
            averaging_day_count=averaging_day_count,
        )

        if not route_panel.empty:
            route_panels.append(route_panel)
        if not stop_panel.empty:
            stop_panels.append(stop_panel)

    route_panel_output.parent.mkdir(parents=True, exist_ok=True)
    stop_panel_output.parent.mkdir(parents=True, exist_ok=True)
    crosswalk_output.parent.mkdir(parents=True, exist_ok=True)

    final_route_panel = (
        pd.concat(route_panels, ignore_index=True)
        if route_panels
        else pd.DataFrame(columns=ROUTE_PANEL_COLUMNS)
    )
    final_stop_panel = (
        pd.concat(stop_panels, ignore_index=True)
        if stop_panels
        else pd.DataFrame(columns=STOP_PANEL_COLUMNS)
    )
    final_crosswalk = (
        pd.concat(crosswalk_frames, ignore_index=True)
        if crosswalk_frames
        else pd.DataFrame(
            columns=[
                "version_id",
                "historic_route_id",
                "route_short_name",
                "canonical_route_id",
                "mapping_confidence",
            ]
        )
    )

    if not final_route_panel.empty:
        final_route_panel = final_route_panel.sort_values(
            by=["version_id", "route_id", "direction_id", "time_period"]
        )
    if not final_stop_panel.empty:
        final_stop_panel = final_stop_panel.sort_values(by=["version_id", "stop_id"])

    final_route_panel.to_csv(route_panel_output, index=False)
    final_stop_panel.to_csv(stop_panel_output, index=False)
    final_crosswalk.to_csv(crosswalk_output, index=False)

    print(f"Route-period panel rows: {len(final_route_panel)}")
    print(f"Stop-level panel rows: {len(final_stop_panel)}")
    print(f"Crosswalk rows: {len(final_crosswalk)}")
    print(f"Route-period output: {route_panel_output}")
    print(f"Stop-level output: {stop_panel_output}")
    print(f"Crosswalk output: {crosswalk_output}")


if __name__ == "__main__":
    main()
