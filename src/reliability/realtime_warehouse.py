from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import PROCESSED_DATA_DIR, PROJECT_ROOT, ensure_data_dirs

SCHEMA_VERSION = "realtime_warehouse.v1"

NORMALIZED_COLUMNS = [
    "feed",
    "event_role",
    "entity_id",
    "service_date",
    "route_id",
    "direction_id",
    "trip_id",
    "stop_id",
    "event_ts",
    "capture_ts",
    "header_ts",
    "stop_sequence",
    "delay_seconds",
    "schedule_relationship",
    "vehicle_id",
    "latitude",
    "longitude",
    "current_status",
    "occupancy_status",
    "alert_cause",
    "alert_effect",
    "source_manifest",
    "source_raw_file",
    "source_url",
    "source_sha256",
]

REQUIRED_COLUMNS = [
    "feed",
    "event_role",
    "service_date",
    "route_id",
    "direction_id",
    "trip_id",
    "stop_id",
    "event_ts",
    "capture_ts",
    "source_manifest",
    "source_raw_file",
    "source_url",
    "source_sha256",
]

PROVENANCE_COLUMNS = [
    "source_manifest",
    "source_raw_file",
    "source_url",
    "source_sha256",
]

TIMESTAMP_COLUMNS = ["event_ts", "capture_ts", "header_ts"]
INT_COLUMNS = ["stop_sequence", "delay_seconds"]
FLOAT_COLUMNS = ["latitude", "longitude"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build warehouse-ready parquet tables from normalized GTFS-RT event rows. "
            "This preserves row-level provenance and emits schema-version metadata."
        )
    )
    parser.add_argument(
        "--input-csv",
        default=str(PROCESSED_DATA_DIR / "reliability" / "realtime_events_normalized.csv"),
        help="Normalized realtime event CSV produced by src/reliability/normalize_realtime.py",
    )
    parser.add_argument(
        "--output-root",
        default=str(PROCESSED_DATA_DIR / "reliability"),
        help="Directory where parquet warehouse tables are written",
    )
    parser.add_argument(
        "--events-table-name",
        default="realtime_events.parquet",
        help="Filename for canonical row-level warehouse table",
    )
    parser.add_argument(
        "--provenance-table-name",
        default="realtime_event_provenance.parquet",
        help="Filename for source-manifest/raw-file provenance table",
    )
    parser.add_argument(
        "--service-summary-table-name",
        default="realtime_service_summary.parquet",
        help="Filename for service_date x route x feed summary table",
    )
    parser.add_argument(
        "--metadata-json",
        default=str(PROCESSED_DATA_DIR / "reliability" / "realtime_warehouse_metadata.json"),
        help="Output JSON containing schema version, table schemas, and row counts",
    )
    parser.add_argument(
        "--schema-version",
        default=SCHEMA_VERSION,
        help="Schema version string written into metadata JSON",
    )
    parser.add_argument(
        "--parquet-engine",
        default="pyarrow",
        help="Parquet engine (pyarrow only in this pipeline)",
    )
    return parser.parse_args()


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def iso_utc(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def require_parquet_engine(engine: str) -> None:
    if engine != "pyarrow":
        raise ValueError(
            f"Unsupported parquet engine '{engine}'. "
            "Use --parquet-engine pyarrow for deterministic reproducibility."
        )
    try:
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing dependency for parquet persistence. Install requirements with "
            "`pip install -r requirements.txt`."
        ) from exc


def normalize_object_columns(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    for column in cleaned.columns:
        if cleaned[column].dtype != object:
            continue
        series = cleaned[column].where(cleaned[column].notna(), pd.NA)
        series = series.map(lambda value: value.strip() if isinstance(value, str) else value)
        series = series.replace("", pd.NA)
        cleaned[column] = series
    return cleaned


def validate_input_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            "Input normalized CSV is missing required columns for warehouse build: "
            f"{missing}"
        )


def parse_service_date(frame: pd.DataFrame) -> pd.Series:
    parsed = pd.to_datetime(frame["service_date"], format="%Y-%m-%d", errors="coerce")
    formatted = parsed.dt.strftime("%Y-%m-%d")
    return formatted.where(parsed.notna(), pd.NA)


def parse_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    typed = frame.copy()
    for column in TIMESTAMP_COLUMNS:
        if column not in typed.columns:
            typed[column] = pd.NaT
            continue
        typed[column] = pd.to_datetime(typed[column], utc=True, errors="coerce")
    return typed


def parse_numeric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    typed = frame.copy()
    for column in INT_COLUMNS:
        if column not in typed.columns:
            typed[column] = pd.Series(pd.NA, index=typed.index, dtype="Int64")
            continue
        typed[column] = pd.to_numeric(typed[column], errors="coerce").astype("Int64")
    for column in FLOAT_COLUMNS:
        if column not in typed.columns:
            typed[column] = pd.Series(pd.NA, index=typed.index, dtype="float64")
            continue
        typed[column] = pd.to_numeric(typed[column], errors="coerce")
    return typed


def build_events_table(normalized_events: pd.DataFrame) -> pd.DataFrame:
    events = normalized_events.copy()
    events["event_date"] = events["event_ts"].dt.strftime("%Y-%m-%d")
    events["event_date"] = events["event_date"].where(events["event_ts"].notna(), pd.NA)
    events["capture_date"] = events["capture_ts"].dt.strftime("%Y-%m-%d")
    events["capture_date"] = events["capture_date"].where(events["capture_ts"].notna(), pd.NA)

    output_columns = [column for column in NORMALIZED_COLUMNS if column in events.columns]
    output_columns.extend(["event_date", "capture_date"])
    return events[output_columns]


def build_provenance_table(events: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "feed",
        "capture_ts",
        "source_manifest",
        "source_raw_file",
        "source_url",
        "source_sha256",
    ]
    grouped = (
        events.groupby(group_columns, dropna=False)
        .agg(
            rows=("entity_id", "size"),
            event_ts_min=("event_ts", "min"),
            event_ts_max=("event_ts", "max"),
            service_date_min=("service_date", "min"),
            service_date_max=("service_date", "max"),
        )
        .reset_index()
    )
    return grouped.sort_values(["capture_ts", "feed", "source_raw_file"], na_position="last")


def build_service_summary_table(events: pd.DataFrame) -> pd.DataFrame:
    group_columns = ["service_date", "feed", "route_id", "direction_id", "event_role"]
    summary = (
        events.groupby(group_columns, dropna=False)
        .agg(
            event_rows=("entity_id", "size"),
            unique_trips=("trip_id", lambda series: int(series.dropna().nunique())),
            unique_stops=("stop_id", lambda series: int(series.dropna().nunique())),
            unique_vehicles=("vehicle_id", lambda series: int(series.dropna().nunique())),
            event_ts_min=("event_ts", "min"),
            event_ts_max=("event_ts", "max"),
        )
        .reset_index()
    )
    return summary.sort_values(
        ["service_date", "feed", "route_id", "direction_id", "event_role"],
        na_position="last",
    )


def table_schema(frame: pd.DataFrame) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    for column in frame.columns:
        schema.append(
            {
                "name": column,
                "dtype": str(frame[column].dtype),
                "nullable": bool(frame[column].isna().any()),
            }
        )
    return schema


def build_metadata(
    *,
    schema_version: str,
    parquet_engine: str,
    input_csv: Path,
    events: pd.DataFrame,
    provenance: pd.DataFrame,
    service_summary: pd.DataFrame,
    events_path: Path,
    provenance_path: Path,
    service_summary_path: Path,
) -> dict[str, Any]:
    row_count = len(events)
    provenance_coverage = {
        column: {
            "non_null_rows": int(events[column].notna().sum()),
            "coverage_ratio": float(events[column].notna().sum() / row_count) if row_count else 0.0,
        }
        for column in PROVENANCE_COLUMNS
    }

    return {
        "schema_version": schema_version,
        "generated_at": iso_utc(datetime.now(tz=timezone.utc)),
        "input_normalized_csv": str(input_csv),
        "parquet_engine": parquet_engine,
        "required_input_columns": REQUIRED_COLUMNS,
        "tables": {
            "events": {
                "path": str(events_path),
                "rows": int(len(events)),
                "schema": table_schema(events),
            },
            "provenance": {
                "path": str(provenance_path),
                "rows": int(len(provenance)),
                "schema": table_schema(provenance),
            },
            "service_summary": {
                "path": str(service_summary_path),
                "rows": int(len(service_summary)),
                "schema": table_schema(service_summary),
            },
        },
        "provenance_coverage": provenance_coverage,
    }


def write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2, sort_keys=True)


def main() -> None:
    args = parse_args()
    ensure_data_dirs()
    require_parquet_engine(args.parquet_engine)

    input_csv = resolve_project_path(args.input_csv)
    output_root = resolve_project_path(args.output_root)
    metadata_json = resolve_project_path(args.metadata_json)

    if not input_csv.exists():
        raise FileNotFoundError(
            f"Normalized realtime CSV not found: {input_csv}. "
            "Run src/reliability/normalize_realtime.py first."
        )

    output_root.mkdir(parents=True, exist_ok=True)
    events_path = output_root / args.events_table_name
    provenance_path = output_root / args.provenance_table_name
    service_summary_path = output_root / args.service_summary_table_name

    normalized_events = pd.read_csv(input_csv, dtype=str)
    validate_input_columns(normalized_events)
    normalized_events = normalize_object_columns(normalized_events)
    normalized_events["service_date"] = parse_service_date(normalized_events)
    normalized_events = parse_timestamps(normalized_events)
    normalized_events = parse_numeric_columns(normalized_events)

    events = build_events_table(normalized_events)
    if len(events) != len(normalized_events):
        raise ValueError(
            "Warehouse event-row count mismatch: output rows differ from normalized input rows."
        )

    provenance = build_provenance_table(events)
    service_summary = build_service_summary_table(events)

    events.to_parquet(events_path, engine=args.parquet_engine, index=False)
    provenance.to_parquet(provenance_path, engine=args.parquet_engine, index=False)
    service_summary.to_parquet(service_summary_path, engine=args.parquet_engine, index=False)

    metadata = build_metadata(
        schema_version=args.schema_version,
        parquet_engine=args.parquet_engine,
        input_csv=input_csv,
        events=events,
        provenance=provenance,
        service_summary=service_summary,
        events_path=events_path,
        provenance_path=provenance_path,
        service_summary_path=service_summary_path,
    )
    write_metadata(metadata_json, metadata)

    print(f"Wrote warehouse events table: {events_path} ({len(events)} rows)")
    print(f"Wrote warehouse provenance table: {provenance_path} ({len(provenance)} rows)")
    print(
        "Wrote warehouse service summary table: "
        f"{service_summary_path} ({len(service_summary)} rows)"
    )
    print(f"Wrote warehouse metadata: {metadata_json}")


if __name__ == "__main__":
    main()

