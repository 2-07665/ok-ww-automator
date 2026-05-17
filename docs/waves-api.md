# Waves API

The `src/ok_ww_automator/waves_api.py` module integrates with the Kuro/Waves community API to provide fast, headless checks for daily tasks.

This integration is completely optional and loads the `requests` library lazily.

## Capabilities

- **Daily Sign-In**: Executes the community sign-in action (`sign_in()`).
- **Live Metrics**: Fetches current stamina, backup stamina (crystallized ether), and daily activity points (`read_daily_info()`).
- **Robust Error Handling**: Wraps HTTP and JSON parsing errors into a consistent structured dictionary to prevent pipeline crashes.

## Orchestration Flow

When `WAVES_API_ENABLED=true` is set in the environment:

1. **Daily Runner**: 
   Attempts API sign-in and fetches initial metrics. These metrics are attached to the run report. Note that live game reads (via OCR) will still override API stamina values once the game launches.
   
2. **Stamina Runner**: 
   Queries the API first to determine current stamina levels. By doing this, the runner can execute the `calculate_burn` logic entirely headless. **If no stamina burn is required, the automator will skip launching the heavy game client entirely.** If the API fails or is disabled, the runner gracefully falls back to launching the game and using OCR to read stamina.