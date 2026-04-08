# Copilot instructions for seattle-transit-restoration

## Build, test, and lint commands

| Purpose | Command | Notes |
| --- | --- | --- |
| Environment setup | `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` | Standard local setup from `README.md`. |
| Enable commit hook | `pre-commit install` | Installs the notebook output stripping hook. |
| Run configured hooks | `pre-commit run --all-files` | The only configured hook is `nbstripout` for `.ipynb` files. |
| Syntax smoke check | `python -m compileall -q src scripts` | Fast repository-wide Python sanity check. |
| One-shot updater run | `python scripts/continuous_data_updater.py --once` | Validates end-to-end updater wiring for selected jobs. |

There is currently no committed pytest/unittest suite in this repository, so there is no single-test command yet.

## High-level architecture

This repo is a staged CLI pipeline, with each domain package exposing executable scripts:

1. **Data ingestion**
   - `scripts/download_data.sh` is the top-level downloader for KCM static GTFS, NOAA, ACS, and Transitland archives.
   - Source-specific ingesters live in `src/gtfs/download_current.py`, `src/gtfs/download_archive.py`, `src/weather/download_noaa.py`, and `src/census/download_acs.py`.
   - Realtime ingestion starts with `src/reliability/download_gtfsrt.py`.
2. **Normalization and feature construction**
   - `src/reliability/normalize_realtime.py` converts GTFS-RT snapshots into canonical event rows.
   - `src/gtfs/service_calculator.py` builds longitudinal service panels plus route crosswalk artifacts.
   - `src/census/process_demographics.py` builds tract-level vulnerability metrics and centroid-enhanced GeoJSON.
   - `src/weather/weather_processor.py` classifies daily weather states and emits scenario probabilities plus friction parameters.
3. **Connectivity and optimization**
   - `src/routing/connectivity_engine.py` computes baseline tract-level connectivity by weather scenario.
   - `src/optimization/candidate_generator.py` creates restoration candidates and marginal gain matrices.
   - `src/optimization/solver.py` runs efficiency-fairness and robust max-min MILP sweeps.
4. **Reporting outputs**
   - `src/viz/plot_generators.py` renders report figures and a figure manifest under `reports/figures`.
5. **Continuous operations path**
   - `scripts/continuous_data_updater.py` schedules recurring ingestion/refresh jobs and writes state/logs under `data/raw/updater_state.json` and `data/raw/updater_logs/`.

## Key repository conventions

- **Active planning entrypoint:** use `plan/architecture-realized-connectivity-1.md` as the roadmap of record; legacy phase prompts are archived under `plan/archive/legacy-phase-plan-v1/`.
- **Path resolution pattern:** scripts commonly accept relative paths and resolve from repo root (via `resolve_project_path(...)`); prefer this over hardcoded absolute paths.
- **Data directory contract:** stages assume `src.config` directory constants and `ensure_data_dirs()`; keep raw outputs in `data/raw/*` and derived outputs in `data/processed/*`.
- **Fail-fast schema checks:** pipeline stages explicitly validate required columns and raise errors on missing/invalid inputs rather than silently continuing.
- **Canonical labels are strict and shared across stages:**
  - Time periods: `AM Peak`, `Midday`, `PM Peak`, `Evening`
  - Weather states: `Dry / Normal`, `Light Rain`, `Heavy Rain`, `Cold/Windy`, `Heat`
- **ID normalization is required:** tract IDs are normalized to canonical GEOID strings, and historical route IDs are reconciled through `src/gtfs/crosswalk.py` before downstream joins.
- **Secrets and data policy:** keep credentials in `.env.data` (from `scripts/data_sources.env.example`), and do not commit `data/raw/**` or `data/processed/**` (regenerate locally from scripts).
- **Local Copilot skill files:** `.github/skills/` is intentionally local-only and gitignored.
