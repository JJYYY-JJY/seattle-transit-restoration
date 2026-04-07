from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import RAW_DATA_DIR, ensure_data_dirs


@dataclass(frozen=True)
class FeedEndpoint:
    name: str
    url: str


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_utc(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def station_day_key(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d")


def timestamp_stem(timestamp: datetime) -> str:
    return timestamp.strftime("%H%M%S_%fZ")


def sanitize_url(raw_url: str) -> str:
    parts = urlsplit(raw_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_headers(
    api_key: str,
    api_key_header: str,
    bearer_token: str,
) -> dict[str, str]:
    headers = {
        "Accept": "application/x-protobuf, application/octet-stream;q=0.9, */*;q=0.1",
        "User-Agent": "seattle-transit-restoration-gtfsrt/1.0",
    }
    if api_key and api_key_header:
        headers[api_key_header] = api_key
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2, sort_keys=True)


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(payload)


def fetch_single_feed(
    session: requests.Session,
    endpoint: FeedEndpoint,
    headers: dict[str, str],
    timeout_seconds: int,
    output_root: Path,
    run_ts: datetime,
) -> dict[str, Any]:
    response = session.get(endpoint.url, headers=headers, timeout=timeout_seconds)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} returned for {endpoint.name}")

    payload = response.content
    if not payload:
        raise RuntimeError(f"Empty payload returned for {endpoint.name}")

    day_key = station_day_key(run_ts)
    stem = timestamp_stem(run_ts)
    raw_file = output_root / day_key / endpoint.name / f"{stem}.pb"
    meta_file = output_root / day_key / "_meta" / f"{stem}_{endpoint.name}.json"

    write_bytes(raw_file, payload)
    digest = hashlib.sha256(payload).hexdigest()

    metadata = {
        "captured_at": iso_utc(run_ts),
        "feed": endpoint.name,
        "url": sanitize_url(endpoint.url),
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "content_length_bytes": len(payload),
        "sha256": digest,
        "raw_file": str(raw_file),
    }
    write_json(meta_file, metadata)
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture one GTFS-RT snapshot for TripUpdates, VehiclePositions, and ServiceAlerts."
        )
    )
    parser.add_argument("--trip-updates-url", default=os.getenv("GTFSRT_TRIP_UPDATES_URL", ""))
    parser.add_argument("--vehicle-positions-url", default=os.getenv("GTFSRT_VEHICLE_POSITIONS_URL", ""))
    parser.add_argument("--alerts-url", default=os.getenv("GTFSRT_ALERTS_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("GTFSRT_API_KEY", ""))
    parser.add_argument(
        "--api-key-header",
        default=os.getenv("GTFSRT_API_KEY_HEADER", "x-api-key"),
        help="Header name used for GTFS-RT API key when --api-key is provided",
    )
    parser.add_argument(
        "--bearer-token",
        default=os.getenv("GTFSRT_BEARER_TOKEN", ""),
        help="Optional bearer token for GTFS-RT requests",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.getenv("GTFSRT_TIMEOUT_SECONDS", "30")),
    )
    parser.add_argument(
        "--output-root",
        default=str(RAW_DATA_DIR / "gtfs_rt"),
        help="Directory where raw GTFS-RT payloads and metadata are written",
    )
    parser.add_argument(
        "--allow-empty-config",
        action="store_true",
        help="Exit successfully when no GTFS-RT URLs are configured",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_data_dirs()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    endpoints: list[FeedEndpoint] = []
    if args.trip_updates_url.strip():
        endpoints.append(FeedEndpoint(name="trip_updates", url=args.trip_updates_url.strip()))
    if args.vehicle_positions_url.strip():
        endpoints.append(FeedEndpoint(name="vehicle_positions", url=args.vehicle_positions_url.strip()))
    if args.alerts_url.strip():
        endpoints.append(FeedEndpoint(name="service_alerts", url=args.alerts_url.strip()))

    if not endpoints:
        if args.allow_empty_config:
            print("No GTFS-RT endpoints configured, skipping snapshot.")
            return
        raise RuntimeError(
            "No GTFS-RT endpoints configured. Set GTFSRT_TRIP_UPDATES_URL, "
            "GTFSRT_VEHICLE_POSITIONS_URL, or GTFSRT_ALERTS_URL."
        )

    headers = build_headers(
        api_key=args.api_key,
        api_key_header=args.api_key_header,
        bearer_token=args.bearer_token,
    )
    run_ts = utc_now()

    successes: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    with requests.Session() as session:
        for endpoint in endpoints:
            try:
                item = fetch_single_feed(
                    session=session,
                    endpoint=endpoint,
                    headers=headers,
                    timeout_seconds=args.timeout_seconds,
                    output_root=output_root,
                    run_ts=run_ts,
                )
                successes.append(item)
                print(
                    f"Captured {endpoint.name}: {item['content_length_bytes']} bytes "
                    f"sha256={item['sha256'][:12]}..."
                )
            except Exception as exc:  # noqa: BLE001
                failures.append({"feed": endpoint.name, "error": str(exc)})
                print(f"Failed {endpoint.name}: {exc}")

    run_manifest = {
        "captured_at": iso_utc(run_ts),
        "feeds_attempted": [endpoint.name for endpoint in endpoints],
        "successful": successes,
        "failed": failures,
    }
    manifest_file = (
        output_root
        / "manifests"
        / station_day_key(run_ts)
        / f"run_{timestamp_stem(run_ts)}.json"
    )
    write_json(manifest_file, run_manifest)
    print(f"Wrote run manifest: {manifest_file}")

    if not successes:
        raise RuntimeError("All GTFS-RT endpoints failed in this snapshot run")


if __name__ == "__main__":
    main()
