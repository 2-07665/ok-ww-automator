"""Lazy adapter for launching ok-wuthering-waves through ok-script."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Iterator, Protocol

from .config import AppConfig


class OkLaunchError(RuntimeError):
    """Raised when the OK runtime cannot be started or driven."""


class DeviceManager(Protocol):
    capture_method: Any
    interaction: Any

    def do_refresh(self, current: bool = False) -> None: ...

    def get_devices(self) -> list[dict[str, Any]]: ...

    def get_preferred_device(self) -> dict[str, Any] | None: ...

    def set_preferred_device(self, imei: str | None = None, index: int = -1) -> None: ...

    def stop_hwnd(self) -> None: ...


class TaskExecutor(Protocol):
    exit_event: Any
    current_task: Any

    def start(self) -> None: ...


class OkRuntime(Protocol):
    device_manager: DeviceManager
    task_executor: TaskExecutor

    def quit(self) -> None: ...


@dataclass(frozen=True)
class OkLaunchOptions:
    ww_root: Path
    game_exe_path: Path
    launch_wait_seconds: float = 300.0
    ready_timeout_seconds: float = 120.0
    ready_poll_seconds: float = 5.0
    start_attempts: int = 2
    restart_settle_seconds: float = 10.0


@dataclass(frozen=True)
class RuntimeImports:
    ok_class: type
    config: dict[str, Any]
    process_execute: Callable[[str], Any]


def install_runtime_safety_patches() -> None:
    """Patch upstream ok-script frame handling for transient capture gaps."""
    try:
        task_module = importlib.import_module("ok.task.task")
    except Exception:
        return

    find_feature_class = getattr(task_module, "FindFeature", None)
    if find_feature_class is None or getattr(find_feature_class, "_ok_ww_missing_frame_patch", False):
        return

    original_find_feature = find_feature_class.find_feature

    def find_feature_with_missing_frame_guard(self, *args, **kwargs):
        frame = kwargs.get("frame")
        if frame is None:
            frame = getattr(getattr(self, "executor", None), "frame", None)
        if frame is None or not hasattr(frame, "shape"):
            return []
        return original_find_feature(self, *args, **kwargs)

    find_feature_class.find_feature = find_feature_with_missing_frame_guard
    find_feature_class._ok_ww_missing_frame_patch = True


class OkLauncher:
    def __init__(
        self,
        options: OkLaunchOptions,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.options = options
        self.sleep = sleep
        self.monotonic = monotonic

    @classmethod
    def from_app_config(cls, app_config: AppConfig, *, ww_root: Path) -> "OkLauncher":
        return cls(
            OkLaunchOptions(
                ww_root=ww_root,
                game_exe_path=app_config.require_game_exe_path(),
            )
        )

    def start_ok(self) -> OkRuntime:
        with ww_runtime_context(self.options.ww_root):
            imports = load_runtime_imports(self.options.ww_root)
            headless_config = dict(imports.config)
            headless_config["use_gui"] = False
            ok = imports.ok_class(headless_config)
        if getattr(ok, "task_executor", None) is None:
            raise OkLaunchError("OK initialized without a task executor")
        return ok

    def start_ok_and_game(self) -> OkRuntime:
        kill_game_processes()
        last_error: Exception | None = None
        for attempt in range(1, self.options.start_attempts + 1):
            ok: OkRuntime | None = None
            try:
                ok = self.start_ok()
                self.ensure_game_ready(ok)
                return ok
            except Exception as exc:
                last_error = exc
                if ok is not None:
                    stop_ok_runtime(ok)
                kill_game_processes()
                if attempt < self.options.start_attempts:
                    self.sleep(self.options.restart_settle_seconds)

        if last_error is not None:
            raise OkLaunchError(
                f"OK was not ready after {self.options.start_attempts:g} launch attempt(s): {last_error}"
            ) from last_error
        raise OkLaunchError("OK was not ready")

    def ensure_game_ready(self, ok: OkRuntime) -> None:
        device_manager = ok.device_manager
        preferred = refresh_and_select_connected_device(device_manager)

        if not preferred or not preferred.get("connected"):
            imports = load_runtime_imports(self.options.ww_root)
            imports.process_execute(str(self.options.game_exe_path))
            self.wait_for_game_window(ok)

        self.refresh_until_ready(ok)

    def wait_for_game_window(self, ok: OkRuntime) -> None:
        deadline = self.monotonic() + self.options.launch_wait_seconds
        while self.monotonic() < deadline:
            preferred = refresh_and_select_connected_device(ok.device_manager)
            if preferred and preferred.get("connected"):
                return
            self.sleep(self.options.ready_poll_seconds)
        raise OkLaunchError(f"Game window was not connected within {self.options.launch_wait_seconds:g} seconds")

    def refresh_until_ready(self, ok: OkRuntime) -> None:
        deadline = self.monotonic() + self.options.ready_timeout_seconds
        while self.monotonic() < deadline:
            refresh_and_select_connected_device(ok.device_manager)
            if is_ok_ready(ok):
                ok.task_executor.start()
                return
            self.sleep(self.options.ready_poll_seconds)
        raise OkLaunchError(f"OK was not ready within {self.options.ready_timeout_seconds:g} seconds")


def refresh_and_select_connected_device(device_manager: DeviceManager) -> dict[str, Any] | None:
    device_manager.do_refresh(True)
    preferred = device_manager.get_preferred_device()
    if preferred and preferred.get("connected"):
        return preferred

    connected = first_connected_device(device_manager)
    if connected is None:
        return preferred

    device_manager.set_preferred_device(connected.get("imei"))
    device_manager.do_refresh(True)
    return device_manager.get_preferred_device()


def first_connected_device(device_manager: DeviceManager) -> dict[str, Any] | None:
    try:
        devices = device_manager.get_devices()
    except Exception:
        return None
    return next((device for device in devices if device.get("connected")), None)


def is_ok_ready(ok: OkRuntime) -> bool:
    device_manager = ok.device_manager
    device_manager.do_refresh(True)
    preferred = device_manager.get_preferred_device()
    capture = getattr(device_manager, "capture_method", None)
    capture_ready = bool(
        preferred
        and preferred.get("connected")
        and has_capture_frame(capture)
    )
    return capture_ready and getattr(device_manager, "interaction", None) is not None


def has_capture_frame(capture: Any) -> bool:
    if capture is None:
        return False
    try:
        if not capture.connected():
            return False
        frame = capture.get_frame()
    except Exception:
        return False
    return frame is not None and hasattr(frame, "shape")


def stop_ok_runtime(ok: OkRuntime) -> None:
    try:
        ok.device_manager.stop_hwnd()
    except Exception:
        pass
    try:
        ok.quit()
    except Exception:
        pass


def run_onetime_task(
    executor: TaskExecutor,
    task: Any,
    *,
    timeout_seconds: float = 1800.0,
    poll_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    task.enable()
    task.unpause()
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if executor.exit_event.is_set():
            raise OkLaunchError("Executor exit event set before task finished")
        if not task.enabled and executor.current_task is None:
            task.running = False
            if error := get_task_error(task):
                return f"{task.name}: {error}"
            return ""
        sleep(poll_seconds)
    raise TimeoutError(f"{task.name} did not finish within {timeout_seconds:g} seconds")


def get_task_error(task: Any) -> str | None:
    keys = ["Error", "error"]
    try:
        from PySide6.QtCore import QCoreApplication

        translated = QCoreApplication.tr("app", "Error")
        keys.insert(0, translated)
    except Exception:
        pass

    for key in dict.fromkeys(keys):
        error = task.info_get(key)
        if isinstance(error, str):
            error = error.strip()
            if error:
                return error
        elif error:
            return str(error)
    return None


def load_runtime_imports(ww_root: Path) -> RuntimeImports:
    with ww_import_path(ww_root):
        config_module = importlib.import_module("config")
        ok_module = importlib.import_module("ok")
        process_module = importlib.import_module("ok.util.process")
        install_runtime_safety_patches()
    return RuntimeImports(
        ok_class=ok_module.OK,
        config=config_module.config,
        process_execute=process_module.execute,
    )


@contextmanager
def ww_runtime_context(ww_root: Path) -> Iterator[None]:
    with ww_import_path(ww_root), working_directory(ww_root):
        yield


@contextmanager
def ww_import_path(ww_root: Path) -> Iterator[None]:
    root = str(ww_root.resolve())
    inserted = False
    if root not in sys.path:
        sys.path.insert(0, root)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(root)
            except ValueError:
                pass


@contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def kill_game_processes() -> None:
    """Best-effort cleanup of all known Wuthering Waves game processes."""
    import subprocess

    try:
        import psutil
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = proc.info.get("name")
                if not name:
                    continue
                if name in ("Wuthering Waves.exe", "Client-Win64-Shipping.exe"):
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        import os
        if os.name == "nt":
            for name in ("Wuthering Waves.exe", "Client-Win64-Shipping.exe"):
                subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True, check=False)
