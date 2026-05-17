# Runners

Runners serve as the high-level orchestration layer between the scheduled environment, Google Sheets, and the game clients.

While `scheduler.py` is responsible for account discovery and multiprocessing, the `runners.py` module defines the business logic for specific routines. 

## Architectural Boundary

**Important**: Runners do not interact with the game directly. All game execution logic (like clicking UI elements or applying specific configs to an `ok-script` task) has been extracted to the `ok_ww_automator.game_clients` module. Runners purely orchestrate the *when* and *why*.

## Daily Runner

`DailyRunner` manages the execution of the main daily login routine:
- Fetches `SheetRunConfig` from the Google Sheets store.
- Evaluates `run_daily` and `skip_daily_once` flags.
- Attempts sign-in and fetches initial metrics via the optional Waves API.
- Clears the skip-once flag if consumed.
- Delegates to the `DailyGameClient` to execute the game task.
- Orchestrates retry loops for transient game crashes.
- Persists the final outcome to the `DailyRuns` worksheet.
- Dispatches execution notifications.
- Requests a system shutdown if configured.

## Stamina Runner

`StaminaRunner` manages a separate, extra login dedicated solely to burning excess stamina.
- Fetches `SheetRunConfig`.
- Evaluates `run_stamina` and `skip_stamina_once` flags.
- Fetches current stamina via the Waves API (falling back to a quick game login and OCR read if the API is disabled or fails).
- Uses `time_utils.calculate_burn()` to intelligently decide if a stamina burn is necessary to prevent overflow before the next scheduled daily run.
- Skips launching the heavy game client entirely if no burn is needed.
- If a burn is needed, delegates to the `StaminaGameClient` to execute a domain or tacet field task.
- Persists the final outcome to the `StaminaRuns` worksheet.
- Dispatches execution notifications.