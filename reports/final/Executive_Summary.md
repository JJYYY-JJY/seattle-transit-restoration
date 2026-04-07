# Executive Summary (One Page)

## Chinese (中文)

### 项目目标
本项目面向西雅图 King County Metro，提出一个“历史服务漂移驱动、天气稳健、公平约束”的公交服务恢复框架。目标是在服务小时预算约束下，优先恢复对脆弱群体最关键、且在不利天气下仍具稳健性的服务层。

### 数据与约束
仅使用静态公开数据：当前 GTFS、历史 GTFS（Transitland）、NOAA 天气、ACS 人口统计。研究不使用 GTFS-RT/AVL 等实时数据，也不依赖精细步行路网。

### 方法概览
1. 构建计划时刻连通性指标（指数时间衰减）。
2. 从历史最大服务与当前服务差值中生成恢复候选库。
3. 求解两类 MIP：效率+公平惩罚模型、稳健 max-min 模型。

### 关键结果
1. 中等预算稳健配置下，平均连通性由 7860.72 提升到 9800.69（+24.68%）。
2. 公平惩罚系数上升时，入选候选数量下降，组合从效率导向转向公平导向。
3. 强降雨惩罚从 Mild 提升为 Severe 时，稳健下界由 8846.93 降至 7020.13（约 -20.65%）。
4. Severe 配置更偏好短运行时候选，说明恶劣天气下“可执行性”优先级提高。

### 规划启示
1. 效率与公平并非二选一，可通过参数化权衡进行可解释调整。
2. 天气稳健性应成为恢复方案评估的常规维度。
3. 预算提升需结合有效候选包络，否则边际收益有限。

### 交付价值
流程可复现、可审计、可迁移，可直接支持“从数据诊断到恢复决策”的规划闭环。

---

## English

### Objective
This project builds a restoration planning framework for King County Metro that is drift-driven, equity-aware, and weather-robust. Under service-hour budgets, it prioritizes restoration layers that protect vulnerable communities while remaining effective in adverse weather scenarios.

### Data and Scope Constraints
The workflow uses static public data only: current GTFS, historical GTFS archives (Transitland), NOAA weather records, and ACS demographics. No real-time GTFS-RT/AVL and no fine-grained pedestrian routing network are required.

### Method at a Glance
1. Define a schedule-based connectivity metric with exponential travel-time decay.
2. Build restoration candidates from the gap between current and historical-maximum service.
3. Solve two MIP formulations: efficiency with fairness penalty, and robust max-min for vulnerable tracts.

### Key Findings
1. At the medium-budget robust setting, mean connectivity increases from 7860.72 to 9800.69 (+24.68%).
2. As fairness penalty increases, selected candidate count decreases, indicating a shift from pure efficiency toward equity-focused allocation.
3. Switching heavy-rain penalty from Mild to Severe lowers robust floor from 8846.93 to 7020.13 (about -20.65%).
4. Severe-weather portfolios select shorter-runtime actions more frequently, emphasizing execution reliability under friction.

### Planning Implications
1. Efficiency and equity can be tuned explicitly rather than treated as a binary tradeoff.
2. Weather robustness should be a standard decision criterion in restoration planning.
3. Budget expansion should be assessed with effective candidate envelopes; otherwise, marginal gains may be limited.

### Delivery Value
The pipeline is reproducible, auditable, and portable, supporting an end-to-end transition from drift diagnostics to implementable restoration choices.