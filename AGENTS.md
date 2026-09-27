# AGENTS.md

## Design Rules

1. **Keep upstream checkouts clean.** Make project changes in `ok-ww-automator` only.
2. **Minimize upstream coupling throughout the repository.** Every added upstream package, import, API call, configuration assumption, and compatibility patch must be necessary for a concrete project requirement.

## Repository and Runtime Assumptions

- `ok-ww-automator`, `ok-wuthering-waves`, and optionally `ok-script` are sibling checkouts under one workspace. `ok_launcher.py` temporarily adds the upstream checkout to `sys.path` and switches `cwd` so its relative `configs/`, `logs/`, and `screenshots/` paths resolve correctly.
- Use the shared parent virtual environment at `../.venv`; do not create `ok-ww-automator/.venv`.
- Prefer `uv run --active ...` when using uv. Plain `uv run` inside this project can create a local environment and rewrite `uv.lock`.
- WSL may show widespread sibling-checkout changes caused only by CRLF/LF normalization.
