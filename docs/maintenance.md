# Maintenance and upstream updates

The upstream boundary is intentionally small: scheduler/runners own decisions, `game_clients.py` translates them into game tasks, and `ok_launcher.py` drives OK. Custom tasks under `ok_tasks/` use upstream input, capture and OCR. Keep changes in Automator; the sibling repositories are dependencies.

## Doctor

From the Automator root, use the shared Windows Python:

```powershell
..\.venv\Scripts\python.exe -m ok_ww_automator.doctor --strict
..\.venv\Scripts\python.exe -m ok_ww_automator.doctor --check-remote --strict
```

The default inspects **the installed `ok` package**, compares its distribution version with the game checkout's requirements, and checks Python/Windows dependencies. It parses source without importing upstream or starting OK. It does not load account secrets, modify checkouts, launch the game, or call notification services. `--check-remote` additionally queries GitHub HEAD with bounded read-only Git requests. Network failure produces a warning, not a false “current” result.

To review an `ok-script` checkout separately:

```powershell
..\.venv\Scripts\python.exe -m ok_ww_automator.doctor --source-only --ok-script-root ..\ok-script --strict
```

On Linux: `PYTHONPATH=src python3 -m ok_ww_automator.doctor --source-only --ok-script-root ../ok-script --strict`. `--ww-root` selects another game checkout. `--json` emits findings for tooling. Source mode does not certify the installed Windows runtime.

| Result | Meaning |
| --- | --- |
| `PASS` | The particular automated check passed. |
| `FAIL` | Missing source, dependency or incompatible API/configuration; exit code 1. |
| `WARN` | A reviewed implementation changed or remote state needs review; exit code 1 with `--strict`. |
| `MANUAL` | A known assumption requires a live or human check; never presented as an automated pass. |

`src/ok_ww_automator/upstream_contracts.json` inventories signatures, task registration, selector ordering, configuration keys, exact completion/error strings, required feature labels, and reviewed behavior fingerprints. Hashes ignore comments and formatting. They detect implementation drift; they cannot establish semantic compatibility. Structural checks of dynamic configuration are deliberately conservative and may require a doctor update after a harmless refactor.

Reviewed on 2026-09-27 against remote default-branch HEADs:

- [ok-wuthering-waves 61bfa64b](https://github.com/ok-oldking/ok-wuthering-waves/commit/61bfa64b2f19eb646a5a3b00974b5b5760d887db), requiring `ok-script[ocr,qt]==2.0.7b1`.
- [ok-script d74ba2bf](https://github.com/ok-oldking/ok-script/commit/d74ba2bff6ef07c120b193f99bd6497753d0f1be).

## Upgrade procedure

1. Record local modifications, upstream revisions and the installed package version before updating. Verify current remote HEADs; a sibling checkout can differ from the installed wheel.
2. Run the doctor against the installation and intended source revision. Review failing or changed contracts in upstream and their Automator callers.
3. Adapt callers and add a regression for the observable break. Refresh only reviewed fingerprints and record the actual reviewed revisions. Do not regenerate the baseline to silence warnings.
4. Install the updated upstream requirements into `..\.venv\Scripts\python.exe`, rerun both doctor modes, and run the tests below. The scheduler updater performs fast-forward-only Git updates and explicitly targets its current interpreter; local conflicts stop the update.
5. Check the affected live behavior when appropriate: launch/capture/cancellation, localized errors, stamina OCR, weekly success, or custom tasks. Report omitted checks. Chinese OCR regions, game balance/timing, Kuro response schemas, credentials, and network services cannot be validated by a source scan.

The project Codex skill is [align-upstream](../.agents/skills/align-upstream/SKILL.md). Invoke `$align-upstream` when reviewing an upstream upgrade.

## Tests

```powershell
..\.venv\Scripts\python.exe -m unittest discover -s tests
```

The core suite uses only the standard library; Linux source checks can use `PYTHONPATH=src python3 -m unittest discover -s tests`. CI runs it on Windows and Linux. Tests should protect decisions, retries, state persistence, parsing, process cleanup and failure reporting. An assertion that repeats a default, dataclass field, UI label or build-script text is not useful coverage by itself. Doctor tests deliberately mutate signatures, configuration and completion behavior to demonstrate detection.

## Launcher builds and releases

Rebuild when `launcher_ui.py`, `windows_launcher.py`, bundled discovery/progress helpers, the subprocess CLI contract, or build dependencies change. Ordinary task implementation updates remain external source and do not need rebuilding.

```powershell
uv pip install --python ..\.venv\Scripts\python.exe -e ".[launcher,build]"
$env:QT_QPA_PLATFORM = "offscreen"
..\.venv\Scripts\python.exe -c "from PySide6.QtWidgets import QApplication; from ok_ww_automator.launcher_ui import LauncherWindow; app = QApplication([]); window = LauncherWindow(); window.close()"
Remove-Item Env:QT_QPA_PLATFORM
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build_launcher.ps1
```

The output is `dist/OKAutomatorLauncher.exe`; PyInstaller uses the sibling upstream icon. The executable still requires the external checkouts and shared Python at runtime. The manifest requests UAC elevation. A GUI initialization smoke test does not test live game automation.

After reviewed commits are pushed, create a new annotated `v*` tag and push it when a release is requested. `.github/workflows/build-launcher.yml` installs locked build dependencies, runs tests, checks offscreen GUI initialization, builds on Windows and publishes the EXE. Ordinary branch pushes run checks but do not release. Never overwrite an existing release tag.
