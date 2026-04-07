# Seasonally Robust and Equity-Constrained Restoration of Scheduled Transit Connectivity in Seattle

## Abstract
This project develops a reproducible planning workflow for transit service restoration under equity and weather uncertainty, using only static and publicly available datasets. The study area is King County Metro in Seattle. We combine current and historical GTFS feeds, ACS demographics, and NOAA climate records to estimate where scheduled transit connectivity has eroded and which restoration actions are most valuable under constrained budgets. Connectivity is modeled as a population-weighted, schedule-based accessibility function with exponential travel-time decay. Weather enters the model through scenario probabilities and friction penalties that increase access and transfer burden in adverse conditions. Historical service drift is converted into a candidate library of feasible route-direction-period restorations, each with estimated service-hour cost and marginal connectivity gain. We then solve two mixed-integer optimization formulations: an efficiency model with a fairness penalty and a robust max-min model focused on vulnerable tracts. Results from the Phase 9 experiment set show clear gains from restoration and meaningful tradeoffs between efficiency and equity priorities. At the medium-budget weather-robust setting, mean connectivity increases from 7860.72 to 9800.69 (about 24.68%). Frontier sweeps show diminishing returns once selected restoration costs approach the effective candidate envelope. Weather-sensitivity tests also show that harsher heavy-rain assumptions reduce robust floor outcomes and shift selected actions toward shorter-runtime, higher-immediacy interventions. The final pipeline offers transit planners a transparent method to move from historical drift diagnosis to budget-feasible, equity-aware restoration strategies without requiring real-time AVL or detailed pedestrian network inputs. The framework also highlights reproducibility, allowing peer review and scenario stress testing.

## 1. Introduction
Seattle-area transit planning faces a persistent tension: restore useful service quickly while protecting vulnerable riders under uncertain conditions. The project charter framed this as a forward-looking restoration problem rather than a retrospective trend report. Instead of only describing historical cuts, we operationalize historical service levels as a feasible restoration menu and optimize that menu under budget limits.

The central planning question is: given limited service hours, which historically observed service layers should be restored to maximize scheduled connectivity while balancing equity and robustness to seasonal weather stress?

## 2. Data and Study Area
The analysis covers King County Metro service in the Seattle region and uses four static data pillars:

1. King County Metro current static GTFS for the baseline schedule network.
2. Transitland historical static GTFS archives for longitudinal service drift and restoration bounds.
3. NOAA Climate Data Online records for weather-state probabilities and scenario parameterization.
4. ACS 5-year demographics for population weighting and vulnerability-focused objective terms.

No real-time data (for example, GTFS-RT or AVL delays) was used. No detailed street-network routing engine was required. This design choice keeps the workflow transparent, reproducible, and transferable to agencies with limited data infrastructure.

## 3. Methodology

### 3.1 Scheduled Connectivity Metric
For each origin tract $g$ under restoration vector $x$ and weather scenario $s$, scheduled connectivity is defined as:

$$
A_g(x, s) = \sum_{h \in H} w_h \cdot \exp\left(-\beta T_{gh}(x, s)\right)
$$

where $w_h$ is destination population weight and $T_{gh}(x, s)$ is schedule-derived generalized travel time including weather-induced access/transfer friction. Higher scores indicate stronger schedule-based opportunities.

### 3.2 Candidate Generation from Historical Drift
Route-direction-period service is assembled into a longitudinal panel. For each service key $j$, current service $q_{j,0}$ is compared with historical maximum $q_j^{\max}$. The nonnegative gap

$$
U_j = \max(0, q_j^{\max} - q_{j,0})
$$

defines restoration headroom. Gaps are discretized into actionable candidates with service-hour costs $c_j$. In this run, the candidate library contains 3655 incremental options (1671 unique candidates represented in marginal gain tables), spanning 265 routes.

### 3.3 Optimization Formulations
Two MIP formulations are solved:

1. Efficiency with fairness penalty:

$$
\max_x \sum_s p_s \sum_g \alpha_g \sum_j \Delta_{gjs} x_j - \lambda\,\mathrm{Gap}(x)
$$

2. Robust max-min for vulnerable tracts:

$$
\max_{x,z} z \quad \text{s.t.} \quad z \le \frac{1}{|G_v|}\sum_{g\in G_v} A_g(x,s),\ \forall s
$$

Both models satisfy budget and binary constraints:

$$
\sum_j c_j x_j \le B, \quad x_j \in \{0,1\}
$$

## 4. Results and Discussion

### 4.1 Visual Diagnostics from Phase 9
The report references the Phase 9 figures:

1. Service drift overview: [fig1_service_drift.png](../figures/fig1_service_drift.png)
2. Volatility map: [fig2_volatility_map.png](../figures/fig2_volatility_map.png)
3. Efficiency-fairness frontier: [fig3_fairness_frontier.png](../figures/fig3_fairness_frontier.png)
4. Candidate selection map: [fig4_candidate_selection_map.png](../figures/fig4_candidate_selection_map.png)
5. Weather robustness comparison: [fig5_weather_robustness_bar.png](../figures/fig5_weather_robustness_bar.png)

Together they show where service drift accumulated, how restoration candidates are spatially distributed, and how objective design changes the restoration portfolio.

### 4.2 Efficiency vs Equity Tradeoff
The fairness tradeoff sweep keeps budget fixed at 2000 (effective used budget about 1235 to 1293 service-hours, constrained by available candidate structure rather than nominal budget cap). As the fairness penalty $\lambda$ increases from 0 to 5, the selected candidate count declines (about 1671 to 1465), indicating a reallocation from broad efficiency gains toward equity-aligned coverage. The frontier shape is consistent with diminishing returns: extra nominal budget above the effective candidate envelope yields limited additional objective gain.

### 4.3 Weather-Robust Selection Shifts
At the medium-budget robust setting tracked in the figure manifest, mean connectivity rises from 7860.72 to 9800.69 (about +24.68%), with aggregate connectivity gain of about 240,556.51 points. Weather-penalty sensitivity shows clear portfolio shifts: moving from mild to severe heavy-rain penalties reduces robust floor from 8846.93 to 7020.13 (about -20.65%). Severe scenarios select more short-runtime candidates (1216 vs 1197 total selections), with profile statistics indicating lower average runtime among severe-only picks (0.365h) versus mild-only picks (1.085h). This suggests robust planning under harsher weather prioritizes interventions that preserve reliability under transfer/access friction.

## 5. Conclusion
This project demonstrates a full static-data pipeline from historical service drift detection to equity-aware, weather-robust restoration optimization for Seattle transit planning. The key contribution is operational: historical GTFS archives are transformed into a feasible restoration decision space rather than treated only as descriptive history.

Policy-wise, results support three planning implications:

1. Equity and efficiency can be tuned explicitly instead of treated as competing narratives.
2. Weather robustness materially changes restoration choices, so climate-informed penalties should be included in medium-term service planning.
3. Budget planning should account for effective candidate envelopes; beyond a point, nominal budget increases have weak returns unless new feasible restoration actions are introduced.

The workflow is reproducible and extensible, and can be adapted to additional agencies, alternative vulnerability definitions, or richer uncertainty models in future work.