from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import NOAA_RAW_DIR, PROCESSED_DATA_DIR, PROJECT_ROOT, ensure_data_dirs

WEATHER_STATES = [
    "Dry / Normal",
    "Light Rain",
    "Heavy Rain",
    "Cold/Windy",
    "Heat",
]

# Deterministic precedence used when multiple conditions could match a day.
RULE_PRECEDENCE = [
    "Heavy Rain",
    "Light Rain",
    "Cold/Windy",
    "Heat",
    "Dry / Normal",
]


@dataclass(frozen=True)
class WeatherThresholds:
    heavy_rain_inches: float = 0.2
    cold_tmax_f: float = 40.0
    heat_tmax_f: float = 85.0
    windy_awnd_mph: float = 12.0


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify Seattle daily weather into discrete states, compute monthly/seasonal "
            "probabilities, and export transit friction parameters."
        )
    )
    parser.add_argument(
        "--input-csv",
        default=str(NOAA_RAW_DIR / "seattle_daily_weather.csv"),
        help="Input NOAA daily weather CSV",
    )
    parser.add_argument(
        "--output-csv",
        default=str(PROCESSED_DATA_DIR / "weather_probabilities.csv"),
        help="Output weather probability table",
    )
    parser.add_argument(
        "--friction-json",
        default=str(PROJECT_ROOT / "src" / "weather" / "friction_params.json"),
        help="Output friction parameter JSON path",
    )
    parser.add_argument(
        "--classified-days-csv",
        default=str(PROCESSED_DATA_DIR / "weather_daily_states.csv"),
        help="Output per-day classified weather states for auditability",
    )
    parser.add_argument(
        "--metadata-json",
        default=str(PROCESSED_DATA_DIR / "weather_scenario_metadata.json"),
        help="Output metadata JSON containing thresholds, logs, and summary stats",
    )
    parser.add_argument("--heavy-rain-inches", type=float, default=0.2)
    parser.add_argument("--cold-tmax-f", type=float, default=40.0)
    parser.add_argument("--heat-tmax-f", type=float, default=85.0)
    parser.add_argument("--windy-awnd-mph", type=float, default=12.0)
    parser.add_argument(
        "--probability-decimals",
        type=int,
        default=6,
        help="Decimal places for output probabilities; group sums are conserved after rounding",
    )
    return parser.parse_args()


def normalize_weather_fields(input_csv: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    frame = pd.read_csv(input_csv)
    expected = ["date", "PRCP", "TMAX", "TMIN", "AWND"]
    missing = [col for col in expected if col not in frame.columns]
    if missing:
        raise ValueError(f"Input weather CSV missing required columns: {missing}")

    frame = frame[expected].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

    dropped_invalid_date = int(frame["date"].isna().sum())
    frame = frame.dropna(subset=["date"]).copy()

    for column in ["PRCP", "TMAX", "TMIN", "AWND"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    prcp_imputed_zero = int(frame["PRCP"].isna().sum())
    frame["PRCP"] = frame["PRCP"].fillna(0.0)

    tmax_from_tmin_mask = frame["TMAX"].isna() & frame["TMIN"].notna()
    tmin_from_tmax_mask = frame["TMIN"].isna() & frame["TMAX"].notna()
    tmax_imputed_from_tmin = int(tmax_from_tmin_mask.sum())
    tmin_imputed_from_tmax = int(tmin_from_tmax_mask.sum())
    frame.loc[tmax_from_tmin_mask, "TMAX"] = frame.loc[tmax_from_tmin_mask, "TMIN"]
    frame.loc[tmin_from_tmax_mask, "TMIN"] = frame.loc[tmin_from_tmax_mask, "TMAX"]

    drop_missing_temp_mask = frame["TMAX"].isna() | frame["TMIN"].isna()
    dropped_missing_temperature = int(drop_missing_temp_mask.sum())
    frame = frame.loc[~drop_missing_temp_mask].copy()

    awnd_imputed_median = int(frame["AWND"].isna().sum())
    awnd_median = frame["AWND"].median(skipna=True)
    if pd.isna(awnd_median):
        awnd_median = 0.0
    frame["AWND"] = frame["AWND"].fillna(float(awnd_median))

    # NOAA values are metric in this pipeline: mm, C, and m/s.
    frame["prcp_in"] = frame["PRCP"] / 25.4
    frame["tmax_f"] = frame["TMAX"] * 9.0 / 5.0 + 32.0
    frame["tmin_f"] = frame["TMIN"] * 9.0 / 5.0 + 32.0
    frame["awnd_mph"] = frame["AWND"] * 2.2369362920544

    frame["month_num"] = frame["date"].dt.month
    frame["month_key"] = frame["date"].dt.strftime("month_%m")
    frame["season"] = frame["month_num"].map(
        {
            12: "Winter",
            1: "Winter",
            2: "Winter",
            3: "Spring",
            4: "Spring",
            5: "Spring",
            6: "Summer",
            7: "Summer",
            8: "Summer",
            9: "Fall",
            10: "Fall",
            11: "Fall",
        }
    )

    log = {
        "dropped_invalid_date": dropped_invalid_date,
        "prcp_imputed_zero": prcp_imputed_zero,
        "tmax_imputed_from_tmin": tmax_imputed_from_tmin,
        "tmin_imputed_from_tmax": tmin_imputed_from_tmax,
        "dropped_missing_temperature": dropped_missing_temperature,
        "awnd_imputed_median": awnd_imputed_median,
    }
    return frame, log


def classify_weather_states(frame: pd.DataFrame, thresholds: WeatherThresholds) -> pd.DataFrame:
    state = pd.Series("Dry / Normal", index=frame.index, dtype="object")

    heavy_rain = frame["prcp_in"] >= thresholds.heavy_rain_inches
    light_rain = (frame["prcp_in"] > 0) & (~heavy_rain)
    cold_windy = (
        ((frame["tmax_f"] < thresholds.cold_tmax_f) | (frame["awnd_mph"] > thresholds.windy_awnd_mph))
        & (~heavy_rain)
        & (~light_rain)
    )
    heat = (
        (frame["tmax_f"] > thresholds.heat_tmax_f)
        & (~heavy_rain)
        & (~light_rain)
        & (~cold_windy)
    )

    state.loc[heavy_rain] = "Heavy Rain"
    state.loc[light_rain] = "Light Rain"
    state.loc[cold_windy] = "Cold/Windy"
    state.loc[heat] = "Heat"

    frame = frame.copy()
    frame["weather_state"] = state

    if frame["weather_state"].isna().any():
        raise ValueError("Weather state classification failed: some rows were unclassified")

    return frame


def summarize_probabilities(frame: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_value, group_df in frame.groupby(group_col, sort=False):
        probs = group_df["weather_state"].value_counts(normalize=True)
        for state in WEATHER_STATES:
            rows.append(
                {
                    "season_or_month": str(group_value),
                    "weather_state": state,
                    "probability": float(probs.get(state, 0.0)),
                }
            )
    return pd.DataFrame(rows)


def round_group_probabilities(group: pd.DataFrame, decimals: int) -> pd.DataFrame:
    group = group.copy()
    rounded = group["probability"].round(decimals)

    if len(rounded) > 0:
        residual = round(1.0 - float(rounded.sum()), decimals)
        # Adjust last state in deterministic order to preserve exactly-1 sums.
        rounded.iloc[-1] = round(float(rounded.iloc[-1]) + residual, decimals)

    if (rounded < 0).any() or (rounded > 1).any():
        states = group["weather_state"].tolist()
        raise ValueError(
            "Rounded probabilities fell outside [0, 1] for group "
            f"{group['season_or_month'].iloc[0]} with states {states}"
        )

    group["probability"] = rounded
    return group


def validate_probability_sums(probabilities: pd.DataFrame, tolerance: float = 1e-9) -> None:
    grouped = probabilities.groupby("season_or_month", dropna=False)["probability"].sum()
    bad = grouped[(grouped - 1.0).abs() > tolerance]
    if not bad.empty:
        details = ", ".join(f"{idx}={val:.12f}" for idx, val in bad.items())
        raise ValueError(f"Probability sums are invalid for groups: {details}")


def build_probability_table(frame: pd.DataFrame, probability_decimals: int) -> pd.DataFrame:
    monthly = summarize_probabilities(frame, "month_key")
    seasonal = summarize_probabilities(frame, "season")

    annual_frame = frame.assign(season_or_month="Annual")
    annual = summarize_probabilities(annual_frame, "season_or_month")

    probabilities = pd.concat([monthly, seasonal, annual], ignore_index=True)

    month_order = [f"month_{i:02d}" for i in range(1, 13)]
    group_order = {name: idx for idx, name in enumerate(month_order + ["Winter", "Spring", "Summer", "Fall", "Annual"])}
    state_order = {name: idx for idx, name in enumerate(WEATHER_STATES)}

    probabilities["_group_order"] = probabilities["season_or_month"].map(group_order).fillna(10_000)
    probabilities["_state_order"] = probabilities["weather_state"].map(state_order).fillna(10_000)

    probabilities = probabilities.sort_values(["_group_order", "_state_order"]).drop(
        columns=["_group_order", "_state_order"]
    )

    rounded_groups: list[pd.DataFrame] = []
    for group_value, group_df in probabilities.groupby("season_or_month", sort=False, dropna=False):
        rounded_group = round_group_probabilities(group_df, decimals=probability_decimals)
        if "season_or_month" not in rounded_group.columns:
            rounded_group = rounded_group.copy()
            rounded_group["season_or_month"] = str(group_value)
        rounded_groups.append(rounded_group)

    probabilities = pd.concat(rounded_groups, ignore_index=True)

    tolerance = 10 ** (-(probability_decimals + 1))
    validate_probability_sums(probabilities, tolerance=tolerance)

    return probabilities


def build_metadata(
    weather_df: pd.DataFrame,
    normalization_log: dict[str, int],
    thresholds: WeatherThresholds,
) -> dict[str, object]:
    date_min = weather_df["date"].min()
    date_max = weather_df["date"].max()

    return {
        "rows_after_normalization": int(len(weather_df)),
        "date_min": date_min.strftime("%Y-%m-%d") if pd.notna(date_min) else None,
        "date_max": date_max.strftime("%Y-%m-%d") if pd.notna(date_max) else None,
        "thresholds": {
            "heavy_rain_inches": thresholds.heavy_rain_inches,
            "cold_tmax_f": thresholds.cold_tmax_f,
            "heat_tmax_f": thresholds.heat_tmax_f,
            "windy_awnd_mph": thresholds.windy_awnd_mph,
        },
        "rule_precedence": RULE_PRECEDENCE,
        "normalization_log": normalization_log,
        "state_counts": {
            state: int(count)
            for state, count in weather_df["weather_state"].value_counts().reindex(WEATHER_STATES, fill_value=0).items()
        },
    }


def default_friction_params() -> dict[str, dict[str, float | int]]:
    return {
        "Dry / Normal": {
            "walk_speed_multiplier": 1.0,
            "max_walk_distance_m": 800,
            "transfer_penalty_mins": 5,
        },
        "Light Rain": {
            "walk_speed_multiplier": 0.9,
            "max_walk_distance_m": 700,
            "transfer_penalty_mins": 6,
        },
        "Heavy Rain": {
            "walk_speed_multiplier": 0.8,
            "max_walk_distance_m": 400,
            "transfer_penalty_mins": 10,
        },
        "Cold/Windy": {
            "walk_speed_multiplier": 0.85,
            "max_walk_distance_m": 500,
            "transfer_penalty_mins": 9,
        },
        "Heat": {
            "walk_speed_multiplier": 0.7,
            "max_walk_distance_m": 600,
            "transfer_penalty_mins": 8,
        },
    }


def main() -> None:
    args = parse_args()
    ensure_data_dirs()

    input_csv = resolve_project_path(args.input_csv)
    output_csv = resolve_project_path(args.output_csv)
    friction_json = resolve_project_path(args.friction_json)
    classified_days_csv = resolve_project_path(args.classified_days_csv)
    metadata_json = resolve_project_path(args.metadata_json)

    if args.probability_decimals < 0:
        raise ValueError("--probability-decimals must be >= 0")

    thresholds = WeatherThresholds(
        heavy_rain_inches=args.heavy_rain_inches,
        cold_tmax_f=args.cold_tmax_f,
        heat_tmax_f=args.heat_tmax_f,
        windy_awnd_mph=args.windy_awnd_mph,
    )

    weather_df, normalization_log = normalize_weather_fields(input_csv)
    weather_df = classify_weather_states(weather_df, thresholds)

    state_counts = weather_df["weather_state"].value_counts().reindex(WEATHER_STATES, fill_value=0)
    if int(state_counts.sum()) != len(weather_df):
        raise ValueError("State count validation failed: total classified days does not match input rows")

    probabilities = build_probability_table(weather_df, probability_decimals=args.probability_decimals)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    probabilities.to_csv(output_csv, index=False)

    classified_days = weather_df[
        ["date", "weather_state", "month_key", "season", "prcp_in", "tmax_f", "tmin_f", "awnd_mph"]
    ].copy()
    classified_days["date"] = classified_days["date"].dt.strftime("%Y-%m-%d")
    classified_days_csv.parent.mkdir(parents=True, exist_ok=True)
    classified_days.to_csv(classified_days_csv, index=False)

    friction = default_friction_params()
    missing_states = [state for state in WEATHER_STATES if state not in friction]
    if missing_states:
        raise ValueError(f"Friction config missing weather states: {missing_states}")

    required_keys = {"walk_speed_multiplier", "max_walk_distance_m", "transfer_penalty_mins"}
    for state, cfg in friction.items():
        cfg_keys = set(cfg.keys())
        if cfg_keys != required_keys:
            raise ValueError(
                f"Friction config for {state} must contain exactly keys {sorted(required_keys)}; got {sorted(cfg_keys)}"
            )

    friction_json.parent.mkdir(parents=True, exist_ok=True)
    with friction_json.open("w", encoding="utf-8") as fh:
        json.dump(friction, fh, indent=2)

    metadata = build_metadata(weather_df, normalization_log, thresholds)
    metadata_json.parent.mkdir(parents=True, exist_ok=True)
    with metadata_json.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    print("Normalization log:")
    for key, value in normalization_log.items():
        print(f"  {key}: {value}")

    print("\nClassified state counts:")
    for state, count in state_counts.items():
        print(f"  {state}: {int(count)}")

    print(f"\nSaved probabilities: {output_csv}")
    print(f"Saved classified daily states: {classified_days_csv}")
    print(f"Saved friction params: {friction_json}")
    print(f"Saved weather metadata: {metadata_json}")


if __name__ == "__main__":
    main()
