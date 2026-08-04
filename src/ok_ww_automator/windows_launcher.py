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

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox, ttk
except ModuleNotFoundError:  # Headless test environments may omit the optional Tk runtime.
    tk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

from .config import ConfigError, read_dotenv
from .env_discovery import AccountEnv, discover_account_envs


APP_NAME = "OK Automator Launcher"
MAX_LOG_LINES = 1_000
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DEFAULT_WINDOW_SIZE = (1_200, 900)
MINIMUM_WINDOW_SIZE = (950, 720)
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


def build_scheduler_command(paths: LauncherPaths, mode: str, account_ids: Sequence[str]) -> list[str]:
    if mode not in {"daily", "stamina"}:
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
) -> None:
    """Start one game directly and deliberately relinquish process ownership."""
    popen(
        [str(launch.executable)],
        cwd=str(launch.executable.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=CREATE_NO_WINDOW if platform_name == "nt" else 0,
    )


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

    def start(self, operation: str, command: Sequence[str], *, cwd: Path) -> None:
        with self._lock:
            if self._state != "idle":
                raise RuntimeError("Another launcher operation is already active.")
            self._state = "starting"
            self._operation = operation
            self._stop_requested = False

        child_env = dict(os.environ)
        child_env["PYTHONUNBUFFERED"] = "1"
        try:
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

        with self._lock:
            self._process = process
            self._state = "running"
        self.events.put(ProcessEvent("started", operation))
        threading.Thread(target=self._collect_output, args=(process, operation), daemon=True).start()

    def _collect_output(self, process: subprocess.Popen[str], operation: str) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self.events.put(ProcessEvent("output", operation, text=line))
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


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.paths: LauncherPaths | None = None
        self.accounts: list[AccountEnv] = []
        self.process = ManagedProcess()
        self._close_when_idle = False
        self._game_launch_cooldown = False

        self.status_text = tk.StringVar(value="Initializing…")
        self.mode = tk.StringVar(value="daily")
        self._configure_window()
        self._build_widgets()
        self._load_workspace()
        self.root.after(100, self._poll_events)

    def _configure_window(self) -> None:
        self.root.title(APP_NAME)
        width, height = DEFAULT_WINDOW_SIZE
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(*MINIMUM_WINDOW_SIZE)
        self.root.option_add("*Font", "{Segoe UI} 9")
        style = ttk.Style(self.root)
        for theme in ("vista", "winnative"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", padding=(8, 6))
        tree_font = tkfont.Font(self.root, family="Segoe UI", size=9)
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=tree_font.metrics("linespace") + 8)
        style.configure("Treeview.Heading", font=("Segoe UI", 9))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=2, minsize=MINIMUM_ACCOUNT_TABLE_HEIGHT)
        outer.rowconfigure(6, weight=3, minsize=MINIMUM_LOG_HEIGHT)

        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.ok_button = ttk.Button(outer, text="Launch OK GUI", command=self._launch_ok_gui)
        self.ok_button.grid(row=0, column=1, sticky="e")

        mode_frame = ttk.LabelFrame(outer, text="Scheduler mode", padding=8)
        mode_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        self.daily_radio = ttk.Radiobutton(mode_frame, text="Daily", value="daily", variable=self.mode)
        self.stamina_radio = ttk.Radiobutton(mode_frame, text="Stamina", value="stamina", variable=self.mode)
        self.daily_radio.pack(side="left", padx=(0, 16))
        self.stamina_radio.pack(side="left")
        self.scheduler_button = ttk.Button(mode_frame, text="Run selected accounts", command=self._launch_scheduler)
        self.scheduler_button.pack(side="right")

        ttk.Label(outer, text="Accounts (run top to bottom)").grid(row=2, column=0, columnspan=2, sticky="w")
        account_frame = ttk.Frame(outer)
        account_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        account_frame.rowconfigure(0, weight=1)
        account_frame.columnconfigure(0, weight=1)
        self.account_table = ttk.Treeview(
            account_frame,
            columns=("account", "file"),
            show="headings",
            selectmode="extended",
            height=7,
        )
        self.account_table.heading("account", text="Account")
        self.account_table.heading("file", text="Profile")
        self.account_table.column("account", width=180, stretch=False)
        self.account_table.column("file", width=460, stretch=True)
        scrollbar = ttk.Scrollbar(account_frame, orient="vertical", command=self.account_table.yview)
        self.account_table.configure(yscrollcommand=scrollbar.set)
        self.account_table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.account_table.bind("<<TreeviewSelect>>", lambda _event: self._sync_controls())

        controls = ttk.Frame(outer)
        controls.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 10))
        self.account_buttons = [
            ttk.Button(controls, text="Select All", command=self._select_all),
            ttk.Button(controls, text="Clear", command=self._clear_selection),
            ttk.Button(controls, text="Refresh", command=self._refresh_accounts),
            ttk.Button(controls, text="Move Up", command=lambda: self._move_accounts(-1)),
            ttk.Button(controls, text="Move Down", command=lambda: self._move_accounts(1)),
        ]
        self.game_button = ttk.Button(controls, text="Launch Game", command=self._launch_selected_game)
        self.account_buttons.append(self.game_button)
        for index, button in enumerate(self.account_buttons):
            controls.columnconfigure(index, weight=1, uniform="account_controls")
            button.grid(
                row=0,
                column=index,
                sticky="ew",
                padx=(0, 6) if index < len(self.account_buttons) - 1 else 0,
            )

        status_frame = ttk.Frame(outer)
        status_frame.grid(row=5, column=0, columnspan=2, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_text, relief="sunken", anchor="w", style="Status.TLabel").grid(
            row=0, column=0, sticky="ew"
        )
        self.stop_button = ttk.Button(status_frame, text="Stop", command=self._request_stop)
        self.stop_button.grid(row=0, column=1, padx=(8, 0))

        log_frame = ttk.LabelFrame(outer, text="Live log", padding=6)
        log_frame.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", state="disabled", height=12, font=("Consolas", 9))
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scrollbar.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scrollbar.grid(row=0, column=1, sticky="ns")

    def _load_workspace(self) -> None:
        try:
            self.paths = discover_launcher_paths(launcher_start_path())
        except LauncherConfigurationError as exc:
            self.status_text.set("Configuration error")
            self._append_log(f"{exc}\n")
            self._sync_controls()
            return
        self._refresh_accounts()
        self.status_text.set(f"Ready — {self.paths.workspace_root}")

    def _refresh_accounts(self) -> None:
        for item in self.account_table.get_children():
            self.account_table.delete(item)
        self.accounts = discover_account_envs(self.paths.automator_root / "env") if self.paths else []
        for account in self.accounts:
            self.account_table.insert("", "end", iid=account.account_id, values=(account.account_id, account.path.name))
        self._select_all()
        if self.paths and not self.accounts:
            self.status_text.set(f"No account profiles found in {self.paths.automator_root / 'env'}")
        self._sync_controls()

    def _displayed_accounts(self) -> list[AccountEnv]:
        by_id = {account.account_id: account for account in self.accounts}
        return [by_id[item] for item in self.account_table.get_children()]

    def _selected_ids(self) -> list[str]:
        return selected_account_ids(self._displayed_accounts(), self.account_table.selection())

    def _select_all(self) -> None:
        items = self.account_table.get_children()
        if items:
            self.account_table.selection_set(items)
        self._sync_controls()

    def _clear_selection(self) -> None:
        self.account_table.selection_remove(self.account_table.selection())
        self._sync_controls()

    def _move_accounts(self, direction: int) -> None:
        selected = set(self.account_table.selection())
        items = list(self.account_table.get_children())
        if direction < 0:
            for index in range(1, len(items)):
                if items[index] in selected and items[index - 1] not in selected:
                    items[index - 1], items[index] = items[index], items[index - 1]
        else:
            for index in range(len(items) - 2, -1, -1):
                if items[index] in selected and items[index + 1] not in selected:
                    items[index], items[index + 1] = items[index + 1], items[index]
        for index, item in enumerate(items):
            self.account_table.move(item, "", index)

    def _launch_ok_gui(self) -> None:
        if self.paths is None:
            return
        self._start_operation("OK GUI", build_ok_gui_command(self.paths))

    def _launch_scheduler(self) -> None:
        if self.paths is None:
            return
        try:
            command = build_scheduler_command(self.paths, self.mode.get(), self._selected_ids())
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc), parent=self.root)
            return
        self._start_operation(f"{self.mode.get().title()} scheduler", command)

    def _launch_selected_game(self) -> None:
        if self.paths is None or self._game_launch_cooldown:
            return
        try:
            launch = build_game_launch(self._displayed_accounts(), self.account_table.selection())
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc), parent=self.root)
            return

        self._game_launch_cooldown = True
        self._sync_controls()
        try:
            launch_game(launch)
        except OSError as exc:
            self.status_text.set(f"Failed to launch game: {exc}")
            self._append_log(f"ERROR launching game: {exc}\n")
        else:
            self.status_text.set(f"Launched game for: {launch.account_id}")
            self._append_log(f"Launched {launch.account_id}: {launch.executable}\n")
        self.root.after(GAME_LAUNCH_COOLDOWN_MS, self._finish_game_launch_cooldown)

    def _finish_game_launch_cooldown(self) -> None:
        self._game_launch_cooldown = False
        self._sync_controls()

    def _start_operation(self, operation: str, command: Sequence[str]) -> None:
        if self.paths is None:
            return
        self._append_log(f"\n> {subprocess.list2cmdline(list(command))}\n")
        self.status_text.set(f"Starting {operation}…")
        try:
            self.process.start(operation, command, cwd=self.paths.workspace_root)
        except Exception as exc:
            self.status_text.set(f"Failed to start {operation}: {exc}")
            self._append_log(f"ERROR: {exc}\n")
        self._sync_controls()

    def _request_stop(self) -> None:
        if not self.process.is_active:
            return
        if messagebox.askyesno(APP_NAME, "Stop the active operation and all of its child processes?", parent=self.root):
            self.status_text.set("Stopping…")
            try:
                self.process.stop()
            except Exception as exc:
                self.status_text.set(f"Stop failed: {exc}")
                self._append_log(f"ERROR stopping process tree: {exc}\n")
            self._sync_controls()

    def _on_close(self) -> None:
        if not self.process.is_active:
            self.root.destroy()
            return
        if not messagebox.askyesno(
            APP_NAME,
            "An operation is still active. Stop it and close the launcher?",
            parent=self.root,
        ):
            return
        self._close_when_idle = True
        self.status_text.set("Stopping before close…")
        try:
            self.process.stop()
        except Exception as exc:
            self._close_when_idle = False
            self.status_text.set(f"Stop failed: {exc}")
            self._append_log(f"ERROR stopping process tree: {exc}\n")

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.process.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "output":
                self._append_log(event.text)
            elif event.kind == "started":
                self.status_text.set(f"Running {event.operation}…")
            elif event.kind == "stopping":
                self.status_text.set(f"Stopping {event.operation}…")
            elif event.kind == "finished":
                if event.text == "completed":
                    self.status_text.set(f"Completed {event.operation}")
                elif event.text == "stopped":
                    self.status_text.set(f"Stopped {event.operation}")
                elif event.returncode is None:
                    self.status_text.set(f"Failed to start {event.operation}: {event.text}")
                else:
                    self.status_text.set(f"Failed {event.operation} (exit code {event.returncode})")
        self._sync_controls()
        if self._close_when_idle and not self.process.is_active:
            self.root.destroy()
            return
        self.root.after(100, self._poll_events)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        line_count = int(self.log.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self.log.delete("1.0", f"{line_count - MAX_LOG_LINES + 1}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _sync_controls(self) -> None:
        active = self.process.is_active
        valid = self.paths is not None
        selection_count = len(self.account_table.selection())
        selected = selection_count > 0
        self.ok_button.configure(state="normal" if valid and not active else "disabled")
        self.scheduler_button.configure(state="normal" if valid and selected and not active else "disabled")
        self.stop_button.configure(state="normal" if active else "disabled")
        state = "disabled" if active else "normal"
        self.daily_radio.configure(state=state)
        self.stamina_radio.configure(state=state)
        self.account_table.configure(selectmode="none" if active else "extended")
        for button in self.account_buttons:
            button.configure(state=state)
        self.game_button.configure(
            state="normal"
            if valid and selection_count == 1 and not active and not self._game_launch_cooldown
            else "disabled"
        )


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main() -> int:
    if tk is None:
        raise RuntimeError("Tkinter is required to run OK Automator Launcher.")
    enable_windows_dpi_awareness()
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
