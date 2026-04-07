# Phase 4: NOAA Weather Scenarios

**Objective:** Process historical weather data to define discrete seasonal weather states and their probabilities, and assign theoretical walk/transfer friction penalties to each state.

## Step-by-Step Instructions for AI Agent

### 4.1 Define Weather States
- Write `src/weather/weather_processor.py`.
- Load `data/raw/noaa/seattle_daily_weather.csv`.
- Create a rule-based categorization to classify every day in the dataset into one of the following mutually exclusive states:
  - `Dry / Normal`: No rain, moderate temperatures.
  - `Light Rain`: PRCP > 0 but < 0.2 inches.
  - `Heavy Rain`: PRCP >= 0.2 inches.
  - `Cold/Windy`: TMAX < 40°F or AWND > high threshold.
  - `Heat`: TMAX > 85°F.

### 4.2 Calculate Seasonal Probabilities ($p_s$)
- Group the classified days by Month (or Quarter).
- Calculate the probability $p_s$ of each weather state $s$ occurring in each month.
- For the optimization model, we will likely use an "Annual Average" or a specific "Winter" vs "Summer" seasonal profile. Compute these aggregate probabilities.
- Save to `data/processed/weather_probabilities.csv`.

### 4.3 Define Access/Transfer Friction Parameters
- Define a JSON configuration `src/weather/friction_params.json` containing the penalties associated with each weather state. This replaces explicit network routing.
  - *Example:*
    - `Dry`: walk_speed_multiplier = 1.0, max_walk_distance = 800m, transfer_penalty_mins = 5
    - `Heavy Rain`: walk_speed_multiplier = 0.8, max_walk_distance = 400m, transfer_penalty_mins = 10
    - `Heat`: walk_speed_multiplier = 0.7, max_walk_distance = 600m, transfer_penalty_mins = 8

### 4.4 Output Validation
- Generate `notebooks/04_NOAA_Weather.ipynb`.
- Create bar charts showing the distribution of weather states by month, and print the penalty matrix.

**Stop Rule:** Do not proceed until `weather_probabilities.csv` and `friction_params.json` are created.
