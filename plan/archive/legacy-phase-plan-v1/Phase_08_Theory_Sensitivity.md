# Phase 8: Theory and Sensitivity Analysis

**Objective:** Validate the mathematical properties of the model and test its sensitivity to hyperparameter choices.

## Step-by-Step Instructions for AI Agent

### 8.1 Theoretical Validation Notebook
- Create `notebooks/08_Theory_Sensitivity.ipynb`.
- In Markdown cells, provide brief mathematical proofs or justifications for:
  1. **Monotonicity:** Proof that the optimal objective value of Model 2 (Robust Max-Min) is monotonically non-decreasing with respect to the budget $B$.
  2. **Tractability:** Justification that by assuming linear additive marginal gains $\Delta_{gjs}$, both Model 1 and Model 2 reduce to standard 0-1 ILP/MILP formulations, solvable by branch-and-bound.

### 8.2 Sensitivity: Budget Frontier
- Write code to plot the Pareto frontier of "Budget vs. Objective Value" for both models.
- Does the connectivity gain experience diminishing returns as the budget increases? (It should, as the solver picks the highest "bang-for-buck" candidates first).

### 8.3 Sensitivity: Fairness Trade-off
- Plot the "Efficiency vs. Equity" tradeoff curve for Model 1.
- X-axis: Fairness Gap.
- Y-axis: Total Population-Weighted Connectivity.
- Show how increasing $\lambda$ moves the solution along this curve.

### 8.4 Sensitivity: Weather Penalties
- Run Model 2 with two different weather penalty configurations:
  - Config A: Mild penalties for Heavy Rain.
  - Config B: Severe penalties for Heavy Rain.
- Compare the selected `candidate_j` lists. Does severe weather force the model to select candidates that improve short-distance or zero-transfer trips?

**Stop Rule:** Do not proceed until `notebooks/08_Theory_Sensitivity.ipynb` contains the requested plots and markdown proofs.
