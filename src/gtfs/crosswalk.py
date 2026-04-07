from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import GTFS_CURRENT_DIR, PROCESSED_DATA_DIR, PROJECT_ROOT


ROUTES_COLUMNS = ["route_id", "route_short_name"]
CROSSWALK_COLUMNS = [
    "version_id",
    "historic_route_id",
    "route_short_name",
    "canonical_route_id",
    "mapping_confidence",
]


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _find_member_name(archive: zipfile.ZipFile, file_name: str) -> str:
    for member in archive.namelist():
        if member.endswith("/"):
            continue
        if Path(member).name == file_name:
            return member
    raise FileNotFoundError(f"{file_name} not found in archive")


def read_gtfs_table(feed_path: Path, table_name: str, usecols: list[str] | None = None) -> pd.DataFrame:
    if feed_path.is_dir():
        candidates = sorted(feed_path.rglob(table_name))
        if not candidates:
            raise FileNotFoundError(f"{table_name} not found under directory {feed_path}")
        return pd.read_csv(candidates[0], dtype=str, usecols=usecols)

    if feed_path.suffix.lower() != ".zip":
        raise FileNotFoundError(f"Unsupported GTFS feed path: {feed_path}")

    with zipfile.ZipFile(feed_path, "r") as archive:
        member = _find_member_name(archive, table_name)
        with archive.open(member) as fh:
            return pd.read_csv(fh, dtype=str, usecols=usecols)


def load_routes_table(feed_path: Path) -> pd.DataFrame:
    return read_gtfs_table(feed_path=feed_path, table_name="routes.txt", usecols=ROUTES_COLUMNS)


def normalize_route_short_name(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    normalized = " ".join(text.split()).lower()
    return normalized or None


def build_current_route_index(current_feed_path: Path) -> tuple[dict[str, list[str]], set[str]]:
    routes = load_routes_table(current_feed_path)
    routes = routes.dropna(subset=["route_id"])
    routes["route_id"] = routes["route_id"].astype(str)
    routes["normalized_short_name"] = routes["route_short_name"].map(normalize_route_short_name)

    grouped: dict[str, list[str]] = {}
    for short_name, group in routes.dropna(subset=["normalized_short_name"]).groupby("normalized_short_name"):
        grouped[str(short_name)] = sorted(set(group["route_id"].astype(str)))

    return grouped, set(routes["route_id"].astype(str))


def map_routes_to_current(
    historical_routes: pd.DataFrame,
    current_short_name_index: dict[str, list[str]],
    current_route_ids: set[str],
) -> pd.DataFrame:
    mapped = historical_routes.copy()
    mapped["historic_route_id"] = mapped["route_id"].astype(str)
    mapped["normalized_short_name"] = mapped["route_short_name"].map(normalize_route_short_name)

    canonical_route_ids: list[str] = []
    confidence_labels: list[str] = []

    for _, row in mapped.iterrows():
        historic_route_id = str(row["historic_route_id"])
        normalized_short_name = row["normalized_short_name"]

        if normalized_short_name and normalized_short_name in current_short_name_index:
            candidates = current_short_name_index[normalized_short_name]
            if len(candidates) == 1:
                canonical_route_ids.append(candidates[0])
                confidence_labels.append("exact_short_name")
            elif historic_route_id in candidates:
                canonical_route_ids.append(historic_route_id)
                confidence_labels.append("short_name_ambiguous_route_matched")
            else:
                canonical_route_ids.append(candidates[0])
                confidence_labels.append("short_name_ambiguous")
        elif historic_route_id in current_route_ids:
            canonical_route_ids.append(historic_route_id)
            confidence_labels.append("exact_route_id")
        else:
            canonical_route_ids.append(historic_route_id)
            confidence_labels.append("unmapped")

    mapped["canonical_route_id"] = canonical_route_ids
    mapped["mapping_confidence"] = confidence_labels

    return mapped[["historic_route_id", "route_short_name", "canonical_route_id", "mapping_confidence"]]


def build_crosswalk_for_manifest(
    manifest_df: pd.DataFrame,
    current_feed_path: Path,
) -> pd.DataFrame:
    current_short_name_index, current_route_ids = build_current_route_index(current_feed_path)
    crosswalk_frames: list[pd.DataFrame] = []

    for _, row in manifest_df.iterrows():
        version_id = str(row.get("version_id", ""))
        raw_feed_path = str(row.get("file_path", "") or "").strip()
        if not raw_feed_path:
            continue

        feed_path = resolve_project_path(raw_feed_path)
        if not feed_path.exists():
            continue

        routes = load_routes_table(feed_path)
        mapped = map_routes_to_current(routes, current_short_name_index, current_route_ids)
        mapped.insert(0, "version_id", version_id)
        crosswalk_frames.append(mapped)

    if not crosswalk_frames:
        return pd.DataFrame(columns=CROSSWALK_COLUMNS)

    crosswalk_df = pd.concat(crosswalk_frames, ignore_index=True)
    return crosswalk_df[CROSSWALK_COLUMNS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build route_id crosswalk from GTFS route_short_name")
    parser.add_argument("--manifest-path", default=str(PROCESSED_DATA_DIR / "feeds_manifest.csv"))
    parser.add_argument(
        "--current-feed-path",
        default=str(GTFS_CURRENT_DIR / "google_transit_current"),
        help="Current GTFS folder or zip used as canonical route_id reference",
    )
    parser.add_argument(
        "--output-path",
        default=str(PROCESSED_DATA_DIR / "route_id_crosswalk.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = resolve_project_path(args.manifest_path)
    current_feed_path = resolve_project_path(args.current_feed_path)
    output_path = resolve_project_path(args.output_path)

    manifest_df = pd.read_csv(manifest_path, dtype=str)
    crosswalk_df = build_crosswalk_for_manifest(
        manifest_df=manifest_df,
        current_feed_path=current_feed_path,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    crosswalk_df.to_csv(output_path, index=False)

    print(f"Crosswalk rows: {len(crosswalk_df)}")
    print(f"Crosswalk output: {output_path}")


if __name__ == "__main__":
    main()
