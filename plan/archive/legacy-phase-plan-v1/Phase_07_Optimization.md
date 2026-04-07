# Phase 7: Optimization Modeling

**Objective:** Formulate and solve the Mixed-Integer Programming (MIP) models to select the optimal bundle of restoration candidates subject to a budget constraint.

## Step-by-Step Instructions for AI Agent

### 7.1 Setup Optimization Environment
- Write `src/optimization/solver.py`.
- Import `mip`, `pulp`, or `gurobipy` (prefer `mip` with the default CBC solver for open-source reproducibility, or Gurobi if a license is available in the environment).

### 7.2 Model 1: Efficiency + Fairness Penalty
- **Decision Variables:** $x_j \in \{0, 1\}$ for each candidate $j \in J$.
- **Parameters:** 
  - Marginal gains $\Delta_{gjs}$
  - Candidate costs $c_j$
  - Budget $B$
  - Weather probabilities $p_s$
  - Tract population weights $\alpha_g$
  - Fairness penalty parameter $\lambda$
- **Formulation:**
  - Let Total Gain for tract $g$ be $G_g = \sum_s p_s \sum_j \Delta_{gjs} x_j$
  - Let Average Vulnerable Gain $AvgV = \frac{1}{|G_v|} \sum_{g \in G_v} G_g$
  - Let Average Non-Vulnerable Gain $AvgNV = \frac{1}{|G_{nv}|} \sum_{g \in G_{nv}} G_g$
  - Gap $= AvgNV - AvgV$ (or use an absolute value constraint).
  - **Objective:** Maximize $\sum_g \alpha_g G_g - \lambda \cdot \text{Gap}$
  - **Constraint:** $\sum_j c_j x_j \le B$

### 7.3 Model 2: Robust Max-Min (Focusing on Vulnerable Tracts)
- **Decision Variables:** $x_j \in \{0, 1\}$, and an auxiliary continuous variable $Z$.
- **Formulation:**
  - Let the average connectivity of vulnerable tracts under scenario $s$ be:
    $CV(s) = \frac{1}{|G_v|} \sum_{g \in G_v} \left( A_g^{(0)}(s) + \sum_j \Delta_{gjs} x_j \right)$
  - **Constraint 1:** For all scenarios $s \in S$, $Z \le CV(s)$.
  - **Constraint 2:** Budget $\sum_j c_j x_j \le B$.
  - **Objective:** Maximize $Z$.

### 7.4 Solving and Output
- Create a function to loop over a range of Budgets $B$ (e.g., 500, 1000, 2000, 5000 service hours).
- Create a function to loop over a range of $\lambda$ (0 to high penalty).
- Save the results of these sweeps to `data/processed/optimization_results_efficiency.csv` and `data/processed/optimization_results_robust.csv`.
- Columns should include: `budget`, `lambda`, `objective_value`, `vulnerable_connectivity`, `gap`, `selected_candidates_list`.
- Generate `notebooks/07_Optimization.ipynb` to show the output of a single run.

**Stop Rule:** Do not proceed until the solver successfully runs both models and saves the CSV results.
