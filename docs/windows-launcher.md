# OK Automator Launcher (Windows)

`OK Automator Launcher` is a small elevated desktop front end for the existing Automator entrypoints. It discovers profiles from `env/*.env`, launches the regular OK GUI or one selected account's game, and runs Daily or Stamina scheduling for selected accounts in the displayed order. It does not install, repair, activate, or update Python environments.

## Workspace and executable placement

The launcher requires this sibling layout:

```text
<workspace>\
├── .venv\Scripts\python.exe
├── ok-ww-automator\
└── ok-wuthering-waves\
```

Place `OKAutomatorLauncher.exe` either in `ok-ww-automator` or in `ok-ww-automator\dist`. The launcher searches its directory and parent directories for the Automator checkout, validates all three paths, and leaves launch actions disabled if the layout is incomplete.

The shared virtual environment must have `ok-ww-automator` and the upstream requirements installed as described in the main setup guide. The executable deliberately invokes `<workspace>\.venv\Scripts\python.exe`; it does not contain or substitute for the automation runtime.

## UAC and process behavior

The executable contains a `requireAdministrator` manifest, so Windows requests elevation every time it starts. Its child Python, scheduler, game, and helper processes inherit the elevated security context. Because the executable is unsigned, Windows can show an unknown-publisher warning.

Only one launcher operation can run at a time. Standard output and errors are combined in the bounded live log. Choosing **Stop**, or confirming a window close while an operation is active, uses Windows process-tree termination so scheduler subprocesses and game children are not left behind.

Every refresh selects all discovered account profiles. `.env.example` is excluded; `.env` is shown as `default`; and names such as `CN.env` retain their exact case. Selection, ordering, and mode are intentionally reset between launcher sessions.

**Launch Game** is enabled only when exactly one account is selected. It validates that profile's `GAME_EXE_PATH`, then starts the executable directly. Account multi-selection remains available for scheduler runs. Game launching is intentionally separate from managed Automator operations: it does not detect or close an already-running game, and the launcher does not monitor, stop, or otherwise control a game after starting it. The button is disabled for three seconds after use to prevent accidental rapid repeat launches.

## Build

Use native Windows Python 3.12 in the shared virtual environment. Install the build extra, then run the PowerShell build script from the Automator checkout:

```powershell
uv pip install --python ..\.venv\Scripts\python.exe -e ".[build]"
.\windows\build_launcher.ps1
```

The script uses the existing `ok-wuthering-waves\icons\icon.ico` and produces one windowed, one-file executable:

```text
dist\OKAutomatorLauncher.exe
```

Ordinary updates to either checkout do not require a launcher rebuild. Rebuild only when launcher features change or when one of its stable contracts changes: `env/*.env` account profiles, repeated scheduler `--account` arguments, or the `ok_ww_automator.ok_main` / `ok_ww_automator.scheduler` module entrypoints. The scheduler retains its normal built-in upstream update behavior.
