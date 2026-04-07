# Phase 9: Experiments and Visualizations

**Objective:** Generate high-quality publication-ready figures representing the findings of the descriptive analysis and optimization models.

## Step-by-Step Instructions for AI Agent

### 9.1 Data Preparation for Plotting
- Write `src/viz/plot_generators.py`. Use `matplotlib` and `seaborn`. Set a consistent publication-ready style (e.g., `sns.set_style("whitegrid")`).

### 9.2 Descriptive Figures
1. **Historical Service Drift Chart:** A line chart showing the total system-wide scheduled service hours across the GTFS versions (from Phase 2). Mark the COVID-19 drop if applicable.
2. **Volatility Map:** A map of Seattle (using Geopandas/Folium) highlighting the transit routes or tracts that experienced the largest standard deviation in service levels.

### 9.3 Optimization Figures
3. **The Fairness Frontier:** The plot generated in Phase 8 (Efficiency vs. Equity tradeoff). Ensure axes are clearly labeled and stylized.
4. **Candidate Selection Map:** For a specific budget $B$ (e.g., a "Medium" budget), plot a map showing the "Current Network" in grey, and highlight the restored routes/segments in bright colors. Use line thickness to indicate the intensity of the restoration.
5. **Weather Robustness Bar Chart:** Compare the baseline vulnerable connectivity under "Heavy Rain" vs. the restored vulnerable connectivity under "Heavy Rain".

### 9.4 Output
- Save all generated figures as high-resolution PNG or PDF files in `reports/figures/`.
- Ensure files are named clearly, e.g., `fig1_service_drift.pdf`, `fig2_volatility_map.png`.

**Stop Rule:** Do not proceed until the `reports/figures/` directory contains at least 5 complete, styled plots.
