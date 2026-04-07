---
goal: Week-by-week execution plan and milestone acceptance matrix for realized-connectivity v2 roadmap
version: 1.0
date_created: 2026-04-07
last_updated: 2026-04-07
owner: Seattle Transit Restoration Maintainers
status: Planned
tags: [process, execution, roadmap, weekly, milestone, validation]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This document is the weekly execution edition of the v2 global architecture roadmap. It converts the global task set in plan/architecture-realized-connectivity-1.md into a deterministic 25-week schedule (Week 00 to Week 24) with explicit weekly exits and milestone acceptance gates.

## 1. Requirements & Constraints

- **REQ-101**: Map all v2 global tasks TASK-001 to TASK-060 from plan/architecture-realized-connectivity-1.md into weekly execution windows.
- **REQ-102**: Define one explicit weekly objective and one weekly exit criterion per week.
- **REQ-103**: Include a machine-readable Week-by-Week table with fixed date windows.
- **REQ-104**: Include a milestone acceptance table with deterministic pass/fail criteria.
- **REQ-105**: Keep task ordering dependency-safe: upstream data contracts before model integration, model integration before optimization, optimization before packaging.
- **REQ-106**: Preserve the no-cost-cap and no-compute-cap assumption from the global plan.
- **REQ-107**: Keep artifact output locations aligned with existing repository layout under data/processed, src, notebooks, reports, scripts.
- **SEC-101**: Keep credentials and secrets out of tracked files; use .env data files only.
- **DAT-101**: Every milestone must have at least one tangible artifact under data/processed or reports/final.
- **OPS-101**: Candidate and optimization work must remain policy-executable and operations-feasible.
- **CON-101**: Week windows are fixed and use Monday-Sunday cadence except Week 00 (bootstrap week).
- **CON-102**: No week can close without satisfying that week's exit criterion.
- **GUD-101**: Use consistent naming and IDs so progress can be tracked by automation.
- **PAT-101**: Use milestone-gated progression; do not start a downstream milestone before upstream acceptance passes.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-101: Complete bootstrap closure and establish realtime reliability data foundation.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-101 | Week 00 (2026-04-07 to 2026-04-12). Close bootstrap tasks mapped to TASK-001, TASK-002, TASK-003, TASK-004. Weekly exit: archive note and v2 plan entry are present. | ✅ | 2026-04-07 |
| TASK-102 | Week 01 (2026-04-13 to 2026-04-19). Execute TASK-005 by implementing src/reliability/download_gtfsrt.py with snapshot scheduling and raw capture schema. Weekly exit: script runs and writes sample snapshots to staging. |  |  |
| TASK-103 | Week 02 (2026-04-20 to 2026-04-26). Execute TASK-006 by implementing canonical normalization in src/reliability/normalize_realtime.py. Weekly exit: normalized records include service_date, route_id, direction_id, trip_id, stop_id, event_ts. |  |  |
| TASK-104 | Week 03 (2026-04-27 to 2026-05-03). Execute TASK-007 and TASK-008 with warehouse persistence and static-realtime crosswalk logic. Weekly exit: reliability parquet tables exist and crosswalk diagnostics are produced. |  |  |
| TASK-105 | Week 04 (2026-05-04 to 2026-05-10). Execute TASK-009 and TASK-010 by publishing reliability manifest and first reliability metrics module. Weekly exit: reliability_manifest.csv and first route-period metrics table exist. |  |  |

### Implementation Phase 2

- GOAL-102: Complete empirical reliability-weather calibration and prepare network-routing interface.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-106 | Week 05 (2026-05-11 to 2026-05-17). Execute TASK-011 and TASK-012 for transfer failure model and route-period-weather calibration output. Weekly exit: reliability_route_period_weather.csv includes coefficient and interval fields. |  |  |
| TASK-107 | Week 06 (2026-05-18 to 2026-05-24). Execute TASK-013 and TASK-014 by generating transfer risk output and diagnostics notebook. Weekly exit: reliability_transfer_risk.csv and notebook 11 render without broken cells. |  |  |
| TASK-108 | Week 07 (2026-05-25 to 2026-05-31). Execute TASK-015 and TASK-016 by implementing weather calibration pipeline and hierarchical scenario generation. Weekly exit: season x precipitation x wind x temperature scenario table is generated. |  |  |
| TASK-109 | Week 08 (2026-06-01 to 2026-06-07). Execute TASK-017 and TASK-018 by integrating calibrated weather penalties into routing connectivity engine. Weekly exit: connectivity engine runs with calibrated penalty inputs and uncertainty fields. |  |  |
| TASK-110 | Week 09 (2026-06-08 to 2026-06-14). Execute TASK-019, TASK-020, TASK-021 by finishing weather notebook and bootstrapping street graph plus OTP/R5 client. Weekly exit: first network itinerary query returns valid path output. |  |  |

### Implementation Phase 3

- GOAL-103: Replace nearest-stop approximation and introduce opportunity-weighted scoring.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-111 | Week 10 (2026-06-15 to 2026-06-21). Execute TASK-022 and TASK-023 by producing access and transfer walk matrices in parquet outputs. Weekly exit: network_access_matrix.parquet and network_transfer_walk_matrix.parquet exist. |  |  |
| TASK-112 | Week 11 (2026-06-22 to 2026-06-28). Execute TASK-024 and TASK-025 by refactoring connectivity engine and adding LEHD/LODES download entrypoint. Weekly exit: connectivity engine consumes network matrices end-to-end. |  |  |
| TASK-113 | Week 12 (2026-06-29 to 2026-07-05). Execute TASK-026 and TASK-027 to produce multichannel destination weights file. Weekly exit: destination_weights_multichannel.csv includes jobs, services, hubs, population channels. |  |  |
| TASK-114 | Week 13 (2026-07-06 to 2026-07-12). Execute TASK-028 and TASK-029 by scoring channel-specific accessibility and publishing notebook 13 comparisons. Weekly exit: at least one channel-vs-population comparison figure is produced. |  |  |
| TASK-115 | Week 14 (2026-07-13 to 2026-07-19). Execute TASK-030, TASK-031, TASK-032 by adding equity groups and grouped frontier solver logic. Weekly exit: grouped fairness run completes with non-empty frontier output. |  |  |

### Implementation Phase 4

- GOAL-104: Build policy-executable bundles and reliability-aware optimization models.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-116 | Week 15 (2026-07-20 to 2026-07-26). Execute TASK-033, TASK-034, TASK-035 by publishing equity outcomes and first action bundle generator. Weekly exit: equity_group_connectivity_outcomes.csv and candidate bundle draft are generated. |  |  |
| TASK-117 | Week 16 (2026-07-27 to 2026-08-02). Execute TASK-036, TASK-037, TASK-038 by encoding operations constraints and bundle-component mapping. Weekly exit: candidate_bundles.csv and bundle_component_map.csv pass schema checks. |  |  |
| TASK-118 | Week 17 (2026-08-03 to 2026-08-09). Execute TASK-039 and TASK-040 by finalizing bundle notebook and integrating reliability penalties into optimizer objective. Weekly exit: optimization objective decomposition includes reliability and transfer terms. |  |  |
| TASK-119 | Week 18 (2026-08-10 to 2026-08-16). Execute TASK-041, TASK-042, TASK-043 by adding stochastic and robust model implementations and outputs. Weekly exit: optimization_results_stochastic.csv and optimization_results_bundle_robust.csv exist. |  |  |
| TASK-120 | Week 19 (2026-08-17 to 2026-08-23). Execute TASK-044 and TASK-045 by publishing optimization notebook and sparse tensor precompute utility. Weekly exit: notebook 16 includes deterministic, stochastic, robust comparisons. |  |  |

### Implementation Phase 5

- GOAL-105: Deliver scalability, external validation, and v2 publication package.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-121 | Week 20 (2026-08-24 to 2026-08-30). Execute TASK-046, TASK-047, TASK-048 by introducing distributed batch runner, config controls, runtime benchmark output. Weekly exit: runtime_benchmarks.csv has at least one full sweep benchmark row set. |  |  |
| TASK-122 | Week 21 (2026-08-31 to 2026-09-06). Execute TASK-049 and TASK-050 by publishing scalability notebook and face-validation module. Weekly exit: face validation script emits route or corridor directionality comparison table. |  |  |
| TASK-123 | Week 22 (2026-09-07 to 2026-09-13). Execute TASK-051, TASK-052, TASK-053 by running stress tests and publishing validation outputs and notebook 18. Weekly exit: validation_stress_results.csv includes at least three alternative definition families. |  |  |
| TASK-124 | Week 23 (2026-09-14 to 2026-09-20). Execute TASK-054, TASK-055, TASK-056 by adding acceptance criteria module, v2 plots, and English technical report draft. Weekly exit: Technical_Report_v2.md includes method, calibration, validation, and policy sections. |  |  |
| TASK-125 | Week 24 (2026-09-21 to 2026-09-27). Execute TASK-057, TASK-058, TASK-059, TASK-060 by final bilingual report, executive summary, pipeline script, and packaging notebook. Weekly exit: scripts/run_v2_pipeline.sh reproduces all headline artifacts from clean state. |  |  |

### Week-by-Week Master Calendar

| Week | Date Window | Source Global Tasks | Primary Output |
|------|-------------|---------------------|----------------|
| W00 | 2026-04-07 to 2026-04-12 | TASK-001 to TASK-004 | Archive closure and v2 entrypoints |
| W01 | 2026-04-13 to 2026-04-19 | TASK-005 | GTFS-RT ingestion script |
| W02 | 2026-04-20 to 2026-04-26 | TASK-006 | Realtime canonical normalization |
| W03 | 2026-04-27 to 2026-05-03 | TASK-007 to TASK-008 | Reliability parquet warehouse and ID crosswalk |
| W04 | 2026-05-04 to 2026-05-10 | TASK-009 to TASK-010 | Reliability manifest and route-period metrics |
| W05 | 2026-05-11 to 2026-05-17 | TASK-011 to TASK-012 | Transfer failure and weather-conditioned coefficients |
| W06 | 2026-05-18 to 2026-05-24 | TASK-013 to TASK-014 | Transfer risk table and reliability notebook |
| W07 | 2026-05-25 to 2026-05-31 | TASK-015 to TASK-016 | Weather calibration engine and hierarchical scenarios |
| W08 | 2026-06-01 to 2026-06-07 | TASK-017 to TASK-018 | Calibrated weather penalties integrated into routing |
| W09 | 2026-06-08 to 2026-06-14 | TASK-019 to TASK-021 | Weather diagnostics notebook and routing client bootstrap |
| W10 | 2026-06-15 to 2026-06-21 | TASK-022 to TASK-023 | Access and transfer network matrices |
| W11 | 2026-06-22 to 2026-06-28 | TASK-024 to TASK-025 | Network-routing connectivity engine and LODES downloader |
| W12 | 2026-06-29 to 2026-07-05 | TASK-026 to TASK-027 | Multichannel destination weights |
| W13 | 2026-07-06 to 2026-07-12 | TASK-028 to TASK-029 | Channel-specific scoring and comparison notebook |
| W14 | 2026-07-13 to 2026-07-19 | TASK-030 to TASK-032 | Equity groups and grouped frontier solver |
| W15 | 2026-07-20 to 2026-07-26 | TASK-033 to TASK-035 | Equity outcomes and initial bundle generator |
| W16 | 2026-07-27 to 2026-08-02 | TASK-036 to TASK-038 | Operations constraints and finalized bundle tables |
| W17 | 2026-08-03 to 2026-08-09 | TASK-039 to TASK-040 | Bundle notebook and reliability-aware objective |
| W18 | 2026-08-10 to 2026-08-16 | TASK-041 to TASK-043 | Stochastic and robust model outputs |
| W19 | 2026-08-17 to 2026-08-23 | TASK-044 to TASK-045 | Optimization notebook and sparse tensor precompute |
| W20 | 2026-08-24 to 2026-08-30 | TASK-046 to TASK-048 | Batch sweeps, config controls, runtime benchmarks |
| W21 | 2026-08-31 to 2026-09-06 | TASK-049 to TASK-050 | Scalability notebook and face validation module |
| W22 | 2026-09-07 to 2026-09-13 | TASK-051 to TASK-053 | Stress test outputs and validation notebook |
| W23 | 2026-09-14 to 2026-09-20 | TASK-054 to TASK-056 | Acceptance criteria module, v2 plots, report draft |
| W24 | 2026-09-21 to 2026-09-27 | TASK-057 to TASK-060 | Final reports, reproducible pipeline, packaging notebook |

## 3. Alternatives

- **ALT-101**: Sprint-only planning (biweekly) without explicit weekly exits; rejected because fine-grained execution control is required.
- **ALT-102**: Keep global phase-only structure with no calendar binding; rejected because progress and dependency drift become difficult to detect.
- **ALT-103**: Track milestones only and skip weekly mapping; rejected because milestone slippage root causes become opaque.
- **ALT-104**: Front-load all modeling before data foundation hardening; rejected because this increases rework risk.

## 4. Dependencies

- **DEP-101**: Existing global roadmap in plan/architecture-realized-connectivity-1.md.
- **DEP-102**: Access to GTFS static, GTFS-RT, NOAA, ACS, and optional OBA/LODES data sources.
- **DEP-103**: Routing stack availability (OTP or R5) for network-based itinerary generation.
- **DEP-104**: Solver environment for MILP plus robust or stochastic variants.
- **DEP-105**: Compute environment capable of matrix precompute and scenario sweeps.

## 5. Files

- **FILE-101**: plan/process-weekly-execution-v2-1.md (this weekly execution plan)
- **FILE-102**: plan/architecture-realized-connectivity-1.md (source global roadmap)
- **FILE-103**: src/reliability/*.py (weeks 01 to 08 primary implementation scope)
- **FILE-104**: src/routing/*.py (weeks 09 to 13 primary implementation scope)
- **FILE-105**: src/census/*.py (weeks 11 to 15 primary implementation scope)
- **FILE-106**: src/optimization/*.py (weeks 14 to 20 primary implementation scope)
- **FILE-107**: src/validation/*.py (weeks 21 to 23 primary implementation scope)
- **FILE-108**: data/processed/*.csv and data/processed/*.parquet (artifact acceptance scope)
- **FILE-109**: notebooks/11_Realized_Reliability.ipynb through notebooks/19_Results_Packaging.ipynb
- **FILE-110**: reports/final/Technical_Report_v2.md, reports/final/Technical_Report_v2_CN.md, reports/final/Executive_Summary_v2.md
- **FILE-111**: scripts/run_v2_pipeline.sh

## 6. Testing

### Milestone Acceptance Table

| Milestone | Target Week | Required Scope | Acceptance Criteria (All Must Pass) | Evidence Artifact |
|-----------|-------------|----------------|-------------------------------------|------------------|
| **MS-101 Realtime Foundation** | W04 | TASK-005 to TASK-009 | AC-101: reliability_manifest.csv exists and has non-empty rows. AC-102: normalized realtime parquet tables exist. AC-103: crosswalk diagnostics report unresolved ID rate below 5 percent. | data/processed/reliability_manifest.csv and data/processed/reliability/*.parquet |
| **MS-102 Reliability and Weather Calibration** | W09 | TASK-010 to TASK-019 | AC-104: reliability_route_period_weather.csv and reliability_transfer_risk.csv exist. AC-105: weather_behavior_calibration.csv includes coefficient and goodness fields. AC-106: notebook 11 and notebook 12 execute end-to-end. | data/processed/reliability_route_period_weather.csv and data/processed/weather_behavior_calibration.csv |
| **MS-103 Network and Opportunity Scoring** | W14 | TASK-020 to TASK-032 | AC-107: network access matrices exist in parquet. AC-108: connectivity engine uses network matrices with no nearest-stop fallback path enabled. AC-109: destination_weights_multichannel.csv contains four required channels. AC-110: grouped frontier run completes and stores output. | data/processed/network_access_matrix.parquet and data/processed/destination_weights_multichannel.csv |
| **MS-104 Bundle and Robust Optimization Core** | W19 | TASK-033 to TASK-045 | AC-111: candidate_bundles.csv and bundle_component_map.csv pass schema checks. AC-112: stochastic and robust optimization outputs are generated. AC-113: optimization notebook v2 contains deterministic versus stochastic versus robust comparison section. AC-114: sparse tensor precompute writes cache index. | data/processed/candidate_bundles.csv and data/processed/optimization_results_bundle_robust.csv |
| **MS-105 Scalability and Validation** | W22 | TASK-046 to TASK-053 | AC-115: runtime_benchmarks.csv records at least one full sweep benchmark run. AC-116: face validation output exists. AC-117: stress test output includes at least three alternate definition families. AC-118: validation notebook executes with pass or fail summary cells. | data/processed/runtime_benchmarks.csv and data/processed/validation_stress_results.csv |
| **MS-106 Final Publication and Reproducibility** | W24 | TASK-054 to TASK-060 | AC-119: acceptance_criteria.py returns pass on all mandatory checks. AC-120: Technical_Report_v2.md, Technical_Report_v2_CN.md, Executive_Summary_v2.md all exist. AC-121: run_v2_pipeline.sh regenerates headline artifacts from clean run. AC-122: packaging notebook reproduces final figures and tables. | reports/final/Technical_Report_v2.md and scripts/run_v2_pipeline.sh |

### Weekly Regression Checks

- **TEST-101**: At each week close, run schema validation on all newly generated CSV and Parquet artifacts.
- **TEST-102**: At each milestone week, run module-specific unit tests for reliability, routing, optimization, and validation packages.
- **TEST-103**: At W14, W19, and W24 run reproducibility checkpoints on sampled and full scopes.
- **TEST-104**: At W24 perform full clean-state execution using scripts/run_v2_pipeline.sh.

## 7. Risks & Assumptions

- **RISK-101**: GTFS-RT coverage gaps can block confidence in reliability calibration.
- **RISK-102**: OSM routing graph generation can introduce heavy preprocessing latency.
- **RISK-103**: Bundle feasibility proxies may not capture all agency scheduling constraints.
- **RISK-104**: Large scenario sweeps may expose solver stability differences across engines.
- **RISK-105**: External validation references can be noisy or weakly structured.
- **ASSUMPTION-101**: Required public data sources remain available throughout the 25-week window.
- **ASSUMPTION-102**: Team can execute overlapping engineering and research workstreams in parallel.
- **ASSUMPTION-103**: v1 baseline outputs remain frozen for reproducibility comparison.

## 8. Related Specifications / Further Reading

- plan/architecture-realized-connectivity-1.md
- plan/archive/legacy-phase-plan-v1/ARCHIVE_NOTE.md
- reports/final/Technical_Report.md
- reports/final/Technical_Report_CN.md
- GTFS Realtime specification: https://gtfs.org/documentation/realtime/reference/
- OpenTripPlanner documentation: https://docs.opentripplanner.org/
- LEHD/LODES documentation: https://lehd.ces.census.gov/data/
