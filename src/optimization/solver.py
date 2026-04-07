from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from mip import BINARY, CBC, CONTINUOUS, GUROBI, MAXIMIZE, Model, OptimizationStatus, xsum

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import ACS_RAW_DIR, PROCESSED_DATA_DIR, PROJECT_ROOT, ensure_data_dirs


CANDIDATE_REQUIRED_COLUMNS = ["candidate_id", "cost_cj"]
DELTA_REQUIRED_COLUMNS = ["tract_g", "candidate_j", "weather_s", "delta_score"]
BASELINE_REQUIRED_COLUMNS = ["tract_id", "weather_scenario", "connectivity_score"]
WEATHER_REQUIRED_COLUMNS = ["season_or_month", "weather_state", "probability"]


@dataclass(frozen=True)
class OptimizationInputs:
    candidates: list[str]
    scenarios: list[str]
    costs: dict[str, float]
    scenario_probabilities: dict[str, float]
    vulnerable_tracts: set[str]
    non_vulnerable_tracts: set[str]
    alpha_weights: dict[str, float]
    efficiency_coeff: dict[str, float]
    vulnerable_expected_coeff: dict[str, float]
    non_vulnerable_expected_coeff: dict[str, float]
    vulnerable_scenario_coeff: dict[str, dict[str, float]]
    baseline_vulnerable_scenario_avg: dict[str, float]
    baseline_non_vulnerable_scenario_avg: dict[str, float]
    baseline_vulnerable_expected: float
    baseline_non_vulnerable_expected: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 7 optimization solver for efficiency-fairness and robust max-min restoration models"
        )
    )
    parser.add_argument(
        "--candidate-library-path",
        default=str(PROCESSED_DATA_DIR / "candidate_library.csv"),
        help="Path to candidate_library.csv from Phase 6",
    )
    parser.add_argument(
        "--delta-path",
        default=str(PROCESSED_DATA_DIR / "marginal_gains_delta.csv"),
        help="Path to marginal_gains_delta.csv from Phase 6",
    )
    parser.add_argument(
        "--baseline-path",
        default=str(PROCESSED_DATA_DIR / "baseline_connectivity_scores.csv"),
        help="Path to baseline_connectivity_scores.csv from Phase 5",
    )
    parser.add_argument(
        "--weather-probability-path",
        default=str(PROCESSED_DATA_DIR / "weather_probabilities.csv"),
        help="Path to weather_probabilities.csv from Phase 4",
    )
    parser.add_argument(
        "--demographics-path",
        default=str(PROCESSED_DATA_DIR / "acs_demographics_centroids.geojson"),
        help="Path to acs_demographics_centroids.geojson from Phase 3",
    )
    parser.add_argument(
        "--acs-population-path",
        default="",
        help=(
            "Optional path to ACS tract CSV with B01001_001E for alpha_g weights. "
            "If omitted, latest raw ACS tract file is auto-detected."
        ),
    )
    parser.add_argument(
        "--probability-profile",
        default="Annual",
        help=(
            "Scenario probability group from weather_probabilities.csv "
            "(e.g., Annual, Winter, Summer, month_01)."
        ),
    )
    parser.add_argument(
        "--budgets",
        default="500,1000,2000,5000",
        help="Comma-separated budget grid, in service-hours cost units",
    )
    parser.add_argument(
        "--lambdas",
        default="0,0.25,0.5,1,2,5",
        help="Comma-separated lambda fairness penalties for model 1",
    )
    parser.add_argument(
        "--solver",
        choices=["auto", "cbc", "gurobi"],
        default="auto",
        help="MIP backend choice",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=120.0,
        help="Time limit for each optimization run",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="Number of solver threads (0 uses solver default)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic seed when supported by the backend",
    )
    parser.add_argument(
        "--efficiency-output",
        default=str(PROCESSED_DATA_DIR / "optimization_results_efficiency.csv"),
        help="Output CSV path for model 1 sweep",
    )
    parser.add_argument(
        "--robust-output",
        default=str(PROCESSED_DATA_DIR / "optimization_results_robust.csv"),
        help="Output CSV path for model 2 sweep",
    )
    return parser.parse_args()


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def parse_float_grid(raw_values: str, label: str) -> list[float]:
    tokens = [token.strip() for token in str(raw_values).split(",") if token.strip()]
    if not tokens:
        raise ValueError(f"{label} grid cannot be empty")
    values = []
    for token in tokens:
        values.append(float(token))
    return values


def normalize_tract_id(value: object) -> str:
    token = str(value).strip()
    if token.endswith(".0"):
        token = token[:-2]
    token = re.sub(r"\s+", "", token)
    if token.isdigit() and len(token) < 11:
        token = token.zfill(11)
    return token


def read_geojson_properties(geojson_path: Path) -> pd.DataFrame:
    with geojson_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    features = payload.get("features", [])
    if not isinstance(features, list) or not features:
        raise ValueError(f"No features found in {geojson_path}")

    rows = []
    for feature in features:
        properties = feature.get("properties", {})
        if isinstance(properties, dict):
            rows.append(properties)

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"No property rows found in {geojson_path}")
    return frame


def detect_latest_acs_tract_file(acs_dir: Path) -> Path | None:
    pattern = re.compile(r"^acs5_(\d{4})_state\d{2}_county\d{3}_tracts\.csv$")
    candidates: list[tuple[int, Path]] = []
    for file_path in acs_dir.glob("acs5_*_tracts.csv"):
        match = pattern.match(file_path.name)
        if match:
            candidates.append((int(match.group(1)), file_path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def load_population_map(
    demographics_path: Path,
    acs_population_path: Path | None,
    tract_ids: set[str],
) -> tuple[dict[str, float], str]:
    demographics_df = read_geojson_properties(demographics_path)

    geoid_column = "geoid" if "geoid" in demographics_df.columns else None
    if geoid_column is None:
        raise ValueError("Demographics GeoJSON is missing `geoid`")

    demographics_df["tract_id"] = demographics_df[geoid_column].map(normalize_tract_id)

    candidate_population_columns = [
        "population",
        "total_population",
        "B01001_001E",
        "pop_total",
    ]

    for column in candidate_population_columns:
        if column in demographics_df.columns:
            population_series = pd.to_numeric(demographics_df[column], errors="coerce")
            map_df = pd.DataFrame(
                {
                    "tract_id": demographics_df["tract_id"],
                    "population": population_series,
                }
            ).dropna(subset=["tract_id"])
            return (
                map_df.dropna(subset=["population"]).set_index("tract_id")["population"].to_dict(),
                f"demographics:{column}",
            )

    if acs_population_path is not None and acs_population_path.exists():
        acs_df = pd.read_csv(acs_population_path, dtype=str)
        required = ["state", "county", "tract", "B01001_001E"]
        missing = [column for column in required if column not in acs_df.columns]
        if missing:
            raise ValueError(
                f"ACS population file {acs_population_path} missing columns {missing}"
            )

        acs_df["state"] = acs_df["state"].astype(str).str.zfill(2)
        acs_df["county"] = acs_df["county"].astype(str).str.zfill(3)
        acs_df["tract"] = acs_df["tract"].astype(str).str.zfill(6)
        acs_df["tract_id"] = acs_df["state"] + acs_df["county"] + acs_df["tract"]
        acs_df["population"] = pd.to_numeric(acs_df["B01001_001E"], errors="coerce")

        population_map = (
            acs_df[["tract_id", "population"]]
            .dropna(subset=["tract_id", "population"])
            .drop_duplicates(subset=["tract_id"])
            .set_index("tract_id")["population"]
            .to_dict()
        )
        return population_map, f"acs:{acs_population_path.name}"

    return {}, "uniform_fallback"


def load_vulnerability_map(demographics_path: Path) -> dict[str, bool]:
    properties_df = read_geojson_properties(demographics_path)

    if "geoid" not in properties_df.columns:
        raise ValueError("Demographics GeoJSON is missing `geoid`")
    if "vulnerable" not in properties_df.columns:
        raise ValueError("Demographics GeoJSON is missing `vulnerable`")

    properties_df["tract_id"] = properties_df["geoid"].map(normalize_tract_id)
    vulnerability_map = (
        properties_df[["tract_id", "vulnerable"]]
        .dropna(subset=["tract_id"])
        .drop_duplicates(subset=["tract_id"])
        .set_index("tract_id")["vulnerable"]
        .astype(bool)
        .to_dict()
    )
    return vulnerability_map


def load_probability_profile(
    weather_probability_path: Path,
    probability_profile: str,
    scenarios: set[str],
) -> dict[str, float]:
    weather_df = pd.read_csv(weather_probability_path)
    missing = [column for column in WEATHER_REQUIRED_COLUMNS if column not in weather_df.columns]
    if missing:
        raise ValueError(f"weather probabilities missing required columns: {missing}")

    weather_df["season_or_month"] = weather_df["season_or_month"].astype(str).str.strip()
    weather_df["weather_state"] = weather_df["weather_state"].astype(str).str.strip()
    weather_df["probability"] = pd.to_numeric(weather_df["probability"], errors="coerce").fillna(0.0)

    profile_mask = weather_df["season_or_month"].str.casefold() == str(probability_profile).strip().casefold()
    profile_df = weather_df.loc[profile_mask, ["weather_state", "probability"]].copy()
    if profile_df.empty:
        available = sorted(weather_df["season_or_month"].unique().tolist())
        raise ValueError(
            f"Probability profile '{probability_profile}' not found. Available values: {available}"
        )

    raw_probs = profile_df.groupby("weather_state", as_index=False)["probability"].sum()
    probability_map = {state: 0.0 for state in scenarios}
    for row in raw_probs.itertuples(index=False):
        weather_state = str(row.weather_state)
        if weather_state in probability_map:
            probability_map[weather_state] = float(row.probability)

    total_probability = float(sum(probability_map.values()))
    if total_probability <= 0:
        raise ValueError(
            "Selected probability profile has zero total mass over optimization scenarios"
        )

    normalized = {
        state: float(probability_map[state] / total_probability)
        for state in sorted(probability_map)
    }
    return normalized


def build_optimization_inputs(
    candidate_library_path: Path,
    delta_path: Path,
    baseline_path: Path,
    demographics_path: Path,
    weather_probability_path: Path,
    probability_profile: str,
    acs_population_path: Path | None,
) -> tuple[OptimizationInputs, str]:
    candidate_df = pd.read_csv(candidate_library_path, dtype=str)
    missing_candidate_cols = [
        column for column in CANDIDATE_REQUIRED_COLUMNS if column not in candidate_df.columns
    ]
    if missing_candidate_cols:
        raise ValueError(
            f"Candidate library missing required columns: {missing_candidate_cols}"
        )

    candidate_df = candidate_df[CANDIDATE_REQUIRED_COLUMNS].copy()
    candidate_df["candidate_id"] = candidate_df["candidate_id"].astype(str).str.strip()
    candidate_df["cost_cj"] = pd.to_numeric(candidate_df["cost_cj"], errors="coerce")
    candidate_df = candidate_df.dropna(subset=["candidate_id", "cost_cj"])
    candidate_df = candidate_df[candidate_df["candidate_id"] != ""]
    candidate_df = candidate_df.drop_duplicates(subset=["candidate_id"])

    if candidate_df.empty:
        raise ValueError("Candidate library has no valid candidates")

    costs = candidate_df.set_index("candidate_id")["cost_cj"].astype(float).to_dict()
    candidates = sorted(costs.keys())

    baseline_df = pd.read_csv(baseline_path, dtype=str)
    missing_baseline_cols = [
        column for column in BASELINE_REQUIRED_COLUMNS if column not in baseline_df.columns
    ]
    if missing_baseline_cols:
        raise ValueError(
            f"Baseline file missing required columns: {missing_baseline_cols}"
        )

    baseline_df = baseline_df[BASELINE_REQUIRED_COLUMNS].copy()
    baseline_df["tract_id"] = baseline_df["tract_id"].map(normalize_tract_id)
    baseline_df["weather_scenario"] = baseline_df["weather_scenario"].astype(str).str.strip()
    baseline_df["connectivity_score"] = pd.to_numeric(
        baseline_df["connectivity_score"], errors="coerce"
    ).fillna(0.0)
    baseline_df = baseline_df.dropna(subset=["tract_id", "weather_scenario"])

    delta_df = pd.read_csv(delta_path, dtype=str)
    missing_delta_cols = [column for column in DELTA_REQUIRED_COLUMNS if column not in delta_df.columns]
    if missing_delta_cols:
        raise ValueError(f"Delta file missing required columns: {missing_delta_cols}")

    delta_df = delta_df[DELTA_REQUIRED_COLUMNS].copy()
    delta_df["tract_g"] = delta_df["tract_g"].map(normalize_tract_id)
    delta_df["candidate_j"] = delta_df["candidate_j"].astype(str).str.strip()
    delta_df["weather_s"] = delta_df["weather_s"].astype(str).str.strip()
    delta_df["delta_score"] = pd.to_numeric(delta_df["delta_score"], errors="coerce").fillna(0.0)

    delta_df = delta_df[delta_df["candidate_j"].isin(candidates)].copy()
    if delta_df.empty:
        raise ValueError("Delta file has no rows matching candidate_library candidate IDs")

    scenario_set = set(baseline_df["weather_scenario"].unique()) | set(delta_df["weather_s"].unique())
    scenario_probabilities = load_probability_profile(
        weather_probability_path=weather_probability_path,
        probability_profile=probability_profile,
        scenarios=scenario_set,
    )

    scenarios = sorted(scenario_probabilities)
    baseline_df = baseline_df[baseline_df["weather_scenario"].isin(scenarios)].copy()
    delta_df = delta_df[delta_df["weather_s"].isin(scenarios)].copy()

    vulnerability_map = load_vulnerability_map(demographics_path)
    baseline_df["is_vulnerable"] = baseline_df["tract_id"].map(vulnerability_map)
    missing_vulnerability = int(baseline_df["is_vulnerable"].isna().sum())
    baseline_df["is_vulnerable"] = baseline_df["is_vulnerable"].fillna(False)

    tract_ids = set(baseline_df["tract_id"].unique())
    vulnerable_tracts = set(
        baseline_df.loc[baseline_df["is_vulnerable"], "tract_id"].unique().tolist()
    )
    non_vulnerable_tracts = tract_ids - vulnerable_tracts

    if not vulnerable_tracts:
        raise ValueError("No vulnerable tracts found after joining demographics")
    if not non_vulnerable_tracts:
        raise ValueError("No non-vulnerable tracts found after joining demographics")

    population_map, population_source = load_population_map(
        demographics_path=demographics_path,
        acs_population_path=acs_population_path,
        tract_ids=tract_ids,
    )

    alpha_raw = {}
    for tract in tract_ids:
        value = float(population_map.get(tract, 0.0))
        if not np.isfinite(value) or value < 0:
            value = 0.0
        alpha_raw[tract] = value

    total_population = float(sum(alpha_raw.values()))
    if total_population > 0:
        alpha_weights = {tract: alpha_raw[tract] / total_population for tract in tract_ids}
    else:
        uniform_weight = 1.0 / float(len(tract_ids))
        alpha_weights = {tract: uniform_weight for tract in tract_ids}
        population_source = "uniform_fallback"

    delta_df["probability"] = delta_df["weather_s"].map(scenario_probabilities).fillna(0.0)
    delta_df["expected_delta"] = delta_df["delta_score"] * delta_df["probability"]
    delta_df["alpha_weight"] = delta_df["tract_g"].map(alpha_weights).fillna(0.0)
    delta_df["weighted_eff_delta"] = delta_df["expected_delta"] * delta_df["alpha_weight"]
    delta_df["is_vulnerable"] = delta_df["tract_g"].map(lambda tract: tract in vulnerable_tracts)

    efficiency_coeff_series = (
        delta_df.groupby("candidate_j")["weighted_eff_delta"].sum().reindex(candidates, fill_value=0.0)
    )

    vulnerable_expected_series = (
        delta_df.loc[delta_df["is_vulnerable"]]
        .groupby("candidate_j")["expected_delta"]
        .sum()
        .reindex(candidates, fill_value=0.0)
        / float(len(vulnerable_tracts))
    )

    non_vulnerable_expected_series = (
        delta_df.loc[~delta_df["is_vulnerable"]]
        .groupby("candidate_j")["expected_delta"]
        .sum()
        .reindex(candidates, fill_value=0.0)
        / float(len(non_vulnerable_tracts))
    )

    vulnerable_scenario_coeff: dict[str, dict[str, float]] = {scenario: {} for scenario in scenarios}
    vulnerable_scenario_grouped = (
        delta_df.loc[delta_df["is_vulnerable"]]
        .groupby(["weather_s", "candidate_j"], as_index=False)["delta_score"]
        .sum()
    )
    for row in vulnerable_scenario_grouped.itertuples(index=False):
        vulnerable_scenario_coeff[str(row.weather_s)][str(row.candidate_j)] = (
            float(row.delta_score) / float(len(vulnerable_tracts))
        )

    baseline_vulnerable_scenario_avg = (
        baseline_df.loc[baseline_df["is_vulnerable"]]
        .groupby("weather_scenario")["connectivity_score"]
        .mean()
        .reindex(scenarios, fill_value=0.0)
        .to_dict()
    )
    baseline_non_vulnerable_scenario_avg = (
        baseline_df.loc[~baseline_df["is_vulnerable"]]
        .groupby("weather_scenario")["connectivity_score"]
        .mean()
        .reindex(scenarios, fill_value=0.0)
        .to_dict()
    )

    baseline_vulnerable_expected = float(
        sum(
            scenario_probabilities[scenario] * baseline_vulnerable_scenario_avg.get(scenario, 0.0)
            for scenario in scenarios
        )
    )
    baseline_non_vulnerable_expected = float(
        sum(
            scenario_probabilities[scenario]
            * baseline_non_vulnerable_scenario_avg.get(scenario, 0.0)
            for scenario in scenarios
        )
    )

    inputs = OptimizationInputs(
        candidates=candidates,
        scenarios=scenarios,
        costs=costs,
        scenario_probabilities=scenario_probabilities,
        vulnerable_tracts=vulnerable_tracts,
        non_vulnerable_tracts=non_vulnerable_tracts,
        alpha_weights=alpha_weights,
        efficiency_coeff=efficiency_coeff_series.astype(float).to_dict(),
        vulnerable_expected_coeff=vulnerable_expected_series.astype(float).to_dict(),
        non_vulnerable_expected_coeff=non_vulnerable_expected_series.astype(float).to_dict(),
        vulnerable_scenario_coeff=vulnerable_scenario_coeff,
        baseline_vulnerable_scenario_avg={
            scenario: float(value)
            for scenario, value in baseline_vulnerable_scenario_avg.items()
        },
        baseline_non_vulnerable_scenario_avg={
            scenario: float(value)
            for scenario, value in baseline_non_vulnerable_scenario_avg.items()
        },
        baseline_vulnerable_expected=baseline_vulnerable_expected,
        baseline_non_vulnerable_expected=baseline_non_vulnerable_expected,
    )

    info = (
        f"tracts={len(tract_ids)}, vulnerable={len(vulnerable_tracts)}, "
        f"missing_vulnerability={missing_vulnerability}, population_source={population_source}"
    )
    return inputs, info


def choose_solver_name(solver_choice: str) -> tuple[str, str]:
    choice = str(solver_choice).strip().lower()
    if choice == "cbc":
        return CBC, "cbc"
    if choice == "gurobi":
        return GUROBI, "gurobi"

    try:
        probe = Model(sense=MAXIMIZE, solver_name=GUROBI)
        probe.verbose = 0
        del probe
        return GUROBI, "gurobi"
    except Exception:
        return CBC, "cbc"


def create_base_model(
    inputs: OptimizationInputs,
    budget: float,
    solver_name: str,
    threads: int,
    seed: int,
    max_seconds: float,
) -> tuple[Model, dict[str, object]]:
    model = Model(sense=MAXIMIZE, solver_name=solver_name)
    model.verbose = 0

    if threads > 0 and hasattr(model, "threads"):
        model.threads = int(threads)
    if hasattr(model, "seed"):
        model.seed = int(seed)
    if hasattr(model, "max_seconds"):
        model.max_seconds = float(max_seconds)

    x_vars = {
        candidate: model.add_var(var_type=BINARY, name=f"x_{index:05d}")
        for index, candidate in enumerate(inputs.candidates)
    }

    model += (
        xsum(inputs.costs[candidate] * x_vars[candidate] for candidate in inputs.candidates)
        <= float(budget)
    )

    return model, x_vars


def selected_candidates_from_vars(
    x_vars: dict[str, object],
    tolerance: float = 1e-6,
) -> list[str]:
    selected: list[str] = []
    for candidate, variable in x_vars.items():
        value = getattr(variable, "x", None)
        if value is not None and float(value) >= 1.0 - float(tolerance):
            selected.append(candidate)
    selected.sort()
    return selected


def evaluate_solution_metrics(
    inputs: OptimizationInputs,
    selected_candidates: list[str],
) -> dict[str, float]:
    selected_set = set(selected_candidates)

    vulnerable_gain = float(
        sum(
            inputs.vulnerable_expected_coeff.get(candidate, 0.0)
            for candidate in selected_set
        )
    )
    non_vulnerable_gain = float(
        sum(
            inputs.non_vulnerable_expected_coeff.get(candidate, 0.0)
            for candidate in selected_set
        )
    )

    vulnerable_connectivity = inputs.baseline_vulnerable_expected + vulnerable_gain
    non_vulnerable_connectivity = inputs.baseline_non_vulnerable_expected + non_vulnerable_gain
    gap = non_vulnerable_connectivity - vulnerable_connectivity

    robust_floor_values = []
    for scenario in inputs.scenarios:
        scenario_gain = 0.0
        scenario_coeff = inputs.vulnerable_scenario_coeff.get(scenario, {})
        for candidate in selected_set:
            scenario_gain += float(scenario_coeff.get(candidate, 0.0))
        robust_floor_values.append(
            inputs.baseline_vulnerable_scenario_avg.get(scenario, 0.0) + scenario_gain
        )

    robust_floor = float(min(robust_floor_values)) if robust_floor_values else float("nan")

    used_budget = float(sum(inputs.costs[candidate] for candidate in selected_set))

    return {
        "vulnerable_connectivity": float(vulnerable_connectivity),
        "non_vulnerable_connectivity": float(non_vulnerable_connectivity),
        "gap": float(gap),
        "robust_floor": robust_floor,
        "used_budget": used_budget,
    }


def solve_efficiency_fairness(
    inputs: OptimizationInputs,
    budget: float,
    fairness_lambda: float,
    solver_name: str,
    solver_label: str,
    max_seconds: float,
    threads: int,
    seed: int,
) -> dict[str, object]:
    model, x_vars = create_base_model(
        inputs=inputs,
        budget=budget,
        solver_name=solver_name,
        threads=threads,
        seed=seed,
        max_seconds=max_seconds,
    )

    objective_coeff = {}
    for candidate in inputs.candidates:
        fairness_contribution = (
            inputs.non_vulnerable_expected_coeff.get(candidate, 0.0)
            - inputs.vulnerable_expected_coeff.get(candidate, 0.0)
        )
        objective_coeff[candidate] = (
            inputs.efficiency_coeff.get(candidate, 0.0)
            - float(fairness_lambda) * fairness_contribution
        )

    model.objective = xsum(objective_coeff[candidate] * x_vars[candidate] for candidate in inputs.candidates)
    status = model.optimize(max_seconds=float(max_seconds))

    selected_candidates = selected_candidates_from_vars(x_vars)
    metrics = evaluate_solution_metrics(inputs=inputs, selected_candidates=selected_candidates)

    objective_value = float(model.objective_value) if model.num_solutions > 0 else float("nan")

    return {
        "budget": float(budget),
        "lambda": float(fairness_lambda),
        "objective_value": objective_value,
        "vulnerable_connectivity": metrics["vulnerable_connectivity"],
        "gap": metrics["gap"],
        "selected_candidates_list": "|".join(selected_candidates),
        "selected_candidate_count": len(selected_candidates),
        "used_budget": metrics["used_budget"],
        "solver": solver_label,
        "status": status.name if isinstance(status, OptimizationStatus) else str(status),
    }


def solve_robust_max_min(
    inputs: OptimizationInputs,
    budget: float,
    solver_name: str,
    solver_label: str,
    max_seconds: float,
    threads: int,
    seed: int,
) -> dict[str, object]:
    model, x_vars = create_base_model(
        inputs=inputs,
        budget=budget,
        solver_name=solver_name,
        threads=threads,
        seed=seed,
        max_seconds=max_seconds,
    )

    z_var = model.add_var(var_type=CONTINUOUS, lb=-1e18, name="z_vulnerable_floor")

    for scenario in inputs.scenarios:
        scenario_coeff = inputs.vulnerable_scenario_coeff.get(scenario, {})
        model += (
            z_var
            <= inputs.baseline_vulnerable_scenario_avg.get(scenario, 0.0)
            + xsum(
                float(scenario_coeff.get(candidate, 0.0)) * x_vars[candidate]
                for candidate in inputs.candidates
            )
        )

    model.objective = z_var
    status = model.optimize(max_seconds=float(max_seconds))

    selected_candidates = selected_candidates_from_vars(x_vars)
    metrics = evaluate_solution_metrics(inputs=inputs, selected_candidates=selected_candidates)

    objective_value = float(z_var.x) if z_var.x is not None else float("nan")

    return {
        "budget": float(budget),
        "lambda": np.nan,
        "objective_value": objective_value,
        "vulnerable_connectivity": metrics["vulnerable_connectivity"],
        "gap": metrics["gap"],
        "selected_candidates_list": "|".join(selected_candidates),
        "selected_candidate_count": len(selected_candidates),
        "used_budget": metrics["used_budget"],
        "robust_floor": metrics["robust_floor"],
        "solver": solver_label,
        "status": status.name if isinstance(status, OptimizationStatus) else str(status),
    }


def run_sweeps(
    inputs: OptimizationInputs,
    budgets: list[float],
    lambdas: list[float],
    solver_name: str,
    solver_label: str,
    max_seconds: float,
    threads: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    efficiency_rows: list[dict[str, object]] = []
    robust_rows: list[dict[str, object]] = []

    for budget in budgets:
        for fairness_lambda in lambdas:
            row = solve_efficiency_fairness(
                inputs=inputs,
                budget=budget,
                fairness_lambda=fairness_lambda,
                solver_name=solver_name,
                solver_label=solver_label,
                max_seconds=max_seconds,
                threads=threads,
                seed=seed,
            )
            efficiency_rows.append(row)

        robust_row = solve_robust_max_min(
            inputs=inputs,
            budget=budget,
            solver_name=solver_name,
            solver_label=solver_label,
            max_seconds=max_seconds,
            threads=threads,
            seed=seed,
        )
        robust_rows.append(robust_row)

    efficiency_df = pd.DataFrame(efficiency_rows)
    robust_df = pd.DataFrame(robust_rows)

    return efficiency_df, robust_df


def main() -> None:
    args = parse_args()
    ensure_data_dirs()

    candidate_library_path = resolve_project_path(args.candidate_library_path)
    delta_path = resolve_project_path(args.delta_path)
    baseline_path = resolve_project_path(args.baseline_path)
    weather_probability_path = resolve_project_path(args.weather_probability_path)
    demographics_path = resolve_project_path(args.demographics_path)

    acs_population_path: Path | None
    if args.acs_population_path:
        acs_population_path = resolve_project_path(args.acs_population_path)
    else:
        acs_population_path = detect_latest_acs_tract_file(ACS_RAW_DIR)

    budgets = parse_float_grid(args.budgets, "budget")
    lambdas = parse_float_grid(args.lambdas, "lambda")

    if any(budget < 0 for budget in budgets):
        raise ValueError("Budgets must be non-negative")

    solver_name, solver_label = choose_solver_name(args.solver)

    inputs, input_info = build_optimization_inputs(
        candidate_library_path=candidate_library_path,
        delta_path=delta_path,
        baseline_path=baseline_path,
        demographics_path=demographics_path,
        weather_probability_path=weather_probability_path,
        probability_profile=args.probability_profile,
        acs_population_path=acs_population_path,
    )

    efficiency_df, robust_df = run_sweeps(
        inputs=inputs,
        budgets=budgets,
        lambdas=lambdas,
        solver_name=solver_name,
        solver_label=solver_label,
        max_seconds=float(args.max_seconds),
        threads=int(args.threads),
        seed=int(args.seed),
    )

    efficiency_output = resolve_project_path(args.efficiency_output)
    robust_output = resolve_project_path(args.robust_output)

    efficiency_output.parent.mkdir(parents=True, exist_ok=True)
    robust_output.parent.mkdir(parents=True, exist_ok=True)

    efficiency_df = efficiency_df[
        [
            "budget",
            "lambda",
            "objective_value",
            "vulnerable_connectivity",
            "gap",
            "selected_candidates_list",
            "selected_candidate_count",
            "used_budget",
            "solver",
            "status",
        ]
    ]
    robust_df = robust_df[
        [
            "budget",
            "lambda",
            "objective_value",
            "vulnerable_connectivity",
            "gap",
            "selected_candidates_list",
            "selected_candidate_count",
            "used_budget",
            "robust_floor",
            "solver",
            "status",
        ]
    ]

    efficiency_df.to_csv(efficiency_output, index=False)
    robust_df.to_csv(robust_output, index=False)

    print(f"Input summary: {input_info}")
    print(f"Solver backend: {solver_label}")
    print(f"Probability profile: {args.probability_profile}")
    print(f"Model 1 rows: {len(efficiency_df)} -> {efficiency_output}")
    print(f"Model 2 rows: {len(robust_df)} -> {robust_output}")


if __name__ == "__main__":
    main()
