"""Elevated Windows GUI for launching the public Automator entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Callable, Iterable, Sequence

from .config import ConfigError, read_dotenv
from .env_discovery import AccountEnv, discover_account_envs
from .farm_progress import FarmProgress, read_progress
from .time_utils import parse_time_of_day


APP_NAME = "OK Automator Launcher"
MAX_LOG_LINES = 1_000
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DEFAULT_WINDOW_SIZE = (1_200, 900)
MINIMUM_WINDOW_SIZE = (950, 800)
MINIMUM_ACCOUNT_TABLE_HEIGHT = 190
MINIMUM_LOG_HEIGHT = 260
GAME_LAUNCH_COOLDOWN_MS = 3_000


class LauncherConfigurationError(RuntimeError):
    """Raised when the launcher cannot use the surrounding workspace."""


@dataclass(frozen=True)
class LauncherPaths:
    workspace_root: Path
    automator_root: Path
    upstream_root: Path
    python_exe: Path


@dataclass(frozen=True)
class ProcessEvent:
    kind: str
    operation: str
    text: str = ""
    returncode: int | None = None
    progress: FarmProgress | None = None


@dataclass(frozen=True)
class GameLaunch:
    account_id: str
    executable: Path


def is_automator_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "src" / "ok_ww_automator" / "scheduler.py").is_file()
        and (path / "env").is_dir()
    )


def find_automator_root(start_path: Path) -> Path:
    """Find the Automator checkout from an executable, source file, or directory."""
    start = Path(start_path).resolve()
    directory = start.parent if start.is_file() or start.suffix.lower() == ".exe" else start
    for candidate in (directory, *directory.parents):
        if is_automator_root(candidate):
            return candidate
    raise LauncherConfigurationError(
        f"Could not find the ok-ww-automator project from {directory}. "
        "Place the executable in the project root or its dist folder."
    )


def discover_launcher_paths(start_path: Path) -> LauncherPaths:
    automator_root = find_automator_root(start_path)
    workspace_root = automator_root.parent
    paths = LauncherPaths(
        workspace_root=workspace_root,
        automator_root=automator_root,
        upstream_root=workspace_root / "ok-wuthering-waves",
        python_exe=workspace_root / ".venv" / "Scripts" / "python.exe",
    )
    errors = validate_launcher_paths(paths)
    if errors:
        raise LauncherConfigurationError("Invalid workspace layout:\n" + "\n".join(f"- {error}" for error in errors))
    return paths


def validate_launcher_paths(paths: LauncherPaths) -> list[str]:
    errors = []
    if not paths.python_exe.is_file():
        errors.append(f"Missing shared Python interpreter: {paths.python_exe}")
    if not paths.automator_root.is_dir():
        errors.append(f"Missing Automator checkout: {paths.automator_root}")
    if not paths.upstream_root.is_dir():
        errors.append(f"Missing upstream checkout: {paths.upstream_root}")
    return errors


def launcher_start_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(__file__)


def build_ok_gui_command(paths: LauncherPaths) -> list[str]:
    return [
        str(paths.python_exe),
        "-m",
        "ok_ww_automator.ok_main",
        "--ww-root",
        str(paths.upstream_root),
    ]


def build_auto_farm_command(paths: LauncherPaths, stop_time: str) -> list[str]:
    stop_time = parse_time_of_day(stop_time).strftime("%H:%M")
    return [
        str(paths.python_exe), "-m", "ok_ww_automator.auto_farm",
        "--ww-root", str(paths.upstream_root), "--stop-time", stop_time,
    ]


def build_scheduler_command(paths: LauncherPaths, mode: str, account_ids: Sequence[str]) -> list[str]:
    if mode not in {"daily", "stamina", "weekly", "stamina-weekly"}:
        raise ValueError(f"Unsupported scheduler mode: {mode}")
    if not account_ids:
        raise ValueError("Select at least one account.")

    command = [
        str(paths.python_exe),
        "-m",
        "ok_ww_automator.scheduler",
        "--project-root",
        str(paths.automator_root),
        "--ww-root",
        str(paths.upstream_root),
        "--mode",
        mode,
    ]
    if mode == "weekly":
        command.append("--run-now")
    for account_id in account_ids:
        command.extend(("--account", account_id))
    return command


def selected_account_ids(accounts: Sequence[AccountEnv], selected_ids: Iterable[str]) -> list[str]:
    """Return selected IDs in displayed account order, validating the selection."""
    selected = set(selected_ids)
    known = {account.account_id for account in accounts}
    unknown = sorted(selected - known)
    if unknown:
        raise ValueError(f"Unknown account env: {', '.join(unknown)}")
    ordered = [account.account_id for account in accounts if account.account_id in selected]
    if not ordered:
        raise ValueError("Select at least one account.")
    return ordered


def build_game_launch(accounts: Sequence[AccountEnv], selected_ids: Iterable[str]) -> GameLaunch:
    """Resolve the game executable for exactly one selected account."""
    ordered_ids = selected_account_ids(accounts, selected_ids)
    if len(ordered_ids) != 1:
        raise ValueError("Select exactly one account to launch its game.")
    by_id = {account.account_id: account for account in accounts}
    account_id = ordered_ids[0]
    account = by_id[account_id]
    try:
        raw_path = read_dotenv(account.path).get("GAME_EXE_PATH", "").strip()
    except (ConfigError, OSError, UnicodeError) as exc:
        raise ValueError(f"Account {account_id}: {exc}") from exc
    if not raw_path:
        raise ValueError(f"Account {account_id}: GAME_EXE_PATH is missing.")
    executable = Path(raw_path).expanduser()
    if not executable.is_file():
        raise ValueError(f"Account {account_id}: game executable not found: {executable}")
    return GameLaunch(account_id=account_id, executable=executable.resolve())


def launch_game(
    launch: GameLaunch,
    *,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    platform_name: str = os.name,
    dll_directory_setter: Callable[[str | None], None] | None = None,
) -> None:
    """Start one game directly and deliberately relinquish process ownership."""
    restore_dll_directory: str | None = None
    if platform_name == "nt" and getattr(sys, "frozen", False):
        # PyInstaller one-file sets this to _MEIPASS. Do not let an independent
        # game load and lock the launcher's temporary VCRUNTIME DLLs.
        restore_dll_directory = str(getattr(sys, "_MEIPASS", "")) or None
        if dll_directory_setter is None:
            dll_directory_setter = set_windows_dll_directory
        dll_directory_setter(None)
    try:
        popen(
            [str(launch.executable)],
            cwd=str(launch.executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=CREATE_NO_WINDOW if platform_name == "nt" else 0,
        )
    finally:
        if dll_directory_setter is not None and restore_dll_directory is not None:
            dll_directory_setter(restore_dll_directory)


def set_windows_dll_directory(path: str | None) -> None:
    """Set the process DLL search override used by PyInstaller on Windows."""
    import ctypes

    if not ctypes.windll.kernel32.SetDllDirectoryW(path):
        raise ctypes.WinError()


class ManagedProcess:
    """Own one child operation and stream its merged output through a queue."""

    def __init__(
        self,
        *,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        platform_name: str = os.name,
    ) -> None:
        self.events: queue.Queue[ProcessEvent] = queue.Queue()
        self._popen = popen
        self._run = run
        self._platform_name = platform_name
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._operation = ""
        self._stop_requested = False
        self._state = "idle"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_active(self) -> bool:
        return self.state != "idle"

    def start(self, operation: str, command: Sequence[str], *, cwd: Path, log_path: Path | None = None) -> None:
        with self._lock:
            if self._state != "idle":
                raise RuntimeError("Another launcher operation is already active.")
            self._state = "starting"
            self._operation = operation
            self._stop_requested = False

        child_env = dict(os.environ)
        child_env["PYTHONUNBUFFERED"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        restore_dll_directory = None
        if self._platform_name == "nt" and getattr(sys, "frozen", False):
            restore_dll_directory = str(sys._MEIPASS)
            # The external Python runtime must load its own Qt, not the frozen GUI's.
            for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
                child_env.pop(key, None)
            child_env["PATH"] = os.pathsep.join(
                path for path in child_env.get("PATH", "").split(os.pathsep)
                if os.path.normcase(path) != os.path.normcase(restore_dll_directory)
            )
        try:
            if restore_dll_directory is not None:
                set_windows_dll_directory(None)
            process = self._popen(
                list(command),
                cwd=str(cwd),
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=CREATE_NO_WINDOW if self._platform_name == "nt" else 0,
            )
        except Exception as exc:
            with self._lock:
                self._state = "idle"
            self.events.put(ProcessEvent("finished", operation, text=str(exc), returncode=None))
            raise
        finally:
            if restore_dll_directory is not None:
                set_windows_dll_directory(restore_dll_directory)

        with self._lock:
            self._process = process
            self._state = "running"
        self.events.put(ProcessEvent("started", operation))
        threading.Thread(target=self._collect_output, args=(process, operation, log_path), daemon=True).start()

    def _collect_output(self, process: subprocess.Popen[str], operation: str, log_path: Path | None = None) -> None:
        log_file = None
        if log_path is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = log_path.open("w", encoding="utf-8", buffering=1)
            except OSError as exc:
                self.events.put(ProcessEvent("output", operation, text=f"Unable to save log: {exc}\n"))
        if process.stdout is not None:
            for line in process.stdout:
                if log_file is not None:
                    try:
                        log_file.write(line)
                    except OSError:
                        log_file.close()
                        log_file = None
                progress = read_progress(line) if operation == "Auto Farm" else None
                if progress is not None:
                    self.events.put(ProcessEvent("progress", operation, progress=progress))
                else:
                    self.events.put(ProcessEvent("output", operation, text=line))
        if log_file is not None:
            log_file.close()
        returncode = process.wait()
        with self._lock:
            stopped = self._stop_requested
            if self._process is process:
                self._process = None
                self._state = "idle"
        outcome = "stopped" if stopped else ("completed" if returncode == 0 else "failed")
        self.events.put(ProcessEvent("finished", operation, text=outcome, returncode=returncode))

    def stop(self) -> bool:
        with self._lock:
            process = self._process
            if process is None or self._state == "idle":
                return False
            self._stop_requested = True
            self._state = "stopping"
            operation = self._operation

        self.events.put(ProcessEvent("stopping", operation))
        if self._platform_name == "nt":
            result = self._run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode != 0 and process.poll() is None:
                process.terminate()
        elif process.poll() is None:
            process.terminate()
        return True



def main() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setFontFamilies, setTheme, setThemeColor
    from .launcher_ui import LauncherWindow

    app = QApplication(sys.argv)
    font = QFont("Microsoft YaHei UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)
    setFontFamilies(["Microsoft YaHei UI", "Segoe UI"])
    setTheme(Theme.LIGHT)
    setThemeColor("#087f8c")
    window = LauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
