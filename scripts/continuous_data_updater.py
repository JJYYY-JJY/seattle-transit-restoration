#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_utc(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def env_int(key: str, fallback: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return fallback
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in environment for {key}: {raw}") from exc


@dataclass(frozen=True)
class JobConfig:
    name: str
    interval_seconds: int
    timeout_seconds: int
    description: str


ALL_JOBS = (
    "gtfs_rt",
    "kcm_static",
    "transitland_versions",
    "transitland_latest",
    "noaa",
    "acs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 24x7 data refresh jobs for Seattle transit restoration datasets."
    )
    parser.add_argument("--env-file", default=".env.data", help="Environment file path")
    parser.add_argument(
        "--state-file",
        default="data/raw/updater_state.json",
        help="Persistent job state JSON path",
    )
    parser.add_argument(
        "--lock-file",
        default="data/raw/updater.lock",
        help="Single-instance lock file path",
    )
    parser.add_argument(
        "--log-dir",
        default="data/raw/updater_logs",
        help="Directory where per-job logs are written",
    )
    parser.add_argument(
        "--jobs",
        default=",".join(ALL_JOBS),
        help=(
            "Comma-separated jobs to run. Available: "
            + ", ".join(ALL_JOBS)
        ),
    )
    parser.add_argument(
        "--sleep-cap-seconds",
        type=int,
        default=30,
        help="Maximum main-loop sleep duration",
    )
    parser.add_argument(
        "--failure-retry-seconds",
        type=int,
        default=env_int("UPDATER_FAILURE_RETRY_SECONDS", 300),
        help="Retry delay after a failed job",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run selected jobs once and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print due jobs and commands without executing network calls",
    )

    parser.add_argument(
        "--gtfsrt-interval-seconds",
        type=int,
        default=env_int("UPDATER_GTFSRT_INTERVAL_SECONDS", 30),
    )
    parser.add_argument(
        "--kcm-static-interval-minutes",
        type=int,
        default=env_int("UPDATER_KCM_STATIC_INTERVAL_MINUTES", 360),
    )
    parser.add_argument(
        "--transitland-versions-interval-minutes",
        type=int,
        default=env_int("UPDATER_TRANSITLAND_VERSIONS_INTERVAL_MINUTES", 720),
    )
    parser.add_argument(
        "--transitland-latest-interval-minutes",
        type=int,
        default=env_int("UPDATER_TRANSITLAND_LATEST_INTERVAL_MINUTES", 1440),
    )
    parser.add_argument(
        "--noaa-interval-minutes",
        type=int,
        default=env_int("UPDATER_NOAA_INTERVAL_MINUTES", 360),
    )
    parser.add_argument(
        "--acs-interval-hours",
        type=int,
        default=env_int("UPDATER_ACS_INTERVAL_HOURS", 168),
    )
    parser.add_argument(
        "--noaa-lookback-days",
        type=int,
        default=env_int("UPDATER_NOAA_LOOKBACK_DAYS", 30),
        help="NOAA incremental window size for each refresh",
    )
    parser.add_argument(
        "--acs-year",
        default=os.getenv("UPDATER_ACS_YEAR", "auto"),
        help="ACS year to pull (auto uses current UTC year)",
    )
    parser.add_argument(
        "--allow-empty-gtfsrt",
        action="store_true",
        help="Allow gtfs_rt job to skip when GTFS-RT URLs are not configured",
    )
    return parser.parse_args()


def load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "jobs": {}}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid updater state JSON in {path}")
    payload.setdefault("version", 1)
    payload.setdefault("jobs", {})
    return payload


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = iso_utc(utc_now())
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def acquire_single_instance_lock(lock_file: Path) -> int:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise RuntimeError(
            f"Another updater instance is already running (lock: {lock_file})"
        ) from exc
    return fd


def build_job_configs(args: argparse.Namespace) -> dict[str, JobConfig]:
    return {
        "gtfs_rt": JobConfig(
            name="gtfs_rt",
            interval_seconds=max(5, args.gtfsrt_interval_seconds),
            timeout_seconds=90,
            description="GTFS-RT snapshot capture",
        ),
        "kcm_static": JobConfig(
            name="kcm_static",
            interval_seconds=max(300, args.kcm_static_interval_minutes * 60),
            timeout_seconds=600,
            description="Official KCM static GTFS refresh",
        ),
        "transitland_versions": JobConfig(
            name="transitland_versions",
            interval_seconds=max(600, args.transitland_versions_interval_minutes * 60),
            timeout_seconds=600,
            description="Transitland feed version listing",
        ),
        "transitland_latest": JobConfig(
            name="transitland_latest",
            interval_seconds=max(600, args.transitland_latest_interval_minutes * 60),
            timeout_seconds=900,
            description="Transitland latest archive refresh",
        ),
        "noaa": JobConfig(
            name="noaa",
            interval_seconds=max(300, args.noaa_interval_minutes * 60),
            timeout_seconds=900,
            description="NOAA incremental raw pull + weather processed refresh",
        ),
        "acs": JobConfig(
            name="acs",
            interval_seconds=max(3600, args.acs_interval_hours * 3600),
            timeout_seconds=1200,
            description="ACS refresh",
        ),
    }


def select_jobs(raw: str) -> list[str]:
    jobs = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(jobs) - set(ALL_JOBS))
    if unknown:
        raise RuntimeError(f"Unknown job(s): {', '.join(unknown)}")
    deduped: list[str] = []
    for job in jobs:
        if job not in deduped:
            deduped.append(job)
    return deduped


def append_log(log_dir: Path, job_name: str, content: str) -> None:
    day_key = utc_now().strftime("%Y-%m-%d")
    path = log_dir / job_name / f"{day_key}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(content)


def required_env_missing(job_name: str) -> list[str]:
    required: dict[str, list[str]] = {
        "transitland_versions": ["TRANSITLAND_API_KEY"],
        "transitland_latest": ["TRANSITLAND_API_KEY"],
        "noaa": ["NOAA_TOKEN"],
    }
    missing: list[str] = []
    for env_key in required.get(job_name, []):
        if not os.getenv(env_key, "").strip():
            missing.append(env_key)
    return missing


def command_for_job(
    job_name: str,
    repo_root: Path,
    args: argparse.Namespace,
) -> list[tuple[list[str], dict[str, str]]]:
    python_bin = sys.executable
    if job_name == "gtfs_rt":
        command = [
            python_bin,
            str(repo_root / "src/reliability/download_gtfsrt.py"),
            "--output-root",
            str(repo_root / "data/raw/gtfs_rt"),
        ]
        if args.allow_empty_gtfsrt:
            command.append("--allow-empty-config")
        return [(command, {})]

    if job_name == "kcm_static":
        return [(["bash", "scripts/download_data.sh", "kcm-static"], {})]

    if job_name == "transitland_versions":
        return [(["bash", "scripts/download_data.sh", "transitland-versions"], {})]

    if job_name == "transitland_latest":
        return [(["bash", "scripts/download_data.sh", "transitland-latest"], {})]

    if job_name == "noaa":
        today = date.today()
        start_date = today - timedelta(days=max(30, args.noaa_lookback_days))
        env_patch = {
            "NOAA_START_DATE": start_date.isoformat(),
            "NOAA_END_DATE": today.isoformat(),
        }
        return [
            (["bash", "scripts/download_data.sh", "noaa"], env_patch),
            (
                [
                    python_bin,
                    str(repo_root / "src/weather/download_noaa.py"),
                    "--from-local-json",
                    "--start-date",
                    start_date.isoformat(),
                    "--end-date",
                    today.isoformat(),
                ],
                {},
            ),
            ([python_bin, str(repo_root / "src/weather/weather_processor.py")], {}),
        ]

    if job_name == "acs":
        if args.acs_year == "auto":
            acs_year = str(date.today().year)
        else:
            acs_year = args.acs_year
        return [(["bash", "scripts/download_data.sh", "acs"], {"ACS_YEAR": acs_year})]

    raise RuntimeError(f"Unsupported job: {job_name}")


def run_job(
    job_name: str,
    config: JobConfig,
    repo_root: Path,
    log_dir: Path,
    args: argparse.Namespace,
    dry_run: bool,
) -> tuple[bool, str]:
    started = utc_now()
    missing = required_env_missing(job_name)
    if missing:
        message = f"Missing required environment variable(s): {', '.join(missing)}"
        append_log(log_dir, job_name, f"[{iso_utc(started)}] ERROR {message}\n")
        return False, message

    steps = command_for_job(job_name=job_name, repo_root=repo_root, args=args)
    append_log(
        log_dir,
        job_name,
        f"[{iso_utc(started)}] START {config.description} steps={len(steps)}\n",
    )

    for index, (command, env_patch) in enumerate(steps, start=1):
        rendered = " ".join(shlex.quote(part) for part in command)
        append_log(log_dir, job_name, f"[{iso_utc(utc_now())}] STEP {index}: {rendered}\n")

        if dry_run:
            append_log(log_dir, job_name, f"[{iso_utc(utc_now())}] DRY-RUN step skipped\n")
            continue

        env = os.environ.copy()
        env.update(env_patch)

        try:
            result = subprocess.run(
                command,
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = (
                f"Timed out after {config.timeout_seconds}s while running step {index} for {job_name}"
            )
            append_log(log_dir, job_name, f"[{iso_utc(utc_now())}] ERROR {message}\n")
            return False, message

        if result.stdout:
            append_log(log_dir, job_name, result.stdout.rstrip() + "\n")
        if result.stderr:
            append_log(log_dir, job_name, result.stderr.rstrip() + "\n")

        if result.returncode != 0:
            message = f"Step {index} exited with code {result.returncode}"
            append_log(log_dir, job_name, f"[{iso_utc(utc_now())}] ERROR {message}\n")
            return False, message

    append_log(log_dir, job_name, f"[{iso_utc(utc_now())}] SUCCESS\n")
    return True, "ok"


def next_due_epoch(
    job_name: str,
    config: JobConfig,
    state: dict[str, Any],
    now_epoch: float,
    failure_retry_seconds: int,
) -> float:
    job_state = state.get("jobs", {}).get(job_name)
    if not isinstance(job_state, dict):
        return now_epoch

    due_candidates: list[float] = []
    ref = job_state.get("last_success") or job_state.get("last_started")
    if isinstance(ref, str):
        due_candidates.append(parse_iso_utc(ref).timestamp() + config.interval_seconds)

    failure_ts = job_state.get("last_failure")
    failures = int(job_state.get("consecutive_failures", 0) or 0)
    if failures > 0 and isinstance(failure_ts, str):
        due_candidates.append(parse_iso_utc(failure_ts).timestamp() + failure_retry_seconds)

    if not due_candidates:
        return now_epoch
    return min(due_candidates)


def update_job_state(
    state: dict[str, Any],
    job_name: str,
    success: bool,
    message: str,
    started: datetime,
) -> None:
    jobs = state.setdefault("jobs", {})
    job_state = jobs.setdefault(job_name, {})
    job_state["last_started"] = iso_utc(started)
    job_state["last_message"] = message

    if success:
        job_state["last_success"] = iso_utc(utc_now())
        job_state["consecutive_failures"] = 0
    else:
        job_state["last_failure"] = iso_utc(utc_now())
        job_state["consecutive_failures"] = int(job_state.get("consecutive_failures", 0) or 0) + 1


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    env_file = (repo_root / args.env_file).resolve() if not Path(args.env_file).is_absolute() else Path(args.env_file)
    state_file = (repo_root / args.state_file).resolve() if not Path(args.state_file).is_absolute() else Path(args.state_file)
    lock_file = (repo_root / args.lock_file).resolve() if not Path(args.lock_file).is_absolute() else Path(args.lock_file)
    log_dir = (repo_root / args.log_dir).resolve() if not Path(args.log_dir).is_absolute() else Path(args.log_dir)

    load_env_file(env_file)
    selected_jobs = select_jobs(args.jobs)
    job_configs = build_job_configs(args)
    state = load_state(state_file)

    lock_fd = acquire_single_instance_lock(lock_file)
    print(f"Updater started with jobs: {', '.join(selected_jobs)}")
    print(f"Logs: {log_dir}")
    print(f"State: {state_file}")

    try:
        if args.once:
            for job_name in selected_jobs:
                started = utc_now()
                config = job_configs[job_name]
                success, message = run_job(
                    job_name=job_name,
                    config=config,
                    repo_root=repo_root,
                    log_dir=log_dir,
                    args=args,
                    dry_run=args.dry_run,
                )
                update_job_state(state, job_name, success, message, started)
                save_state(state_file, state)
                print(f"{job_name}: {'OK' if success else 'FAIL'} - {message}")
            return

        while True:
            now_epoch = time.time()
            due_jobs = [
                name
                for name in selected_jobs
                if now_epoch
                >= next_due_epoch(
                    job_name=name,
                    config=job_configs[name],
                    state=state,
                    now_epoch=now_epoch,
                    failure_retry_seconds=max(10, args.failure_retry_seconds),
                )
            ]

            for job_name in due_jobs:
                started = utc_now()
                config = job_configs[job_name]
                success, message = run_job(
                    job_name=job_name,
                    config=config,
                    repo_root=repo_root,
                    log_dir=log_dir,
                    args=args,
                    dry_run=args.dry_run,
                )
                update_job_state(state, job_name, success, message, started)
                save_state(state_file, state)
                print(f"[{iso_utc(utc_now())}] {job_name}: {'OK' if success else 'FAIL'} - {message}")

            next_due_values = [
                next_due_epoch(
                    job_name=name,
                    config=job_configs[name],
                    state=state,
                    now_epoch=time.time(),
                    failure_retry_seconds=max(10, args.failure_retry_seconds),
                )
                for name in selected_jobs
            ]
            if not next_due_values:
                raise RuntimeError("No jobs selected")

            next_due = min(next_due_values)
            sleep_seconds = max(1, min(args.sleep_cap_seconds, int(next_due - time.time())))
            time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        print("Updater stopped by keyboard interrupt")
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    main()
