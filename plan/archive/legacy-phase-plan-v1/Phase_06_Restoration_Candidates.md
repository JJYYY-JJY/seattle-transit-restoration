# Phase 6: Historical Restoration Candidates

**Objective:** Identify the "gap" between current service and maximum historical service to construct the library of feasible restoration options.

## Step-by-Step Instructions for AI Agent

### 6.1 Identify Service Gaps
- Write `src/optimization/candidate_generator.py`.
- Load `data/processed/service_panel_route_period.csv`.
- For each `(route_id, direction_id, time_period)`:
  - Find $q_j^{\max}$ = maximum `trip_count` (or minimum `avg_headway`) observed across all historical versions.
  - Find $q_{j,0}$ = `trip_count` in the Current GTFS version.
  - Calculate the gap: $U_j = q_j^{\max} - q_{j,0}$.
- Filter for $U_j > 0$. These represent services that were historically viable but have been cut.

### 6.2 Discretize Candidates ($j \in J$)
- We don't have to restore the entire gap at once. Break the gap down into actionable units. 
- Example: If the gap is 6 trips per period, define candidate $j$ as "Add 2 trips to Route X, AM Peak".
- For each candidate $j$, estimate the cost $c_j$ in **Service-Hours** using the average trip runtime from GTFS.

### 6.3 Precompute Marginal Connectivity Gains ($\Delta_{gjs}$)
- This is critical for the MIP formulation. We assume linear additive gains for small changes to keep the math tractable.
- For each candidate $j$, temporarily "add" this service to the network (e.g., lower the average headway by the proposed amount).
- Recalculate the connectivity engine for all tracts $g$ under all weather scenarios $s$.
- Calculate $\Delta_{gjs} = A_g^{(with\_j)}(s) - A_g^{(0)}(s)$.
- Save this large mapping to a sparse matrix or CSV: `data/processed/marginal_gains_delta.csv` (columns: `tract_g`, `candidate_j`, `weather_s`, `delta_score`).
- Save the candidate list to `data/processed/candidate_library.csv` (columns: `candidate_id`, `route`, `period`, `cost_cj`).

### 6.4 Output Validation
- Create `notebooks/06_Restoration_Candidates.ipynb`.
- Show a table of the top 10 most expensive candidates and the top 10 candidates that yield the highest aggregate delta.

**Stop Rule:** Do not proceed until `candidate_library.csv` and `marginal_gains_delta.csv` are fully generated.
