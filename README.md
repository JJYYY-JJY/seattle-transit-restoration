# Seattle Transit Restoration Optimization

**Seasonally Robust and Equity-Constrained Restoration of Scheduled Transit Connectivity from Historical GTFS Archives in Seattle**

## Overview
This repository contains a purely schedule-based, equity-aware transit connectivity framework for Seattle. It uses official King County Metro GTFS, archived historical GTFS versions (from Transitland), NOAA weather data, and ACS demographic data to formulate and solve a seasonally robust, budget-constrained restoration optimization problem.

## Directory Structure
- `data/`: Raw and processed data, organized by source (GTFS, NOAA, ACS).
- `notebooks/`: Exploratory Jupyter notebooks matching the 10 project phases.
- `src/`: Python source code modules (gtfs, weather, census, routing, optimization, viz).
- `plan/`: Active and archived implementation plans (current v2 global roadmap and archived legacy plans).
- `reports/`: Proposal, generated figures, and the final report.
- `agent_instructions/`: Entry pointers and instruction index; completed legacy phase prompts are archived under `plan/archive/`.

## Getting Started
1. Create a virtual environment: `python3 -m venv venv && source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. AI Agent execution: Start from `plan/architecture-realized-connectivity-1.md` for the active global roadmap, and use `agent_instructions/README.md` for archive pointers.

## Data Download CLI
The repository now includes a shell entrypoint for Phase 1 data acquisition:
- `scripts/download_data.sh`

It supports these sources and writes directly into the existing `data/raw/*` layout:
- Official King County Metro static GTFS
- NOAA daily weather summaries (CDO API)
- ACS 5-year tract and block group extracts (Census API)
- Transitland feed versions and GTFS archives

### Quick Start
1. Create your local env file from the template:
	```bash
	cp scripts/data_sources.env.example .env.data
	```
2. Fill keys in `.env.data`:
	- `NOAA_TOKEN`
	- `CENSUS_KEY` (optional but recommended)
	- `TRANSITLAND_API_KEY` (needed for Transitland commands)
3. Run all downloads:
	```bash
	bash scripts/download_data.sh all
	```

### Command Examples
```bash
# Official KCM static GTFS only
bash scripts/download_data.sh kcm-static

# NOAA only
bash scripts/download_data.sh noaa

# ACS only
bash scripts/download_data.sh acs

# Transitland: list versions and download latest
bash scripts/download_data.sh transitland-versions
bash scripts/download_data.sh transitland-latest

# Transitland: download one specific historical feed version by key
bash scripts/download_data.sh transitland-version 979571bcf26a6fc5f1f2f10b710b545b0fbeea24
```

### Output Paths
- `data/raw/gtfs_current/`
- `data/raw/gtfs_archive/`
- `data/raw/noaa/`
- `data/raw/acs/`
- `data/raw/download_log.csv`

## GitHub Publishing (Privacy-Safe Defaults)

This repository is configured to publish code and project docs only.

### Not uploaded by default
- `data/raw/**` (downloaded source datasets)
- `data/processed/**` (derived outputs)
- `.env*` and other local secret-bearing environment files
- local IDE/runtime artifacts (`.venv`, `.idea`, `.DS_Store`, `__pycache__`)

See `data/README.md` for data publishing policy details.

### Recommended pre-push check
```bash
git status --short
```
Confirm only code/docs files are staged before pushing.

## Notebook Commit Hygiene

This repository uses `pre-commit` + `nbstripout` to remove Jupyter output cells before commit.

### One-time setup
```bash
pip install -r requirements.txt
pre-commit install
```

### Optional: normalize all notebooks now
```bash
pre-commit run --all-files
```

After setup, every `git commit` automatically strips outputs from `.ipynb` files.
