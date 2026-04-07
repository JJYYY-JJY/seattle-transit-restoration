from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

MPL_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "matplotlib"
MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from shapely.geometry import LineString

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import GTFS_CURRENT_DIR, PROCESSED_DATA_DIR, PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate publication-ready Phase 9 figures for descriptive analysis "
            "and optimization outputs."
        )
    )
    parser.add_argument(
        "--service-panel-path",
        default=str(PROCESSED_DATA_DIR / "service_panel_route_period.csv"),
        help="Route-period service panel from Phase 2",
    )
    parser.add_argument(
        "--feeds-manifest-path",
        default=str(PROCESSED_DATA_DIR / "feeds_manifest.csv"),
        help="GTFS feed manifest for mapping version IDs to dates",
    )
    parser.add_argument(
        "--route-crosswalk-path",
        default=str(PROCESSED_DATA_DIR / "route_id_crosswalk.csv"),
        help="Route ID crosswalk for canonical route mapping",
    )
    parser.add_argument(
        "--fairness-tradeoff-path",
        default=str(PROCESSED_DATA_DIR / "phase8_fairness_tradeoff.csv"),
        help="Phase 8 fairness frontier results",
    )
    parser.add_argument(
        "--efficiency-frontier-path",
        default=str(PROCESSED_DATA_DIR / "phase8_efficiency_frontier.csv"),
        help="Phase 8 efficiency frontier results",
    )
    parser.add_argument(
        "--candidate-library-path",
        default=str(PROCESSED_DATA_DIR / "candidate_library.csv"),
        help="Phase 6 candidate library",
    )
    parser.add_argument(
        "--baseline-connectivity-path",
        default=str(PROCESSED_DATA_DIR / "baseline_connectivity_scores.csv"),
        help="Baseline weather scenario connectivity scores",
    )
    parser.add_argument(
        "--marginal-gains-path",
        default=str(PROCESSED_DATA_DIR / "marginal_gains_delta.csv"),
        help="Candidate marginal connectivity gains",
    )
    parser.add_argument(
        "--robust-results-path",
        default=str(PROCESSED_DATA_DIR / "optimization_results_robust.csv"),
        help="Robust optimization output used for weather comparison",
    )
    parser.add_argument(
        "--centroids-path",
        default=str(PROCESSED_DATA_DIR / "acs_demographics_centroids.geojson"),
        help="ACS tract geometry and vulnerability labels",
    )
    parser.add_argument(
        "--gtfs-feed-path",
        default=str(GTFS_CURRENT_DIR / "google_transit_current"),
        help="Current GTFS folder containing routes/trips/shapes tables",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/figures",
        help="Output directory for generated figures",
    )
    parser.add_argument(
        "--medium-budget",
        type=float,
        default=1000.0,
        help="Target medium budget used for the candidate selection map",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=320,
        help="PNG export resolution",
    )
    return parser.parse_args()


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def normalize_id(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip()
    return normalized.str.replace(r"\.0$", "", regex=True)


def parse_candidate_list(candidate_blob: str) -> list[str]:
    if candidate_blob is None:
        return []
    text = str(candidate_blob).strip()
    if not text or text.lower() == "nan":
        return []
    return [token.strip() for token in text.split("|") if token.strip()]


def apply_publication_style() -> None:
    sns.set_theme(context="talk", style="whitegrid")
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "#fcfcfd",
            "axes.edgecolor": "#333333",
            "axes.linewidth": 1.0,
            "axes.titleweight": "bold",
            "axes.titlesize": 16,
            "axes.labelsize": 12,
            "grid.color": "#d8dde6",
            "grid.linewidth": 0.8,
            "grid.alpha": 0.8,
            "legend.frameon": True,
            "legend.facecolor": "white",
            "legend.framealpha": 0.95,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "savefig.bbox": "tight",
        }
    )


def save_figure(fig: plt.Figure, output_dir: Path, stem: str, dpi: int) -> list[Path]:
    output_paths = [
        output_dir / f"{stem}.png",
        output_dir / f"{stem}.pdf",
    ]
    for output_path in output_paths:
        if output_path.suffix == ".png":
            fig.savefig(output_path, dpi=dpi)
        else:
            fig.savefig(output_path)
    plt.close(fig)
    return output_paths


def load_route_geometries(gtfs_feed_dir: Path) -> gpd.GeoDataFrame:
    routes = pd.read_csv(
        gtfs_feed_dir / "routes.txt",
        usecols=["route_id", "route_short_name", "route_long_name"],
        dtype=str,
    )
    routes["route_id"] = normalize_id(routes["route_id"])

    trips = pd.read_csv(
        gtfs_feed_dir / "trips.txt",
        usecols=["route_id", "shape_id"],
        dtype=str,
    ).dropna(subset=["route_id", "shape_id"])
    trips["route_id"] = normalize_id(trips["route_id"])
    trips["shape_id"] = trips["shape_id"].astype(str).str.strip()

    shape_choice = (
        trips.groupby(["route_id", "shape_id"], as_index=False)
        .size()
        .sort_values(["route_id", "size"], ascending=[True, False])
        .drop_duplicates("route_id")
        [["route_id", "shape_id"]]
    )

    shapes = pd.read_csv(
        gtfs_feed_dir / "shapes.txt",
        usecols=["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
        dtype={"shape_id": str},
    )
    shapes = shapes[shapes["shape_id"].isin(set(shape_choice["shape_id"]))].copy()
    shapes["shape_pt_lat"] = pd.to_numeric(shapes["shape_pt_lat"], errors="coerce")
    shapes["shape_pt_lon"] = pd.to_numeric(shapes["shape_pt_lon"], errors="coerce")
    shapes["shape_pt_sequence"] = pd.to_numeric(shapes["shape_pt_sequence"], errors="coerce")
    shapes = shapes.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
    shapes = shapes.sort_values(["shape_id", "shape_pt_sequence"])

    geometry_rows: list[dict[str, object]] = []
    for shape_id, group in shapes.groupby("shape_id", sort=False):
        coords = list(zip(group["shape_pt_lon"], group["shape_pt_lat"]))
        if len(coords) < 2:
            continue
        geometry_rows.append({"shape_id": shape_id, "geometry": LineString(coords)})

    shape_gdf = gpd.GeoDataFrame(geometry_rows, geometry="geometry", crs="EPSG:4326")
    route_geom = shape_choice.merge(shape_gdf, on="shape_id", how="inner").merge(
        routes, on="route_id", how="left"
    )
    route_geom = gpd.GeoDataFrame(route_geom, geometry="geometry", crs="EPSG:4326")
    return route_geom


def plot_service_drift(
    service_panel_path: Path,
    feeds_manifest_path: Path,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    panel = pd.read_csv(service_panel_path, usecols=["version_id", "service_hours"], dtype=str)
    panel["version_id"] = normalize_id(panel["version_id"])
    panel["service_hours"] = pd.to_numeric(panel["service_hours"], errors="coerce").fillna(0.0)

    drift = (
        panel.groupby("version_id", as_index=False)["service_hours"]
        .sum()
        .rename(columns={"service_hours": "total_service_hours"})
    )

    manifest = pd.read_csv(feeds_manifest_path, usecols=["version_id", "date_start"], dtype=str)
    manifest["version_id"] = normalize_id(manifest["version_id"])
    manifest["date_start"] = pd.to_datetime(manifest["date_start"], errors="coerce")

    drift = drift.merge(manifest, on="version_id", how="left")
    drift["version_num"] = pd.to_numeric(drift["version_id"], errors="coerce")
    drift = drift.sort_values(["date_start", "version_num"], na_position="last").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.plot(
        drift["date_start"],
        drift["total_service_hours"],
        color="#1f4e79",
        marker="o",
        markersize=4,
        linewidth=2.2,
    )
    ax.fill_between(
        drift["date_start"],
        drift["total_service_hours"],
        color="#4f85b6",
        alpha=0.12,
    )

    covid_window = drift[
        (drift["date_start"] >= pd.Timestamp("2020-03-01"))
        & (drift["date_start"] <= pd.Timestamp("2021-12-31"))
    ]
    if not covid_window.empty:
        trough = covid_window.loc[covid_window["total_service_hours"].idxmin()]
        ax.scatter(
            [trough["date_start"]],
            [trough["total_service_hours"]],
            color="#c1121f",
            s=85,
            zorder=4,
            label="COVID-era trough",
        )
        ax.annotate(
            "COVID-era trough",
            xy=(trough["date_start"], trough["total_service_hours"]),
            xytext=(18, -24),
            textcoords="offset points",
            color="#7a0c13",
            fontsize=10,
            arrowprops={"arrowstyle": "->", "lw": 1.2, "color": "#7a0c13"},
        )

    ax.set_title("Historical System-Wide Scheduled Service Hours")
    ax.set_xlabel("GTFS feed start date")
    ax.set_ylabel("Total scheduled service hours")
    ax.legend(loc="best")
    fig.autofmt_xdate()
    return save_figure(fig, output_dir, "fig1_service_drift", dpi)


def compute_route_volatility(service_panel_path: Path, route_crosswalk_path: Path) -> pd.DataFrame:
    panel = pd.read_csv(
        service_panel_path,
        usecols=["version_id", "route_id", "service_hours"],
        dtype=str,
    )
    panel["version_id"] = normalize_id(panel["version_id"])
    panel["route_id"] = normalize_id(panel["route_id"])
    panel["service_hours"] = pd.to_numeric(panel["service_hours"], errors="coerce").fillna(0.0)

    crosswalk = pd.read_csv(
        route_crosswalk_path,
        usecols=["version_id", "historic_route_id", "canonical_route_id"],
        dtype=str,
    )
    crosswalk["version_id"] = normalize_id(crosswalk["version_id"])
    crosswalk["historic_route_id"] = normalize_id(crosswalk["historic_route_id"])
    crosswalk["canonical_route_id"] = normalize_id(crosswalk["canonical_route_id"])

    merged = panel.merge(
        crosswalk,
        left_on=["version_id", "route_id"],
        right_on=["version_id", "historic_route_id"],
        how="left",
    )
    merged["canonical_route_id"] = merged["canonical_route_id"].fillna(merged["route_id"])

    route_version = (
        merged.groupby(["canonical_route_id", "version_id"], as_index=False)["service_hours"]
        .sum()
        .rename(columns={"service_hours": "service_hours_total"})
    )

    volatility = route_version.groupby("canonical_route_id", as_index=False).agg(
        service_hours_std=("service_hours_total", lambda s: float(np.std(s.to_numpy(), ddof=0))),
        service_hours_mean=("service_hours_total", "mean"),
    )
    return volatility


def plot_volatility_map(
    route_geometries: gpd.GeoDataFrame,
    route_volatility: pd.DataFrame,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    map_df = route_geometries.merge(
        route_volatility,
        left_on="route_id",
        right_on="canonical_route_id",
        how="left",
    )
    map_df["service_hours_std"] = pd.to_numeric(map_df["service_hours_std"], errors="coerce").fillna(0.0)

    fig, ax = plt.subplots(figsize=(10.5, 10.5))
    map_df.plot(ax=ax, color="#c9cdd2", linewidth=0.7, alpha=0.55)

    threshold = float(map_df["service_hours_std"].quantile(0.85))
    highlight = map_df[map_df["service_hours_std"] >= threshold].copy()
    if highlight.empty:
        highlight = map_df.nlargest(25, "service_hours_std").copy()

    if len(highlight) > 0:
        min_v = float(highlight["service_hours_std"].min())
        max_v = float(highlight["service_hours_std"].max())
        if math.isclose(min_v, max_v):
            highlight["line_width"] = 2.4
        else:
            scaled = (highlight["service_hours_std"] - min_v) / (max_v - min_v)
            highlight["line_width"] = 1.8 + 3.8 * scaled

        highlight.plot(
            ax=ax,
            column="service_hours_std",
            cmap="YlOrRd",
            linewidth=highlight["line_width"],
            alpha=0.95,
        )

        norm = Normalize(vmin=min_v, vmax=max_v if max_v > min_v else min_v + 1.0)
        colorbar = fig.colorbar(
            ScalarMappable(norm=norm, cmap="YlOrRd"),
            ax=ax,
            fraction=0.03,
            pad=0.01,
        )
        colorbar.set_label("Std dev of route service hours")

    ax.set_title("Service Volatility Map (Most Variable Routes Highlighted)")
    ax.set_axis_off()
    return save_figure(fig, output_dir, "fig2_volatility_map", dpi)


def plot_fairness_frontier(
    fairness_tradeoff_path: Path,
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    tradeoff = pd.read_csv(fairness_tradeoff_path)
    tradeoff["lambda"] = pd.to_numeric(tradeoff["lambda"], errors="coerce")

    x_col = "efficiency_gain" if "efficiency_gain" in tradeoff.columns else "objective_value"
    tradeoff[x_col] = pd.to_numeric(tradeoff[x_col], errors="coerce")
    tradeoff["vulnerable_connectivity"] = pd.to_numeric(
        tradeoff["vulnerable_connectivity"], errors="coerce"
    )
    tradeoff = tradeoff.dropna(subset=["lambda", x_col, "vulnerable_connectivity"]).sort_values("lambda")

    fig, ax = plt.subplots(figsize=(8.8, 6.6))
    ax.plot(
        tradeoff[x_col],
        tradeoff["vulnerable_connectivity"],
        marker="o",
        markersize=7,
        linewidth=2.0,
        color="#15616d",
    )
    ax.scatter(
        tradeoff[x_col],
        tradeoff["vulnerable_connectivity"],
        c=tradeoff["lambda"],
        cmap="viridis",
        s=75,
        edgecolor="white",
        linewidth=0.8,
        zorder=3,
    )

    for _, row in tradeoff.iterrows():
        ax.annotate(
            f"$\\lambda$={row['lambda']:.2f}",
            xy=(row[x_col], row["vulnerable_connectivity"]),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=9,
            color="#1f2937",
        )

    ax.set_title("Fairness Frontier: Efficiency vs Vulnerable Connectivity")
    ax.set_xlabel("Efficiency objective value")
    ax.set_ylabel("Vulnerable tract connectivity")
    return save_figure(fig, output_dir, "fig3_fairness_frontier", dpi)


def choose_medium_budget_solution(
    efficiency_frontier_path: Path,
    target_budget: float,
) -> tuple[pd.Series, float]:
    frontier = pd.read_csv(efficiency_frontier_path)
    frontier["budget"] = pd.to_numeric(frontier["budget"], errors="coerce")
    frontier["lambda"] = pd.to_numeric(frontier.get("lambda", 0.0), errors="coerce").fillna(0.0)
    frontier = frontier.dropna(subset=["budget"])

    budget_values = sorted(frontier["budget"].unique())
    if not budget_values:
        raise ValueError("No valid budget values found in efficiency frontier")

    selected_budget = min(budget_values, key=lambda value: abs(value - target_budget))
    chosen = frontier[frontier["budget"] == selected_budget].sort_values("lambda").iloc[0]
    return chosen, float(selected_budget)


def compute_selected_route_intensity(candidate_library_path: Path, selected_ids: set[str]) -> pd.DataFrame:
    candidates = pd.read_csv(
        candidate_library_path,
        usecols=["candidate_id", "route_id", "increment_trips"],
        dtype=str,
    )
    candidates["candidate_id"] = candidates["candidate_id"].astype(str).str.strip()
    candidates["route_id"] = normalize_id(candidates["route_id"])
    candidates["increment_trips"] = pd.to_numeric(candidates["increment_trips"], errors="coerce").fillna(0.0)

    selected = candidates[candidates["candidate_id"].isin(selected_ids)].copy()
    intensity = (
        selected.groupby("route_id", as_index=False)
        .agg(restoration_intensity=("increment_trips", "sum"), selected_steps=("candidate_id", "count"))
        .sort_values("restoration_intensity", ascending=False)
    )
    return intensity


def plot_candidate_selection_map(
    route_geometries: gpd.GeoDataFrame,
    route_intensity: pd.DataFrame,
    output_dir: Path,
    dpi: int,
    selected_budget: float,
) -> list[Path]:
    map_df = route_geometries.merge(route_intensity, on="route_id", how="left")
    map_df["restoration_intensity"] = pd.to_numeric(
        map_df["restoration_intensity"], errors="coerce"
    ).fillna(0.0)

    fig, ax = plt.subplots(figsize=(10.5, 10.5))
    map_df.plot(ax=ax, color="#d3d6db", linewidth=0.7, alpha=0.55)

    selected = map_df[map_df["restoration_intensity"] > 0].copy()
    if len(selected) > 0:
        min_i = float(selected["restoration_intensity"].min())
        max_i = float(selected["restoration_intensity"].max())
        if math.isclose(min_i, max_i):
            selected["line_width"] = 2.6
        else:
            scaled = (selected["restoration_intensity"] - min_i) / (max_i - min_i)
            selected["line_width"] = 1.7 + 4.6 * scaled

        selected.plot(
            ax=ax,
            column="restoration_intensity",
            cmap="plasma",
            linewidth=selected["line_width"],
            alpha=0.95,
        )

        norm = Normalize(vmin=min_i, vmax=max_i if max_i > min_i else min_i + 1.0)
        colorbar = fig.colorbar(
            ScalarMappable(norm=norm, cmap="plasma"),
            ax=ax,
            fraction=0.03,
            pad=0.01,
        )
        colorbar.set_label("Restoration intensity (incremental trips)")

    ax.set_title(f"Candidate Selection Map (Medium Budget = {selected_budget:.0f})")
    ax.set_axis_off()
    return save_figure(fig, output_dir, "fig4_candidate_selection_map", dpi)


def compute_weather_comparison(
    baseline_connectivity_path: Path,
    marginal_gains_path: Path,
    robust_results_path: Path,
    centroids_path: Path,
) -> dict[str, float]:
    centroids = gpd.read_file(centroids_path)[["geoid", "vulnerable"]].copy()
    centroids["geoid"] = normalize_id(centroids["geoid"])
    centroids["vulnerable"] = centroids["vulnerable"].astype(str).str.lower().isin({"1", "true", "yes"})
    vulnerable_tracts = set(centroids.loc[centroids["vulnerable"], "geoid"])

    baseline = pd.read_csv(baseline_connectivity_path, dtype=str)
    baseline["tract_id"] = normalize_id(baseline["tract_id"])
    baseline["connectivity_score"] = pd.to_numeric(
        baseline["connectivity_score"], errors="coerce"
    ).fillna(0.0)
    heavy_baseline = baseline[baseline["weather_scenario"] == "Heavy Rain"].copy()
    heavy_baseline = heavy_baseline[heavy_baseline["tract_id"].isin(vulnerable_tracts)].copy()

    robust = pd.read_csv(robust_results_path)
    selected_candidates = set(parse_candidate_list(str(robust.iloc[0]["selected_candidates_list"])))

    deltas = pd.read_csv(
        marginal_gains_path,
        usecols=["tract_g", "candidate_j", "weather_s", "delta_score"],
        dtype=str,
    )
    deltas["tract_g"] = normalize_id(deltas["tract_g"])
    deltas["delta_score"] = pd.to_numeric(deltas["delta_score"], errors="coerce").fillna(0.0)
    selected_heavy = deltas[
        (deltas["weather_s"] == "Heavy Rain") & (deltas["candidate_j"].isin(selected_candidates))
    ].copy()

    gains = (
        selected_heavy.groupby("tract_g", as_index=False)["delta_score"]
        .sum()
        .rename(columns={"tract_g": "tract_id", "delta_score": "restoration_gain"})
    )

    heavy_restored = heavy_baseline.merge(gains, on="tract_id", how="left")
    heavy_restored["restoration_gain"] = heavy_restored["restoration_gain"].fillna(0.0)
    heavy_restored["restored_connectivity"] = (
        heavy_restored["connectivity_score"] + heavy_restored["restoration_gain"]
    )

    return {
        "baseline_mean": float(heavy_restored["connectivity_score"].mean()),
        "restored_mean": float(heavy_restored["restored_connectivity"].mean()),
        "baseline_sum": float(heavy_restored["connectivity_score"].sum()),
        "restored_sum": float(heavy_restored["restored_connectivity"].sum()),
    }


def plot_weather_robustness(
    weather_comparison: dict[str, float],
    output_dir: Path,
    dpi: int,
) -> list[Path]:
    labels = ["Baseline\n(Heavy Rain)", "Restored\n(Heavy Rain, robust)"]
    values = [weather_comparison["baseline_mean"], weather_comparison["restored_mean"]]
    colors = ["#8d99ae", "#2a9d8f"]

    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    bars = ax.bar(labels, values, color=colors, width=0.58)

    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            f"{height:,.0f}",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    uplift = 100.0 * (values[1] - values[0]) / values[0] if values[0] else 0.0
    ax.set_title("Weather Robustness for Vulnerable Tracts")
    ax.set_ylabel("Mean connectivity score")
    ax.text(
        0.5,
        0.95,
        f"Mean uplift under Heavy Rain: {uplift:.1f}%",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color="#1f2937",
    )
    return save_figure(fig, output_dir, "fig5_weather_robustness_bar", dpi)


def main() -> None:
    args = parse_args()
    apply_publication_style()

    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    service_panel_path = resolve_project_path(args.service_panel_path)
    feeds_manifest_path = resolve_project_path(args.feeds_manifest_path)
    route_crosswalk_path = resolve_project_path(args.route_crosswalk_path)
    fairness_tradeoff_path = resolve_project_path(args.fairness_tradeoff_path)
    efficiency_frontier_path = resolve_project_path(args.efficiency_frontier_path)
    candidate_library_path = resolve_project_path(args.candidate_library_path)
    baseline_connectivity_path = resolve_project_path(args.baseline_connectivity_path)
    marginal_gains_path = resolve_project_path(args.marginal_gains_path)
    robust_results_path = resolve_project_path(args.robust_results_path)
    centroids_path = resolve_project_path(args.centroids_path)
    gtfs_feed_path = resolve_project_path(args.gtfs_feed_path)

    generated_files: list[str] = []

    generated_files.extend(
        str(path)
        for path in plot_service_drift(
            service_panel_path=service_panel_path,
            feeds_manifest_path=feeds_manifest_path,
            output_dir=output_dir,
            dpi=args.dpi,
        )
    )

    route_geometries = load_route_geometries(gtfs_feed_path)
    route_volatility = compute_route_volatility(service_panel_path, route_crosswalk_path)
    generated_files.extend(
        str(path)
        for path in plot_volatility_map(
            route_geometries=route_geometries,
            route_volatility=route_volatility,
            output_dir=output_dir,
            dpi=args.dpi,
        )
    )

    generated_files.extend(
        str(path)
        for path in plot_fairness_frontier(
            fairness_tradeoff_path=fairness_tradeoff_path,
            output_dir=output_dir,
            dpi=args.dpi,
        )
    )

    medium_solution, selected_budget = choose_medium_budget_solution(
        efficiency_frontier_path=efficiency_frontier_path,
        target_budget=args.medium_budget,
    )
    selected_candidates = set(
        parse_candidate_list(str(medium_solution.get("selected_candidates_list", "")))
    )
    route_intensity = compute_selected_route_intensity(candidate_library_path, selected_candidates)
    generated_files.extend(
        str(path)
        for path in plot_candidate_selection_map(
            route_geometries=route_geometries,
            route_intensity=route_intensity,
            output_dir=output_dir,
            dpi=args.dpi,
            selected_budget=selected_budget,
        )
    )

    weather_comparison = compute_weather_comparison(
        baseline_connectivity_path=baseline_connectivity_path,
        marginal_gains_path=marginal_gains_path,
        robust_results_path=robust_results_path,
        centroids_path=centroids_path,
    )
    generated_files.extend(
        str(path)
        for path in plot_weather_robustness(
            weather_comparison=weather_comparison,
            output_dir=output_dir,
            dpi=args.dpi,
        )
    )

    manifest = {
        "generated_count": len(generated_files),
        "medium_budget_selected": selected_budget,
        "weather_metrics": weather_comparison,
        "files": generated_files,
    }
    manifest_path = output_dir / "figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Generated figures:")
    for file_path in generated_files:
        print(f" - {file_path}")
    print(f"Saved figure manifest: {manifest_path}")


if __name__ == "__main__":
    main()