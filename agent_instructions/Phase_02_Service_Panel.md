# Phase 2: Constructing Longitudinal Service Panel

**Objective:** Parse the downloaded GTFS archives to extract historical service drift. Formulate a longitudinal dataset to identify which routes, directions, and time periods experienced the most significant service changes.

## Step-by-Step Instructions for AI Agent

### 2.1 Standardize Time Periods
- In `src/gtfs/service_calculator.py`, define 4 standard time bins:
  - AM Peak (06:00 - 09:00)
  - Midday (09:00 - 15:00)
  - PM Peak (15:00 - 18:00)
  - Evening (18:00 - 24:00)

### 2.2 Calculate Service Indicators per Version
- For each GTFS version listed in `data/processed/feeds_manifest.csv`:
  - Read `trips.txt`, `stop_times.txt`, `calendar.txt`, `calendar_dates.txt`.
  - Filter for "Average Weekday" service (or analyze a specific day of the week, e.g., Wednesday).
  - For every `route_id`, `direction_id`, and `time_period`, calculate:
    - `trip_count`: Total number of trips departing within the period.
    - `average_headway`: `(Period Duration in Minutes) / trip_count`.
    - `service_hours`: Sum of `(arrival_time - departure_time)` for all trips in this period.
  - Compile into a dataframe: `(version_id, route_id, direction_id, time_period, trip_count, avg_headway, service_hours)`.

### 2.3 Handle Persistent Identifiers
- Transit agencies sometimes change `route_id` or `stop_id` over time.
- Implement a simple crosswalk module `src/gtfs/crosswalk.py`. Use `route_short_name` to bridge `route_id` changes. Map everything to the `route_id` used in the *Current GTFS* version.

### 2.4 Stop-Level Service Drift
- Additionally, calculate the number of daily bus arrivals at each `stop_id`.
- Track this `stop_level_service_count` across versions to see spatial service drift.

### 2.5 Output
- Save the panel dataset to `data/processed/service_panel_route_period.csv`.
- Save the stop-level panel to `data/processed/service_panel_stop_level.csv`.
- Create `notebooks/02_service_panel.ipynb` to visualize the routes and periods with the highest variance (volatility ranking) over time.

**Stop Rule:** Do not proceed until `service_panel_route_period.csv` successfully captures the longitudinal trend of service across multiple feed versions.
