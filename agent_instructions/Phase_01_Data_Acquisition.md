# Phase 1: Data Acquisition and Version Cleaning

**Objective:** Automatically download, validate, and inventory the 4 core datasets: Current GTFS, Historical GTFS (Transitland), ACS demographics, and NOAA weather data.

## Step-by-Step Instructions for AI Agent

### 1.1 Setup and Environment
- Verify `requests`, `pandas`, `geopandas` are installed.
- Create a configuration file `src/config.py` to store base URLs, API tokens (placeholder for NOAA and Census), and bounding box coordinates for Seattle (King County Metro service area).

### 1.2 Acquire Current Official GTFS
- Write a script `src/gtfs/download_current.py`.
- Download the latest King County Metro static GTFS zip file from the official King County Metro GTFS endpoint (e.g., `https://kingcounty.gov/~/media/transportation/kcdot/MetroTransit/data/google_transit.zip` or the relevant MobilityData catalog link).
- Save to `data/raw/gtfs_current/google_transit_current.zip`.
- Extract and write a brief validation function to ensure essential files exist (`stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `calendar.txt`).

### 1.3 Acquire Historical GTFS (Transitland Archive)
- Write a script `src/gtfs/download_archive.py`.
- Query the Transitland API (v2) for feed versions corresponding to King County Metro.
- You do not need to download *every* single version. Implement a sampling strategy:
  - Select 1 version per quarter or 1 version every 6 months spanning the past 3-5 years (e.g., pre-COVID to present).
  - Target ~10-15 unique versions.
- Download the `.zip` files into `data/raw/gtfs_archive/` with names like `kcm_gtfs_{date}_{sha1}.zip`.
- Run a lightweight structural validation.
- Output a `feeds_manifest.csv` in `data/processed/` containing columns: `version_id`, `date_start`, `date_end`, `sha1`, `file_path`.

### 1.4 Acquire ACS Demographics
- Write a script `src/census/download_acs.py`.
- Use the Census API to pull 5-year ACS data for tracts (and block groups if possible) in King County, WA (State FIPS 53, County FIPS 033).
- Pull total population, and proxy variables for vulnerability:
  - Low-income population
  - Zero-vehicle households
  - Elderly population (65+)
  - Disability status
- Save raw JSON/CSV to `data/raw/acs/`.
- Download TIGER/Line shapefiles for the tracts and save to `data/raw/acs/shapefiles/`.

### 1.5 Acquire NOAA Weather Data
- Write a script `src/weather/download_noaa.py`.
- Use the NOAA CDO (Climate Data Online) API. Search for a primary Seattle station (e.g., Seattle-Tacoma International Airport, USW00024233).
- Pull daily summaries (PRCP, TMAX, TMIN, AWND) for the last 5 years to cover the GTFS archive timeline.
- Save raw data to `data/raw/noaa/seattle_daily_weather.csv`.

### 1.6 Output Validations
- Generate a Jupyter Notebook `notebooks/01_feed_inventory.ipynb`.
- In the notebook, load the manifest and print summaries of the downloaded data to confirm the data acquisition phase is complete.

**Stop Rule:** Do not proceed to Phase 2 until `feeds_manifest.csv`, raw GTFS zips, ACS data, and NOAA data are successfully written to disk.
