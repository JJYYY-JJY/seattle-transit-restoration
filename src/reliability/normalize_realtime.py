from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import PROCESSED_DATA_DIR, PROJECT_ROOT, RAW_DATA_DIR, ensure_data_dirs

OUTPUT_COLUMNS = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize GTFS-RT snapshots from raw manifests into canonical event rows "
            "with keys service_date, route_id, direction_id, trip_id, stop_id, event_ts."
        )
    )
    parser.add_argument(
        "--input-root",
        default=str(RAW_DATA_DIR / "gtfs_rt"),
        help="Root directory containing GTFS-RT manifests and raw protobuf payloads",
    )
    parser.add_argument(
        "--manifest-glob",
        default="manifests/*/run_*.json",
        help="Glob pattern (relative to --input-root) for run manifests",
    )
    parser.add_argument(
        "--output-csv",
        default=str(PROCESSED_DATA_DIR / "reliability" / "realtime_events_normalized.csv"),
        help="Output normalized events CSV path",
    )
    parser.add_argument(
        "--summary-json",
        default=str(PROCESSED_DATA_DIR / "reliability" / "realtime_normalization_summary.json"),
        help="Output normalization summary JSON path",
    )
    parser.add_argument(
        "--max-manifests",
        type=int,
        default=0,
        help="Optional cap on number of manifest files to process (0 = all)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional cap on total raw protobuf files to process (0 = all)",
    )
    parser.add_argument(
        "--allow-missing-raw-files",
        action="store_true",
        help="Skip manifest rows whose raw_file path is missing instead of failing",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue after parse errors and record them in summary JSON",
    )
    return parser.parse_args()


def resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_gtfs_realtime_pb2() -> Any:
    try:
        from google.transit import gtfs_realtime_pb2  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing dependency for GTFS-RT protobuf decoding. "
            "Install requirements with: pip install -r requirements.txt"
        ) from exc
    return gtfs_realtime_pb2


def parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_utc(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        epoch = int(value)
    except (TypeError, ValueError):
        return None
    if epoch <= 0:
        return None
    return iso_utc(datetime.fromtimestamp(epoch, tz=timezone.utc))


def normalize_service_date(raw: Any) -> str | None:
    if raw is None:
        return None
    token = str(raw).strip()
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return None


def service_date_from_iso(value: str | None) -> str | None:
    if not value:
        return None
    return parse_iso_utc(value).strftime("%Y-%m-%d")


def clean_text(raw: Any) -> str | None:
    if raw is None:
        return None
    token = str(raw).strip()
    if token == "":
        return None
    return token


def proto_has_field(message: Any, field_name: str) -> bool:
    try:
        return bool(message.HasField(field_name))
    except ValueError:
        return False


def enum_name(enum_cls: Any, raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        return str(enum_cls.Name(int(raw)))
    except Exception:  # noqa: BLE001
        try:
            return str(int(raw))
        except Exception:  # noqa: BLE001
            return None


def load_manifest_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be a JSON object: {path}")
    return payload


def iter_manifest_paths(input_root: Path, manifest_glob: str, max_manifests: int) -> list[Path]:
    manifests = sorted(input_root.glob(manifest_glob))
    if max_manifests > 0:
        manifests = manifests[:max_manifests]
    if not manifests:
        raise FileNotFoundError(
            f"No manifest files found under {input_root} matching '{manifest_glob}'"
        )
    return manifests


def manifest_success_entries(
    manifest_path: Path,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    capture_ts = clean_text(payload.get("captured_at"))
    successful = payload.get("successful", [])
    if not isinstance(successful, list):
        raise ValueError(f"'successful' must be a list in manifest {manifest_path}")

    rows: list[dict[str, Any]] = []
    for item in successful:
        if not isinstance(item, dict):
            continue
        feed = clean_text(item.get("feed"))
        raw_file = clean_text(item.get("raw_file"))
        if not feed or not raw_file:
            continue
        rows.append(
            {
                "manifest_path": manifest_path,
                "capture_ts": capture_ts,
                "feed": feed,
                "raw_file": raw_file,
                "url": clean_text(item.get("url")),
                "sha256": clean_text(item.get("sha256")),
            }
        )
    return rows


def resolve_raw_file(raw_file: str) -> Path:
    path = Path(raw_file)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def parse_stop_event_time(stop_event: Any) -> tuple[str | None, int | None]:
    event_ts = None
    delay_seconds = None
    if proto_has_field(stop_event, "time"):
        event_ts = epoch_to_iso(stop_event.time)
    if proto_has_field(stop_event, "delay"):
        delay_seconds = int(stop_event.delay)
    return event_ts, delay_seconds


def parse_trip_updates_rows(
    gtfs_realtime_pb2: Any,
    feed_message: Any,
    base_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header_ts = epoch_to_iso(feed_message.header.timestamp) if proto_has_field(feed_message.header, "timestamp") else None

    for entity in feed_message.entity:
        if not proto_has_field(entity, "trip_update"):
            continue
        trip_update = entity.trip_update
        trip = trip_update.trip

        trip_update_ts = epoch_to_iso(trip_update.timestamp) if proto_has_field(trip_update, "timestamp") else None
        service_date = normalize_service_date(trip.start_date)
        route_id = clean_text(trip.route_id)
        direction_id = str(trip.direction_id) if proto_has_field(trip, "direction_id") else None
        trip_id = clean_text(trip.trip_id)
        vehicle_id = clean_text(trip_update.vehicle.id) if proto_has_field(trip_update, "vehicle") else None
        schedule_relationship = enum_name(
            gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship,
            trip.schedule_relationship if proto_has_field(trip, "schedule_relationship") else None,
        )

        stop_updates = list(trip_update.stop_time_update)
        if stop_updates:
            for stop_update in stop_updates:
                arrival_ts, arrival_delay = parse_stop_event_time(stop_update.arrival)
                departure_ts, departure_delay = parse_stop_event_time(stop_update.departure)
                event_ts = (
                    arrival_ts
                    or departure_ts
                    or trip_update_ts
                    or header_ts
                    or base_meta["capture_ts"]
                )
                row = {
                    **base_meta,
                    "header_ts": header_ts,
                    "event_role": "trip_update_stop_time",
                    "entity_id": clean_text(entity.id),
                    "service_date": service_date or service_date_from_iso(event_ts),
                    "route_id": route_id,
                    "direction_id": direction_id,
                    "trip_id": trip_id,
                    "stop_id": clean_text(stop_update.stop_id),
                    "event_ts": event_ts,
                    "stop_sequence": int(stop_update.stop_sequence) if proto_has_field(stop_update, "stop_sequence") else None,
                    "delay_seconds": arrival_delay if arrival_delay is not None else departure_delay,
                    "schedule_relationship": schedule_relationship,
                    "vehicle_id": vehicle_id,
                }
                rows.append(row)
            continue

        event_ts = trip_update_ts or header_ts or base_meta["capture_ts"]
        rows.append(
            {
                **base_meta,
                "header_ts": header_ts,
                "event_role": "trip_update",
                "entity_id": clean_text(entity.id),
                "service_date": service_date or service_date_from_iso(event_ts),
                "route_id": route_id,
                "direction_id": direction_id,
                "trip_id": trip_id,
                "stop_id": None,
                "event_ts": event_ts,
                "stop_sequence": None,
                "delay_seconds": None,
                "schedule_relationship": schedule_relationship,
                "vehicle_id": vehicle_id,
            }
        )

    return rows


def parse_vehicle_position_rows(
    gtfs_realtime_pb2: Any,
    feed_message: Any,
    base_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header_ts = epoch_to_iso(feed_message.header.timestamp) if proto_has_field(feed_message.header, "timestamp") else None

    for entity in feed_message.entity:
        if not proto_has_field(entity, "vehicle"):
            continue
        vehicle = entity.vehicle
        trip = vehicle.trip

        vehicle_ts = epoch_to_iso(vehicle.timestamp) if proto_has_field(vehicle, "timestamp") else None
        event_ts = vehicle_ts or header_ts or base_meta["capture_ts"]
        route_id = clean_text(trip.route_id)
        direction_id = str(trip.direction_id) if proto_has_field(trip, "direction_id") else None
        trip_id = clean_text(trip.trip_id)
        service_date = normalize_service_date(trip.start_date) or service_date_from_iso(event_ts)
        latitude = float(vehicle.position.latitude) if proto_has_field(vehicle, "position") and proto_has_field(vehicle.position, "latitude") else None
        longitude = float(vehicle.position.longitude) if proto_has_field(vehicle, "position") and proto_has_field(vehicle.position, "longitude") else None

        rows.append(
            {
                **base_meta,
                "header_ts": header_ts,
                "event_role": "vehicle_position",
                "entity_id": clean_text(entity.id),
                "service_date": service_date,
                "route_id": route_id,
                "direction_id": direction_id,
                "trip_id": trip_id,
                "stop_id": clean_text(vehicle.stop_id),
                "event_ts": event_ts,
                "stop_sequence": int(vehicle.current_stop_sequence) if proto_has_field(vehicle, "current_stop_sequence") else None,
                "delay_seconds": None,
                "schedule_relationship": enum_name(
                    gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship,
                    trip.schedule_relationship if proto_has_field(trip, "schedule_relationship") else None,
                ),
                "vehicle_id": clean_text(vehicle.vehicle.id) if proto_has_field(vehicle, "vehicle") else None,
                "latitude": latitude,
                "longitude": longitude,
                "current_status": enum_name(
                    gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus,
                    vehicle.current_status if proto_has_field(vehicle, "current_status") else None,
                ),
                "occupancy_status": enum_name(
                    gtfs_realtime_pb2.VehiclePosition.OccupancyStatus,
                    vehicle.occupancy_status if proto_has_field(vehicle, "occupancy_status") else None,
                ),
            }
        )

    return rows


def parse_service_alert_rows(
    gtfs_realtime_pb2: Any,
    feed_message: Any,
    base_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header_ts = epoch_to_iso(feed_message.header.timestamp) if proto_has_field(feed_message.header, "timestamp") else None

    for entity in feed_message.entity:
        if not proto_has_field(entity, "alert"):
            continue
        alert = entity.alert
        alert_cause = enum_name(
            gtfs_realtime_pb2.Alert.Cause,
            alert.cause if proto_has_field(alert, "cause") else None,
        )
        alert_effect = enum_name(
            gtfs_realtime_pb2.Alert.Effect,
            alert.effect if proto_has_field(alert, "effect") else None,
        )

        active_start = None
        if alert.active_period:
            first_period = alert.active_period[0]
            if proto_has_field(first_period, "start"):
                active_start = epoch_to_iso(first_period.start)

        informed_entities = list(alert.informed_entity)
        if not informed_entities:
            event_ts = active_start or header_ts or base_meta["capture_ts"]
            rows.append(
                {
                    **base_meta,
                    "header_ts": header_ts,
                    "event_role": "service_alert",
                    "entity_id": clean_text(entity.id),
                    "service_date": service_date_from_iso(event_ts),
                    "route_id": None,
                    "direction_id": None,
                    "trip_id": None,
                    "stop_id": None,
                    "event_ts": event_ts,
                    "alert_cause": alert_cause,
                    "alert_effect": alert_effect,
                }
            )
            continue

        for informed in informed_entities:
            direction_id = str(informed.direction_id) if proto_has_field(informed, "direction_id") else None
            trip_id = None
            service_date = None
            if proto_has_field(informed, "trip"):
                trip_id = clean_text(informed.trip.trip_id)
                service_date = normalize_service_date(informed.trip.start_date)
                if direction_id is None and proto_has_field(informed.trip, "direction_id"):
                    direction_id = str(informed.trip.direction_id)

            event_ts = active_start or header_ts or base_meta["capture_ts"]
            rows.append(
                {
                    **base_meta,
                    "header_ts": header_ts,
                    "event_role": "service_alert_informed_entity",
                    "entity_id": clean_text(entity.id),
                    "service_date": service_date or service_date_from_iso(event_ts),
                    "route_id": clean_text(informed.route_id),
                    "direction_id": direction_id,
                    "trip_id": trip_id,
                    "stop_id": clean_text(informed.stop_id),
                    "event_ts": event_ts,
                    "alert_cause": alert_cause,
                    "alert_effect": alert_effect,
                }
            )

    return rows


def parse_rows_for_feed(
    gtfs_realtime_pb2: Any,
    feed_name: str,
    feed_message: Any,
    base_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    if feed_name == "trip_updates":
        return parse_trip_updates_rows(gtfs_realtime_pb2, feed_message, base_meta)
    if feed_name == "vehicle_positions":
        return parse_vehicle_position_rows(gtfs_realtime_pb2, feed_message, base_meta)
    if feed_name == "service_alerts":
        return parse_service_alert_rows(gtfs_realtime_pb2, feed_message, base_meta)
    return []


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2, sort_keys=True)


def main() -> None:
    args = parse_args()
    ensure_data_dirs()
    gtfs_realtime_pb2 = load_gtfs_realtime_pb2()

    input_root = resolve_project_path(args.input_root)
    output_csv = resolve_project_path(args.output_csv)
    summary_json = resolve_project_path(args.summary_json)

    manifest_paths = iter_manifest_paths(
        input_root=input_root,
        manifest_glob=args.manifest_glob,
        max_manifests=args.max_manifests,
    )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "input_root": str(input_root),
        "manifest_glob": args.manifest_glob,
        "manifest_count": len(manifest_paths),
        "raw_files_seen": 0,
        "raw_files_processed": 0,
        "raw_files_missing": 0,
        "raw_files_failed": 0,
        "rows_written": 0,
        "feeds": {
            "trip_updates": {"files": 0, "rows": 0},
            "vehicle_positions": {"files": 0, "rows": 0},
            "service_alerts": {"files": 0, "rows": 0},
        },
        "errors": [],
        "generated_at": iso_utc(datetime.now(tz=timezone.utc)),
    }

    files_processed = 0

    with output_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for manifest_path in manifest_paths:
            payload = load_manifest_payload(manifest_path)
            entries = manifest_success_entries(manifest_path, payload)

            for entry in entries:
                if args.max_files > 0 and files_processed >= args.max_files:
                    break

                summary["raw_files_seen"] = int(summary["raw_files_seen"]) + 1

                raw_path = resolve_raw_file(str(entry["raw_file"]))
                if not raw_path.exists():
                    summary["raw_files_missing"] = int(summary["raw_files_missing"]) + 1
                    missing_message = f"Missing raw file referenced by manifest: {raw_path}"
                    if args.allow_missing_raw_files:
                        summary["errors"].append(
                            {
                                "type": "missing_raw_file",
                                "manifest": str(manifest_path),
                                "raw_file": str(raw_path),
                            }
                        )
                        continue
                    raise FileNotFoundError(missing_message)

                feed_name = str(entry["feed"])
                base_meta = {
                    "feed": feed_name,
                    "capture_ts": str(entry["capture_ts"] or ""),
                    "source_manifest": str(manifest_path),
                    "source_raw_file": str(raw_path),
                    "source_url": entry["url"],
                    "source_sha256": entry["sha256"],
                }

                try:
                    feed_message = gtfs_realtime_pb2.FeedMessage()
                    feed_message.ParseFromString(raw_path.read_bytes())
                    rows = parse_rows_for_feed(
                        gtfs_realtime_pb2=gtfs_realtime_pb2,
                        feed_name=feed_name,
                        feed_message=feed_message,
                        base_meta=base_meta,
                    )
                except Exception as exc:  # noqa: BLE001
                    summary["raw_files_failed"] = int(summary["raw_files_failed"]) + 1
                    if args.continue_on_error:
                        summary["errors"].append(
                            {
                                "type": "parse_error",
                                "manifest": str(manifest_path),
                                "raw_file": str(raw_path),
                                "feed": feed_name,
                                "error": str(exc),
                            }
                        )
                        continue
                    raise

                for row in rows:
                    writer.writerow({column: row.get(column) for column in OUTPUT_COLUMNS})

                files_processed += 1
                summary["raw_files_processed"] = int(summary["raw_files_processed"]) + 1
                summary["rows_written"] = int(summary["rows_written"]) + len(rows)

                if feed_name in summary["feeds"]:
                    summary["feeds"][feed_name]["files"] = int(summary["feeds"][feed_name]["files"]) + 1
                    summary["feeds"][feed_name]["rows"] = int(summary["feeds"][feed_name]["rows"]) + len(rows)

            if args.max_files > 0 and files_processed >= args.max_files:
                break

    write_summary(summary_json, summary)
    print(f"Wrote normalized realtime CSV: {output_csv}")
    print(f"Wrote normalization summary: {summary_json}")
    print(
        "Processed "
        f"{summary['raw_files_processed']} raw files, "
        f"wrote {summary['rows_written']} rows."
    )


if __name__ == "__main__":
    main()

