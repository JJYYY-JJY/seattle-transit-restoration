# Project Charter & Proposal

## Title
**Seasonally Robust and Equity-Constrained Restoration of Scheduled Transit Connectivity from Historical GTFS Archives in Seattle**

## 1. Introduction & Motivation
Public transit agencies face ongoing challenges in maintaining service reliability and equity under budget constraints. Over time, transit networks experience "service drift" due to sequential cuts, schedule adjustments, and evolving demand. While many studies analyze historical schedules to quantify service changes retrospectively, fewer works operationalize these historical records as a library of feasible "restoration candidates" for future planning.

This project shifts the focus from retrospective measurement to **forward-looking robust optimization**. Using purely static, publicly available datasets, we define a population-weighted, schedule-based transit connectivity metric. By integrating seasonal weather stress models (driven by NOAA probabilities), we evaluate the resilience of this connectivity against adverse weather (which imposes access and transfer friction). Our ultimate goal is to formulate an optimization problem that selects historical service layers to restore, maximizing the weather-robust connectivity of vulnerable populations subject to a service-hour budget constraint.

## 2. Research Questions
**RQ1:** Across historical static GTFS archives for Seattle (King County Metro), which route-direction-period service layers exhibit the most significant historical drift, and how do these changes disparately impact transit connectivity for different census block groups (or tracts)?

**RQ2:** In the absence of real-time AVL data or explicit pedestrian routing networks, how can we construct a seasonally robust, weather-weighted, and equity-sensitive measure of scheduled transit connectivity using exclusively Current GTFS, Archived GTFS, NOAA Climate Data, and ACS Demographics?

**RQ3:** Under a strictly constrained operational budget (measured in service-hours), which historically observed service layers should be restored to maximize either (a) the worst-case weather-scenario connectivity of vulnerable communities (robust max-min), or (b) overall efficiency with an explicit penalty for inequity?

## 3. Data Sources & Constraints
To ensure transparency, reproducibility, and mathematical clarity, this project explicitly **excludes** realtime data (GTFS-RT), detailed street networks (OSM), and granular point-of-interest/jobs datasets (LEHD). 

The project strictly relies on four static data pillars:
1. **Current Official Static GTFS:** Base network schedule from King County Metro.
2. **Third-Party Historical Static GTFS Versions:** Longitudinal feed archives sourced via Transitland. Used exclusively to identify historical high-service envelopes and generate candidate restoration sets.
3. **NOAA Climate Data Online (CDO):** Historical weather data for Seattle, used strictly to derive the seasonal probabilities of discrete weather states (e.g., dry, light rain, heavy rain, cold-windy, heat) and justify access/transfer friction penalties.
4. **Census ACS 5-Year Estimates (API):** Demographic data at the tract/block-group level to compute population weights and composite vulnerability indices (low-income, zero-vehicle households, elderly/disabled proxies).

## 4. Methodology
**4.1. Schedule-Based Connectivity Engine**
Connectivity is defined as the population-weighted access from origin $g$ to all destinations $h$, subject to a smooth decay over scheduled travel time:
$A_g(x,s)=\sum_{h\in H} w_h \cdot \exp(-\beta T_{gh}(x,s))$
where $w_h$ is the destination population weight, and $T_{gh}(x,s)$ is the scheduled travel time under weather scenario $s$ given service restoration vector $x$. Weather scenarios introduce additive friction to walking access and transfer times.

**4.2. Longitudinal Service Panel & Candidate Generation**
By processing longitudinal GTFS archives, we compute the maximum historical service intensity $q_j^{\max}$ for each route-direction-period $j$. The gap between $q_j^{\max}$ and the current service level $q_{j,0}$ defines the allowable restoration space. Candidates are discretized into actionable units with associated service-hour costs $c_j$.

**4.3. Robust and Equity-Constrained Optimization**
Let $\Delta_{gjs}$ denote the marginal connectivity gain for origin $g$ under scenario $s$ if candidate $j$ is restored. We formulate two Mixed-Integer Programming (MIP) variants:
- **Efficiency + Fairness Penalty:** $\max_x \sum_s p_s \sum_g \alpha_g \sum_j \Delta_{gjs}x_j - \lambda \cdot \mathrm{Gap}(x)$
- **Robust Max-Min:** $\max_x \min_s \left( \frac{1}{|G_v|}\sum_{g\in G_v} A_g(x,s) \right)$
Both subject to the budget constraint $\sum_j c_jx_j \le B$ and binary decision variables $x_j \in \{0, 1\}$.

## 5. Scope & Exclusions
- **What this project IS:** A scheduled-connectivity analysis, an optimization of historical service drift, a robust optimization modeling exercise factoring discrete weather probabilities.
- **What this project IS NOT:** Real-time delay prediction, routing engine development, full timetable redesign, or economic job-accessibility analysis.

## 6. Project Outcomes
1. A reproducible Python data pipeline and analytical codebase.
2. A formalized MIP model demonstrating the trade-offs between budget, efficiency, and equity.
3. A technical report/paper detailing theoretical properties (monotonicity, fairness frontiers) and empirical findings for Seattle.
