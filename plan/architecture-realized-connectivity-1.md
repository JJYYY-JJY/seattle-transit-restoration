---
goal: End-to-end upgrade from schedule-based planning to empirically calibrated realized accessibility and operations-feasible restoration
version: 1.0
date_created: 2026-04-07
last_updated: 2026-04-07
owner: Seattle Transit Restoration Maintainers
status: Planned
tags: [architecture, feature, transit, robustness, equity, validation]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This plan replaces the completed static-schedule-first execution sequence with a new global architecture that prioritizes realized reliability, operations-feasible action design, empirically calibrated weather effects, and external validation. The plan explicitly assumes no implementation-cost or compute-cost ceiling and is structured as deterministic, atomic phases.

## 1. Requirements & Constraints

- **REQ-001**: Preserve compatibility with existing baseline outputs in `data/processed/` while adding realized-performance layers.
- **REQ-002**: Integrate real-time operations evidence (GTFS-RT and/or OneBusAway-derived feeds) into reliability and transfer-failure modeling.
- **REQ-003**: Replace nearest-stop and scalar walk frictions with street-network-based access/egress routing.
- **REQ-004**: Replace single destination population proxy with multi-channel opportunity weights (jobs, essential services, hubs, population).
- **REQ-005**: Upgrade fairness from single scalar vulnerability to multi-objective group-explicit fairness constraints.
- **REQ-006**: Upgrade candidate generation from route-direction-period increments to policy-executable action bundles.
- **REQ-007**: Calibrate weather penalties from observed operations behavior, not hand-picked static penalties.
- **REQ-008**: Support expansion to regional scale, larger scenario sets, and larger candidate sets.
- **REQ-009**: Add external validation and stress-testing beyond internal model consistency.
- **REQ-010**: Keep all generated artifacts reproducible via scripted pipelines under `src/` and notebooks under `notebooks/`.
- **SEC-001**: Keep secret-bearing credentials in `.env*` only; no keys or tokens committed into repository files.
- **SEC-002**: Validate and sanitize third-party feed payloads before persistence.
- **DAT-001**: Version all source snapshots and derived tables with manifest metadata and run IDs.
- **DAT-002**: Store normalized large intermediate tables in columnar format (Parquet) with schema versioning.
- **OPS-001**: Treat optimization actions as agency-executable units (bundle-level), not abstract micro increments only.
- **OPS-002**: Encode operator/garage/interline feasibility constraints in optimization-ready structures.
- **CON-001**: No cap on compute cost, runtime, or infrastructure spend for this roadmap.
- **CON-002**: Public-data-first implementation remains default, with optional non-public AVL extension hooks.
- **GUD-001**: Keep code paths modular by domain package (`routing`, `weather`, `optimization`, `reliability`, `equity`, `validation`).
- **PAT-001**: Enforce deterministic pipeline stages with explicit input/output contracts and schema checks.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Archive completed v1 phase plan and establish v2 execution control files.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Move legacy phase plans from `agent_instructions/Phase_*.md` to `plan/archive/legacy-phase-plan-v1/` and preserve history index. | ✅ | 2026-04-07 |
| TASK-002 | Create `agent_instructions/README.md` that points to archive and active v2 plan entrypoint. |  |  |
| TASK-003 | Update `README.md` project navigation to reference `plan/architecture-realized-connectivity-1.md`. |  |  |
| TASK-004 | Create `plan/archive/legacy-phase-plan-v1/ARCHIVE_NOTE.md` with archived file inventory and rationale. |  |  |

### Implementation Phase 2

- GOAL-002: Build realized operations data foundation (GTFS-RT / OBA) and normalized reliability warehouse.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-005 | Add `src/reliability/download_gtfsrt.py` to ingest TripUpdates, VehiclePositions, ServiceAlerts snapshots at fixed cadence. |  |  |
| TASK-006 | Add `src/reliability/normalize_realtime.py` to map feed entities to canonical keys: `service_date`, `route_id`, `direction_id`, `trip_id`, `stop_id`, `event_ts`. |  |  |
| TASK-007 | Add `src/reliability/realtime_warehouse.py` to persist normalized tables in `data/processed/reliability/*.parquet`. |  |  |
| TASK-008 | Add `src/gtfs/crosswalk_rt_static.py` to reconcile static and realtime trip/route identifiers across feed versions. |  |  |
| TASK-009 | Add `data/processed/reliability_manifest.csv` containing source URL, capture windows, schema versions, and row counts. |  |  |

### Implementation Phase 3

- GOAL-003: Estimate realized reliability and missed-connection surfaces from observed operations.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-010 | Add `src/reliability/metrics.py` for delay distribution, on-time probability, cancellation proxy, and bunching metrics by route-direction-period. |  |  |
| TASK-011 | Add `src/reliability/transfer_failure.py` to compute empirical missed-connection probability for transfer pairs by weather state and time period. |  |  |
| TASK-012 | Add `data/processed/reliability_route_period_weather.csv` with calibrated reliability coefficients and confidence intervals. |  |  |
| TASK-013 | Add `data/processed/reliability_transfer_risk.csv` with transfer-level failure probabilities and sample sizes. |  |  |
| TASK-014 | Add `notebooks/11_Realized_Reliability.ipynb` for diagnostics and fit quality plots. |  |  |

### Implementation Phase 4

- GOAL-004: Replace heuristic weather frictions with empirically calibrated weather-behavior mapping.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-015 | Add `src/weather/calibrate_weather_penalties.py` to estimate weather-to-delay and weather-to-transfer-risk mappings. |  |  |
| TASK-016 | Extend `src/weather/weather_processor.py` to output hierarchical scenarios: season × precipitation × wind × temperature bins. |  |  |
| TASK-017 | Add `data/processed/weather_behavior_calibration.csv` containing estimated coefficients and fit diagnostics. |  |  |
| TASK-018 | Replace static friction lookup in `src/routing/connectivity_engine.py` with calibrated reliability penalties and uncertainty bounds. |  |  |
| TASK-019 | Add `notebooks/12_Weather_Calibration.ipynb` for residual checks and stress-scenario generation. |  |  |

### Implementation Phase 5

- GOAL-005: Integrate street-network routing for realistic access/egress and transfer walk paths.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-020 | Add `src/routing/osm_graph_builder.py` to build multimodal walk graph from OSM extracts for study area. |  |  |
| TASK-021 | Add `src/routing/otp_client.py` (or `src/routing/r5_client.py`) for batch transit+street itinerary queries. |  |  |
| TASK-022 | Add `src/routing/access_egress_matrix.py` to compute tract-to-stop and stop-to-tract network travel times under weather-adjusted walk impedance. |  |  |
| TASK-023 | Add `data/processed/network_access_matrix.parquet` and `data/processed/network_transfer_walk_matrix.parquet`. |  |  |
| TASK-024 | Refactor `src/routing/connectivity_engine.py` to consume network matrices instead of nearest-stop approximations. |  |  |

### Implementation Phase 6

- GOAL-006: Upgrade destination weighting from population-only to opportunity-weighted accessibility.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-025 | Add `src/census/download_lodes.py` to fetch LEHD/LODES WAC/RAC/OD datasets for study geography. |  |  |
| TASK-026 | Add `src/census/process_opportunity_weights.py` to build tract-level channels: jobs, services, hubs, population. |  |  |
| TASK-027 | Add `data/processed/destination_weights_multichannel.csv` with normalized channel weights and composite variants. |  |  |
| TASK-028 | Extend scoring in `src/routing/connectivity_engine.py` to compute channel-specific and composite accessibility outputs. |  |  |
| TASK-029 | Add `notebooks/13_Opportunity_Weights.ipynb` for side-by-side comparison against population-only metric. |  |  |

### Implementation Phase 7

- GOAL-007: Replace scalar fairness with multi-objective, group-explicit equity design.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-030 | Add `src/census/equity_groups.py` to generate explicit groups (zero-car, disability, elderly, low-income, limited-English proxy). |  |  |
| TASK-031 | Extend `src/optimization/solver.py` with lexicographic objective mode and group-specific floor constraints. |  |  |
| TASK-032 | Add `src/optimization/fairness_frontier.py` to compute grouped frontiers and per-group trade-off surfaces. |  |  |
| TASK-033 | Add `data/processed/equity_group_connectivity_outcomes.csv` with group-wise gains, gaps, and floor violations. |  |  |
| TASK-034 | Add `notebooks/14_Group_Equity_Frontiers.ipynb` to visualize who gains and who remains underserved. |  |  |

### Implementation Phase 8

- GOAL-008: Rebuild candidate actions as operations-feasible action bundles.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-035 | Add `src/optimization/bundle_generator.py` to create corridor headway bundles, span extensions, weekend bundles, and paired-trip bundles. |  |  |
| TASK-036 | Add `src/optimization/ops_constraints.py` to encode garage/operator/interline feasibility approximations. |  |  |
| TASK-037 | Extend `src/optimization/candidate_generator.py` to emit bundle-level costs and bundle-level marginal gain priors. |  |  |
| TASK-038 | Add `data/processed/candidate_bundles.csv` and `data/processed/bundle_component_map.csv`. |  |  |
| TASK-039 | Add `notebooks/15_Action_Bundles.ipynb` for bundle sanity checks and policy-interpretability checks. |  |  |

### Implementation Phase 9

- GOAL-009: Upgrade optimization to scenario-rich, reliability-aware, and bundle-native robust models.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-040 | Refactor `src/optimization/solver.py` to include realized reliability penalties and transfer-failure terms in objective/constraints. |  |  |
| TASK-041 | Add `src/optimization/stochastic_model.py` for multi-scenario expected utility and CVaR variants. |  |  |
| TASK-042 | Add `src/optimization/robust_model.py` for strict max-min floors under calibrated uncertainty sets. |  |  |
| TASK-043 | Add `data/processed/optimization_results_stochastic.csv` and `data/processed/optimization_results_bundle_robust.csv`. |  |  |
| TASK-044 | Add `notebooks/16_Optimization_v2.ipynb` to compare efficiency, fairness, and robustness under the new model family. |  |  |

### Implementation Phase 10

- GOAL-010: Engineer large-scale compute path for regional and high-scenario expansion.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-045 | Add `src/routing/precompute_sparse_tensor.py` to build sparse OD-time-weather matrices and reusable cache keys. |  |  |
| TASK-046 | Add `src/optimization/batch_runner.py` for distributed sweeps across budgets, objectives, and scenario definitions. |  |  |
| TASK-047 | Add `src/config.py` options for chunk sizing, parallel backend, and cache invalidation strategy. |  |  |
| TASK-048 | Add `data/processed/runtime_benchmarks.csv` with wall time, memory, and solver convergence metrics by run profile. |  |  |
| TASK-049 | Add `notebooks/17_Scalability_Benchmarks.ipynb` for scaling curves and bottleneck diagnostics. |  |  |

### Implementation Phase 11

- GOAL-011: Add external face validation and counterfactual stress tests.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-050 | Add `src/validation/face_validation.py` to compare selected bundles against historical Metro restoration/cut directionality. |  |  |
| TASK-051 | Add `src/validation/stress_tests.py` to rerun core findings under alternate vulnerability definitions, weather thresholds, and destination weights. |  |  |
| TASK-052 | Add `data/processed/validation_face_alignment.csv` and `data/processed/validation_stress_results.csv`. |  |  |
| TASK-053 | Add `notebooks/18_Validation_Stress.ipynb` summarizing pass/fail and sensitivity intervals. |  |  |
| TASK-054 | Add minimum acceptance rules in `src/validation/acceptance_criteria.py` for reproducible go/no-go checks. |  |  |

### Implementation Phase 12

- GOAL-012: Publish v2 outputs, reproducibility artifacts, and final narrative packaging.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-055 | Extend `src/viz/plot_generators.py` with grouped fairness frontiers, reliability penalty decomposition, and bundle explainability plots. |  |  |
| TASK-056 | Add `reports/final/Technical_Report_v2.md` with methods, calibration details, validation evidence, and policy discussion. |  |  |
| TASK-057 | Add `reports/final/Technical_Report_v2_CN.md` for Chinese technical narrative parity. |  |  |
| TASK-058 | Add `reports/final/Executive_Summary_v2.md` focused on implementable actions and uncertainty-aware insights. |  |  |
| TASK-059 | Add `scripts/run_v2_pipeline.sh` to orchestrate full end-to-end reproducible execution. |  |  |
| TASK-060 | Add `notebooks/19_Results_Packaging.ipynb` to regenerate all headline figures/tables from processed outputs. |  |  |

## 3. Alternatives

- **ALT-001**: Keep static schedule-only framework and add more visualization detail; rejected because it does not improve behavioral realism.
- **ALT-002**: Add GTFS-RT only as descriptive appendix without changing optimization objective; rejected because reliability evidence must influence decisions.
- **ALT-003**: Keep nearest-stop approximation and tune walk multipliers; rejected because Seattle access geometry requires street-network routing realism.
- **ALT-004**: Keep single vulnerability scalar and only tune lambda; rejected because group-level winners/losers remain unobservable.
- **ALT-005**: Keep trip-increment candidates only; rejected because policy implementation occurs at bundle/corridor/span level.

## 4. Dependencies

- **DEP-001**: King County Metro static GTFS and realtime GTFS-RT feed access.
- **DEP-002**: Optional OneBusAway-derived historical reliability exports.
- **DEP-003**: NOAA daily weather and, if available, sub-daily weather observations for event attribution.
- **DEP-004**: ACS base demographics and LEHD/LODES opportunity datasets.
- **DEP-005**: OpenStreetMap extracts for study geography.
- **DEP-006**: OTP or R5 routing engine runtime environment.
- **DEP-007**: MILP solver with robust/stochastic support (Gurobi/CPLEX/HiGHS-compatible code paths).
- **DEP-008**: Columnar storage and parallel compute stack (PyArrow + optional Dask/Ray).

## 5. Files

- **FILE-001**: `README.md` (entrypoint update for archived plans and v2 roadmap)
- **FILE-002**: `agent_instructions/README.md` (archive pointer and usage)
- **FILE-003**: `plan/archive/legacy-phase-plan-v1/*` (archived v1 plan files)
- **FILE-004**: `src/reliability/download_gtfsrt.py`
- **FILE-005**: `src/reliability/normalize_realtime.py`
- **FILE-006**: `src/reliability/realtime_warehouse.py`
- **FILE-007**: `src/reliability/metrics.py`
- **FILE-008**: `src/reliability/transfer_failure.py`
- **FILE-009**: `src/gtfs/crosswalk_rt_static.py`
- **FILE-010**: `src/weather/calibrate_weather_penalties.py`
- **FILE-011**: `src/routing/osm_graph_builder.py`
- **FILE-012**: `src/routing/otp_client.py` or `src/routing/r5_client.py`
- **FILE-013**: `src/routing/access_egress_matrix.py`
- **FILE-014**: `src/census/download_lodes.py`
- **FILE-015**: `src/census/process_opportunity_weights.py`
- **FILE-016**: `src/census/equity_groups.py`
- **FILE-017**: `src/optimization/bundle_generator.py`
- **FILE-018**: `src/optimization/ops_constraints.py`
- **FILE-019**: `src/optimization/stochastic_model.py`
- **FILE-020**: `src/optimization/robust_model.py`
- **FILE-021**: `src/validation/face_validation.py`
- **FILE-022**: `src/validation/stress_tests.py`
- **FILE-023**: `src/validation/acceptance_criteria.py`
- **FILE-024**: `scripts/run_v2_pipeline.sh`
- **FILE-025**: `reports/final/Technical_Report_v2.md`

## 6. Testing

- **TEST-001**: Unit tests for realtime feed parsing, schema validation, and crosswalk integrity.
- **TEST-002**: Unit tests for transfer-failure estimation and weather calibration coefficient stability.
- **TEST-003**: Integration tests for OTP/R5 access matrix generation on sampled tracts/stops.
- **TEST-004**: Regression tests that compare v1 and v2 metrics on identical static-only settings.
- **TEST-005**: Optimization feasibility tests for bundle constraints and group-floor constraints.
- **TEST-006**: Robust/stochastic model consistency tests under deterministic single-scenario collapse.
- **TEST-007**: External validation test asserting minimum alignment threshold with historical restoration directionality.
- **TEST-008**: Stress-test suite for alternate vulnerability definitions, weather bins, and opportunity weighting schemes.
- **TEST-009**: End-to-end reproducibility test using `scripts/run_v2_pipeline.sh` from clean workspace state.

## 7. Risks & Assumptions

- **RISK-001**: GTFS-RT historical completeness may be uneven across seasons and routes.
- **RISK-002**: Cross-version trip/route reconciliation may introduce mapping uncertainty.
- **RISK-003**: Street-network routing throughput can become a major runtime bottleneck at regional scale.
- **RISK-004**: Bundle feasibility proxies may diverge from agency internal scheduling realities.
- **RISK-005**: External validation data may be partially qualitative and require structured coding.
- **ASSUMPTION-001**: Public data and open specifications remain available and stable over implementation period.
- **ASSUMPTION-002**: Sufficient compute and storage are available to support high-dimensional scenario sweeps.
- **ASSUMPTION-003**: Existing v1 processed outputs remain frozen as baseline references for reproducibility.

## 8. Related Specifications / Further Reading

- `plan/process-weekly-execution-v2-1.md`
- `plan/archive/legacy-phase-plan-v1/Phase_01_Data_Acquisition.md`
- `plan/archive/legacy-phase-plan-v1/Phase_10_Writing_Packaging.md`
- `reports/final/Technical_Report.md`
- `reports/final/Technical_Report_CN.md`
- GTFS Realtime specification: https://gtfs.org/documentation/realtime/reference/
- OpenTripPlanner documentation: https://docs.opentripplanner.org/
- LEHD/LODES documentation: https://lehd.ces.census.gov/data/
