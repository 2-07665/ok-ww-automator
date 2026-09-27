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

## Download a release

Open [Releases](https://github.com/2-07665/ok-ww-automator/releases), download `OKAutomatorLauncher.exe` from the desired version's **Assets**, and place it in `ok-ww-automator\dist`. Release assets do not use the retention period of temporary Actions artifacts.

[Release Windows launcher](https://github.com/2-07665/ok-ww-automator/actions/workflows/build-launcher.yml) builds only when a tag starting with `v` is pushed. Ordinary branch pushes and pull requests do not trigger it. It uses Windows x64, Python 3.12, and the `launcher` and `build` dependencies locked in `uv.lock`. It runs the existing launcher tests and a GUI initialization check, then invokes the same build script used locally. The upstream checkout supplies only an icon from a pinned commit; CI does not install or run ok-script, game tasks, or OCR dependencies. After a successful build, it creates a release for that tag with generated release notes and the EXE attached.

When a release is needed, first commit the code and workflow to be released, then create and push a new version tag. For example:

```powershell
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Replace the example version with the new release version. CI builds the commit referenced by the tag; use the downloaded launcher with the matching source version. Let the workflow create the release instead of creating one with the same tag in the web UI beforehand. Failed builds can be retried in Actions; use a new tag for changes to an already published version.

Downloading the EXE avoids local compilation and PowerShell execution policy setup. The shared Python environment, both checkouts, and task configuration are still required as described in the installation guide. This artifact contains the launcher, not the complete automation environment; the GUI check does not validate actual game tasks.

## Local build

To build locally, install `uv` and arrange both checkouts as shown above. Run the following from the Automator directory. Use the first command only for initial setup when the shared `.venv` does not yet exist:

```powershell
uv venv --python 3.12 ..\.venv
uv pip install --python ..\.venv\Scripts\python.exe -e ".[launcher,build]"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\build_launcher.ps1
```

The last command sets execution policy only for that PowerShell process. The build script does not create an environment or install dependencies, so cloning alone is insufficient. Close any running launcher before replacing its EXE.

The script uses the existing `ok-wuthering-waves\icons\icon.ico`, temporarily narrows the build process's `PATH` to avoid bundling incompatible DLLs from other tools, and stores intermediate files in `build\launcher`. It produces one windowed, one-file executable:

```text
dist\OKAutomatorLauncher.exe
```

Ordinary updates to either checkout do not require a launcher rebuild. Rebuild only when launcher features change or when one of its stable contracts changes: `env/*.env` account profiles, repeated scheduler `--account` arguments, or the `ok_ww_automator.ok_main` / `ok_ww_automator.scheduler` module entrypoints. The scheduler retains its normal built-in upstream update behavior.
