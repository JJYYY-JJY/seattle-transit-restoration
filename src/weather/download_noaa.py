from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import NOAA_CDO_API_BASE, NOAA_RAW_DIR, NOAA_STATION_ID, NOAA_TOKEN, ensure_data_dirs


def station_safe_name(station_id: str) -> str:
    return station_id.replace(":", "_")


def parse_datatypes(raw: str) -> list[str]:
    normalized = raw.replace(",", " ").strip()
    return [item for item in normalized.split() if item]


def fetch_station_metadata(session: requests.Session, token: str, station_id: str) -> dict[str, Any]:
    url = f"{NOAA_CDO_API_BASE}/stations/{station_id}"
    response = session.get(url, headers={"token": token}, timeout=120)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return payload


def fetch_noaa_datatype(
    session: requests.Session,
    token: str,
    station_id: str,
    datatype: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    url = f"{NOAA_CDO_API_BASE}/data"
    limit = 1000
    rows: list[dict[str, Any]] = []

    window_start = date.fromisoformat(start_date)
    full_end = date.fromisoformat(end_date)

    while window_start <= full_end:
        window_end = min(window_start + timedelta(days=364), full_end)
        offset = 1
        window_rows = 0

        while True:
            params = {
                "datasetid": "GHCND",
                "stationid": station_id,
                "datatypeid": datatype,
                "startdate": window_start.isoformat(),
                "enddate": window_end.isoformat(),
                "units": "metric",
                "limit": limit,
                "offset": offset,
            }
            response = session.get(url, headers={"token": token}, params=params, timeout=120)
            response.raise_for_status()
            payload = response.json()

            chunk = payload.get("results", [])
            if not isinstance(chunk, list):
                raise RuntimeError(f"NOAA returned invalid results payload for datatype {datatype}")
            rows.extend(chunk)
            window_rows += len(chunk)

            resultset = payload.get("metadata", {}).get("resultset", {})
            total = int(resultset.get("count", window_rows))
            if not chunk or window_rows >= total:
                break
            offset += len(chunk)

        window_start = window_end + timedelta(days=1)

    return rows


def load_local_datatype_rows(
    noaa_dir: Path,
    datatype: str,
    station_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    safe_station = station_safe_name(station_id)
    exact_file = noaa_dir / f"{datatype}_{start_date}_{end_date}_{safe_station}.json"

    if exact_file.exists():
        candidate = exact_file
    else:
        matches = sorted(noaa_dir.glob(f"{datatype}_*_{safe_station}.json"))
        if not matches:
            raise RuntimeError(
                f"No local NOAA json found for {datatype} and station {station_id}"
            )
        candidate = matches[-1]

    with candidate.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    raise RuntimeError(f"Invalid local NOAA payload format in {candidate}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def build_daily_weather_csv(
    datatype_rows: dict[str, list[dict[str, Any]]],
    output_csv: Path,
) -> None:
    long_rows: list[dict[str, Any]] = []
    for datatype, rows in datatype_rows.items():
        for row in rows:
            long_rows.append(
                {
                    "date": str(row.get("date", ""))[:10],
                    "datatype": datatype,
                    "value": row.get("value"),
                    "attributes": row.get("attributes", ""),
                    "station": row.get("station", ""),
                }
            )

    if not long_rows:
        raise RuntimeError("No NOAA rows collected, cannot build seattle_daily_weather.csv")

    frame = pd.DataFrame(long_rows)
    wide = frame.pivot_table(index="date", columns="datatype", values="value", aggfunc="first")
    wide = wide.reset_index().sort_values("date")

    # Keep a stable schema for downstream processors even when a datatype has no rows.
    required_columns = ["PRCP", "TMAX", "TMIN", "AWND"]
    for column in required_columns:
        if column not in wide.columns:
            wide[column] = pd.NA

    ordered = ["date", *required_columns]
    optional = [column for column in wide.columns if column not in ordered]
    wide = wide[ordered + optional]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    wide.to_csv(output_csv, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download NOAA daily weather data for Seattle station and consolidate to CSV"
    )
    parser.add_argument("--token", default=NOAA_TOKEN)
    parser.add_argument("--station-id", default=NOAA_STATION_ID)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--datatypes", default="PRCP,TMAX,TMIN,AWND")
    parser.add_argument(
        "--output-csv",
        default=str(NOAA_RAW_DIR / "seattle_daily_weather.csv"),
    )
    parser.add_argument(
        "--from-local-json",
        action="store_true",
        help="Skip NOAA API calls and build CSV from existing local JSON files",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    ensure_data_dirs()
    NOAA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    end_date = args.end_date or date.today().isoformat()
    start_date = args.start_date or (date.today() - timedelta(days=365 * 5)).isoformat()
    datatypes = parse_datatypes(args.datatypes)
    if not datatypes:
        raise RuntimeError("At least one NOAA datatype must be provided")

    safe_station = station_safe_name(args.station_id)
    use_local_json = args.from_local_json or not args.token
    if use_local_json and not args.from_local_json:
        print("NOAA token missing; falling back to local JSON mode.")

    datatype_rows: dict[str, list[dict[str, Any]]] = {}
    if use_local_json:
        station_file = NOAA_RAW_DIR / f"station_{safe_station}.json"
        if station_file.exists():
            print(f"Using existing station metadata: {station_file}")
        for datatype in datatypes:
            rows = load_local_datatype_rows(
                noaa_dir=NOAA_RAW_DIR,
                datatype=datatype,
                station_id=args.station_id,
                start_date=start_date,
                end_date=end_date,
            )
            datatype_rows[datatype] = rows
            print(f"Loaded local {datatype} observations: {len(rows)} rows")
    else:
        with requests.Session() as session:
            station_meta = fetch_station_metadata(
                session=session,
                token=args.token,
                station_id=args.station_id,
            )
            station_file = NOAA_RAW_DIR / f"station_{safe_station}.json"
            write_json(station_file, station_meta)
            print(f"Saved station metadata: {station_file}")

            for datatype in datatypes:
                rows = fetch_noaa_datatype(
                    session=session,
                    token=args.token,
                    station_id=args.station_id,
                    datatype=datatype,
                    start_date=start_date,
                    end_date=end_date,
                )
                datatype_rows[datatype] = rows

                datatype_file = NOAA_RAW_DIR / f"{datatype}_{start_date}_{end_date}_{safe_station}.json"
                write_json(
                    datatype_file,
                    {
                        "metadata": {
                            "station_id": args.station_id,
                            "datatype": datatype,
                            "start_date": start_date,
                            "end_date": end_date,
                            "count": len(rows),
                        },
                        "results": rows,
                    },
                )
                print(f"Saved {datatype} observations: {datatype_file}")

    output_csv = Path(args.output_csv)
    build_daily_weather_csv(datatype_rows=datatype_rows, output_csv=output_csv)
    print(f"Saved consolidated daily weather CSV: {output_csv}")


if __name__ == "__main__":
    main()
