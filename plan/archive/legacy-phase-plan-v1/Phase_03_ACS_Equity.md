# Phase 3: ACS Geography and Equity Layer

**Objective:** Create the demographic foundation for the population-weighted connectivity metric. Define which spatial units (tracts/block groups) are considered "vulnerable".

## Step-by-Step Instructions for AI Agent

### 3.1 Process ACS Data
- Write `src/census/process_demographics.py`.
- Load the raw ACS JSON/CSV data downloaded in Phase 1.
- Merge the demographic variables to the TIGER/Line shapefiles based on `GEOID`.
- Ensure the coordinate reference system (CRS) is set to a locally accurate projection (e.g., EPSG:2285 or EPSG:32610 for Seattle/Washington State) for distance calculations, but keep a WGS84 (EPSG:4326) version for GTFS mapping.

### 3.2 Compute Vulnerability Index
- For each tract/block group, calculate percentages:
  - `% Low Income`
  - `% Zero-Vehicle Households`
  - `% Elderly/Disabled`
- Create a composite `vulnerability_score`. This could be a simple average of the percentiles of these metrics, or a threshold-based flag (e.g., 1 if the tract is in the top quartile of poverty, 0 otherwise).
- Categorize the tracts into two groups: `vulnerable` and `non-vulnerable` (or deciles).

### 3.3 Compute Tract Centroids
- Extract the geometric centroid for each tract/block group. This will serve as the Origin/Destination point for the connectivity engine.
- Save this combined geospatial dataset to `data/processed/acs_demographics_centroids.geojson`.

### 3.4 Output Validations
- Generate `notebooks/03_ACS_Equity.ipynb`.
- Plot a choropleth map of Seattle showing the `vulnerability_score` and highlighting the tracts flagged as `vulnerable`.

**Stop Rule:** Do not proceed until `acs_demographics_centroids.geojson` is written and visually validated.
