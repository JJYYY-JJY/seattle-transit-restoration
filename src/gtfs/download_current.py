from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import (
    GTFS_CURRENT_DIR,
    KCM_GTFS_FALLBACK_URL,
    KCM_GTFS_URL,
    ensure_data_dirs,
)


ESSENTIAL_GTFS_FILES = {
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
}


def stream_download(url: str, destination: Path, timeout_seconds: int) -> None:
    with requests.get(url, stream=True, timeout=timeout_seconds) as response:
        response.raise_for_status()
        with destination.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    fh.write(chunk)


def download_with_fallback(urls: list[str], destination: Path, timeout_seconds: int) -> str:
    last_error: Exception | None = None
    for url in urls:
        try:
            print(f"Downloading GTFS from: {url}")
            stream_download(url=url, destination=destination, timeout_seconds=timeout_seconds)
            return url
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if destination.exists():
                destination.unlink()
            print(f"  Failed: {exc}")
    raise RuntimeError(f"Unable to download GTFS from all configured URLs: {last_error}")


def validate_gtfs_zip(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = {
            Path(name).name
            for name in archive.namelist()
            if name and not name.endswith("/")
        }
    return sorted(ESSENTIAL_GTFS_FILES - members)


def extract_gtfs(zip_path: Path, extract_dir: Path) -> None:
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and validate the current official King County Metro GTFS feed."
    )
    parser.add_argument("--url", default=KCM_GTFS_URL, help="Primary GTFS URL")
    parser.add_argument(
        "--fallback-url",
        default=KCM_GTFS_FALLBACK_URL,
        help="Fallback GTFS URL",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="HTTP timeout per request",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even when dated file already exists",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Skip extracting the validated zip",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_data_dirs()
    GTFS_CURRENT_DIR.mkdir(parents=True, exist_ok=True)

    utc_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    dated_zip = GTFS_CURRENT_DIR / f"google_transit_{utc_day}.zip"
    current_zip = GTFS_CURRENT_DIR / "google_transit_current.zip"
    extract_dir = GTFS_CURRENT_DIR / "google_transit_current"

    urls = [args.url]
    if args.fallback_url and args.fallback_url not in urls:
        urls.append(args.fallback_url)

    if args.force or not dated_zip.exists():
        if not args.force and current_zip.exists():
            shutil.copy2(current_zip, dated_zip)
            print(f"Using existing current GTFS zip for dated snapshot: {current_zip}")
        else:
            source_url = download_with_fallback(
                urls=urls,
                destination=dated_zip,
                timeout_seconds=args.timeout_seconds,
            )
            print(f"Downloaded file: {dated_zip}")
            print(f"Source URL: {source_url}")
    else:
        print(f"Using existing dated GTFS zip: {dated_zip}")

    shutil.copy2(dated_zip, current_zip)
    missing_files = validate_gtfs_zip(current_zip)
    if missing_files:
        raise RuntimeError(
            "Current GTFS validation failed. Missing required files: "
            + ", ".join(missing_files)
        )

    print(f"Validated required GTFS files in: {current_zip}")
    if not args.no_extract:
        extract_gtfs(zip_path=current_zip, extract_dir=extract_dir)
        print(f"Extracted GTFS to: {extract_dir}")


if __name__ == "__main__":
    main()
