from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import (
    GTFS_ARCHIVE_DIR,
    PROCESSED_DATA_DIR,
    PROJECT_ROOT,
    TRANSITLAND_API_BASE,
    TRANSITLAND_API_KEY,
    TRANSITLAND_FEED_ID,
    ensure_data_dirs,
)


ESSENTIAL_GTFS_FILES = {
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
}

MANIFEST_COLUMNS = ["version_id", "date_start", "date_end", "sha1", "file_path"]


def parse_any_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    try:
        if "T" in raw_value:
            return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).date()
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def version_date(version: dict[str, Any]) -> date | None:
    return parse_any_date(version.get("earliest_calendar_date")) or parse_any_date(
        version.get("fetched_at")
    )


def quarter_key(day: date) -> tuple[int, int]:
    return day.year, ((day.month - 1) // 3) + 1


def safe_relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def find_latest_cached_versions_json(feed_id: str) -> Path | None:
    pattern = re.compile(rf"^transitland_{re.escape(feed_id)}_feed_versions_\d{{4}}-\d{{2}}-\d{{2}}\.json$")
    candidates = [p for p in GTFS_ARCHIVE_DIR.glob("transitland_*_feed_versions_*.json") if pattern.match(p.name)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def load_versions_from_json(json_path: Path) -> list[dict[str, Any]]:
    with json_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    versions = payload.get("feed_versions", [])
    if not isinstance(versions, list):
        raise RuntimeError(f"Invalid Transitland versions payload in {json_path}")
    return versions


def fetch_versions_from_api(
    api_key: str,
    feed_id: str,
    page_size: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    url = f"{TRANSITLAND_API_BASE}/feeds/{feed_id}/feed_versions"
    params: dict[str, Any] | None = {"apikey": api_key, "limit": page_size}
    all_versions: list[dict[str, Any]] = []

    with requests.Session() as session:
        for _ in range(max_pages):
            response = session.get(url, params=params, timeout=120)
            response.raise_for_status()
            payload = response.json()

            page_versions = payload.get("feed_versions", [])
            if not isinstance(page_versions, list):
                raise RuntimeError("Transitland API returned invalid feed_versions payload")
            all_versions.extend(page_versions)

            next_url = payload.get("meta", {}).get("next")
            if not next_url:
                break
            url = next_url
            params = None

    if not all_versions:
        raise RuntimeError("Transitland returned zero feed versions")
    return all_versions


def write_versions_cache(feed_id: str, versions: list[dict[str, Any]]) -> Path:
    stamp = date.today().isoformat()
    out_path = GTFS_ARCHIVE_DIR / f"transitland_{feed_id}_feed_versions_{stamp}.json"
    payload = {"feed_versions": versions}
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return out_path


def filter_by_lookback(versions: list[dict[str, Any]], lookback_years: int) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=365 * lookback_years)
    filtered = [v for v in versions if (d := version_date(v)) is not None and d >= cutoff]
    return filtered if filtered else versions


def sample_quarterly(versions: list[dict[str, Any]], target_versions: int) -> list[dict[str, Any]]:
    sorted_versions = sorted(
        versions,
        key=lambda v: (
            version_date(v) or date.min,
            int(v.get("id", 0)),
        ),
    )

    per_quarter: dict[tuple[int, int], dict[str, Any]] = {}
    for version in sorted_versions:
        vdate = version_date(version)
        if vdate is None:
            continue
        per_quarter[quarter_key(vdate)] = version

    sampled = [per_quarter[key] for key in sorted(per_quarter)]
    if len(sampled) <= target_versions:
        return sampled
    if target_versions <= 1:
        return [sampled[-1]]

    # Downsample evenly over the time-ordered quarterly list.
    step = (len(sampled) - 1) / (target_versions - 1)
    indices = sorted({round(i * step) for i in range(target_versions)})
    return [sampled[idx] for idx in indices]


def expected_archive_name(version: dict[str, Any]) -> str:
    version_start = version.get("earliest_calendar_date")
    if not version_start:
        vdate = version_date(version)
        version_start = vdate.isoformat() if vdate else "unknown"
    sha1 = str(version.get("sha1") or f"id{version.get('id', 'unknown')}")
    return f"kcm_gtfs_{version_start}_{sha1}.zip"


def find_existing_zip_for_sha(sha1: str | None) -> Path | None:
    if not sha1:
        return None
    matches = sorted(GTFS_ARCHIVE_DIR.glob(f"*{sha1}*.zip"))
    if matches:
        return matches[0]
    return None


def download_feed_version_zip(session: requests.Session, api_key: str, sha1: str, output_path: Path) -> None:
    download_url = f"{TRANSITLAND_API_BASE}/feed_versions/{sha1}/download"
    with session.get(download_url, params={"apikey": api_key}, stream=True, timeout=240) as response:
        response.raise_for_status()
        with output_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    fh.write(chunk)


def validate_gtfs_zip(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = {
            Path(name).name
            for name in archive.namelist()
            if name and not name.endswith("/")
        }
    return sorted(ESSENTIAL_GTFS_FILES - members)


def write_manifest(rows: list[dict[str, str]], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download sampled historical GTFS feed versions from Transitland and "
            "build data/processed/feeds_manifest.csv"
        )
    )
    parser.add_argument("--feed-id", default=TRANSITLAND_FEED_ID)
    parser.add_argument("--api-key", default=TRANSITLAND_API_KEY)
    parser.add_argument("--lookback-years", type=int, default=5)
    parser.add_argument("--target-versions", type=int, default=12)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument(
        "--cached-versions-json",
        default="",
        help="Optional path to an existing feed_versions JSON file",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Only build manifest from already downloaded zips",
    )
    parser.add_argument(
        "--manifest-path",
        default=str(PROCESSED_DATA_DIR / "feeds_manifest.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_data_dirs()
    GTFS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    versions: list[dict[str, Any]]
    cache_source: str | None = None

    if args.cached_versions_json:
        cached_path = Path(args.cached_versions_json)
        versions = load_versions_from_json(cached_path)
        cache_source = safe_relpath(cached_path)
    elif args.api_key:
        versions = fetch_versions_from_api(
            api_key=args.api_key,
            feed_id=args.feed_id,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
        cache_path = write_versions_cache(feed_id=args.feed_id, versions=versions)
        cache_source = safe_relpath(cache_path)
    else:
        latest_cached = find_latest_cached_versions_json(feed_id=args.feed_id)
        if latest_cached is None:
            raise RuntimeError(
                "Transitland API key not provided and no cached feed_versions JSON found in data/raw/gtfs_archive"
            )
        versions = load_versions_from_json(latest_cached)
        cache_source = safe_relpath(latest_cached)

    filtered = filter_by_lookback(versions=versions, lookback_years=args.lookback_years)
    sampled = sample_quarterly(versions=filtered, target_versions=args.target_versions)
    if not sampled:
        raise RuntimeError("No sampled feed versions found after filtering")

    manifest_rows: list[dict[str, str]] = []
    warnings: list[str] = []

    with requests.Session() as session:
        for version in sampled:
            sha1 = str(version.get("sha1") or "")
            version_id = str(version.get("id") or "")
            date_start = str(version.get("earliest_calendar_date") or "")
            date_end = str(version.get("latest_calendar_date") or "")

            output_path = GTFS_ARCHIVE_DIR / expected_archive_name(version)
            existing_sha_match = find_existing_zip_for_sha(sha1)
            if existing_sha_match is not None:
                output_path = existing_sha_match

            if not output_path.exists() and not args.skip_download:
                if not args.api_key:
                    warnings.append(
                        f"Skipped download for version {version_id} ({sha1}): missing API key"
                    )
                elif not sha1:
                    warnings.append(f"Skipped version {version_id}: missing sha1 in metadata")
                else:
                    print(f"Downloading sampled version {version_id} ({sha1})")
                    try:
                        download_feed_version_zip(
                            session=session,
                            api_key=args.api_key,
                            sha1=sha1,
                            output_path=output_path,
                        )
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"Download failed for version {version_id} ({sha1}): {exc}")

            file_path = ""
            if output_path.exists():
                try:
                    missing = validate_gtfs_zip(output_path)
                    if missing:
                        warnings.append(
                            f"Validation warning for {output_path.name}: missing {', '.join(missing)}"
                        )
                    file_path = safe_relpath(output_path)
                except zipfile.BadZipFile:
                    warnings.append(f"Invalid zip archive: {output_path}")
                    if not args.skip_download and args.api_key and sha1:
                        try:
                            output_path.unlink(missing_ok=True)
                            download_feed_version_zip(
                                session=session,
                                api_key=args.api_key,
                                sha1=sha1,
                                output_path=output_path,
                            )
                            missing = validate_gtfs_zip(output_path)
                            if missing:
                                warnings.append(
                                    f"Validation warning after re-download for {output_path.name}: "
                                    f"missing {', '.join(missing)}"
                                )
                            file_path = safe_relpath(output_path)
                        except Exception as exc:  # noqa: BLE001
                            warnings.append(
                                f"Re-download failed for corrupted archive {output_path.name}: {exc}"
                            )

            manifest_rows.append(
                {
                    "version_id": version_id,
                    "date_start": date_start,
                    "date_end": date_end,
                    "sha1": sha1,
                    "file_path": file_path,
                }
            )

    manifest_path = Path(args.manifest_path)
    write_manifest(rows=manifest_rows, manifest_path=manifest_path)

    print(f"Feed versions source: {cache_source}")
    print(f"Sampled versions: {len(sampled)}")
    print(f"Manifest written: {safe_relpath(manifest_path)}")

    available_count = sum(1 for row in manifest_rows if row["file_path"])
    print(f"Manifest rows with local zip file: {available_count}/{len(manifest_rows)}")

    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")


if __name__ == "__main__":
    main()
