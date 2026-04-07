# Phase 5: Schedule-Based Connectivity Engine

**Objective:** Build a lightweight, scalable engine to compute origin-destination (O-D) scheduled travel times based strictly on GTFS schedules, without using OpenStreetMap.

## Step-by-Step Instructions for AI Agent

### 5.1 The Approximation Model
- Write `src/routing/connectivity_engine.py`.
- **Origins & Destinations:** Use the tract centroids generated in Phase 3.
- **Access Leg:** Use simple Euclidean or Haversine distance from the centroid to the nearest $k$ bus stops.
  - Calculate `access_walk_time` = distance / (standard_walk_speed * weather_speed_multiplier).
  - If distance > `max_walk_distance` (defined by weather state), access is not possible.
- **Transit Leg:** 
  - For a given origin stop and destination stop, compute the scheduled travel time using GTFS `stop_times.txt` and `trips.txt` for the specified time period.
  - Account for average wait time based on frequency (e.g., `wait_time = avg_headway / 2`).
- **Transfer Leg:** 
  - If direct connection doesn't exist, allow a maximum of 1 transfer. 
  - Add `transfer_penalty_mins` (from weather params).
- **Total Time ($T_{gh}$):** `access_time_O + wait_time_O + ride_time_1 + transfer_penalty + wait_time_T + ride_time_2 + access_time_D`.

### 5.2 Compute Baseline Connectivity Tensor
- For the **Current GTFS** version, compute the OD travel time matrix between all tracts $g \in G$ and all tracts $h \in H$.
- Apply the exponential decay function to compute the connectivity score for origin $g$:
  $A_g^{(0)}(s) = \sum_{h \in H} w_h \cdot \exp(-\beta T_{gh}(s))$
  where $w_h$ is the total population of destination tract $h$. Choose a standard $\beta$ (e.g., half-life of 30 minutes).
- Do this for every weather scenario $s$.

### 5.3 Outputs
- Save the baseline connectivity scores to `data/processed/baseline_connectivity_scores.csv` (columns: `tract_id`, `weather_scenario`, `connectivity_score`).
- Create `notebooks/05_Connectivity_Engine.ipynb` to map the baseline connectivity across Seattle for "Dry" vs "Heavy Rain" scenarios.

**Stop Rule:** Do not proceed until the baseline connectivity scores are successfully computed for the current network across all weather scenarios.
