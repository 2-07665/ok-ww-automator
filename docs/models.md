# Data Models

The `src/ok_ww_automator/models.py` module defines pure Python data structures. By design, this module has **zero dependencies** on Google Sheets, network libraries, or game-specific launchers. 

## Core Models

1. **`SheetRunConfig`**: A dataclass that holds the parsed configuration retrieved from the Google Sheets `Config` worksheet. 
2. **`RunResult`**: Tracks the execution outcome of daily and stamina tasks. It calculates derived metrics like `duration`, `stamina_used`, and predicts the stamina available at the next daily reset.
3. **`FastFarmResult`**: Tracks the execution outcome of the Echo fast-farming loop (e.g., 5-to-1 fusions).

## Explicit Serialization

Models handle their own serialization for Google Sheets via explicit methods rather than hiding the dependency:
- `RunResult.as_daily_row()` -> Formats the row for `DailyRuns`
- `RunResult.as_stamina_row()` -> Formats the row for `StaminaRuns`
- `FastFarmResult.as_row()` -> Formats the row for `5to1`

## Time Utilities

Time and stamina calculations reside in `src/ok_ww_automator/time_utils.py`. The module assumes:
- **Current Stamina Cap**: 240
- **Backup Stamina Cap**: 480
- **Regeneration**: 1 per 6 minutes (Current), 1 per 12 minutes (Backup)
- **Timezone**: All internal target evaluations use Beijing Time (UTC+08:00) to align with server resets.