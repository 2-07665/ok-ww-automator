"""Bounded child-process execution for weekly work."""

from __future__ import annotations

import os
import signal
import subprocess


def run_with_timeout(command, *, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    if timeout <= 0:
        raise subprocess.TimeoutExpired(command, timeout)
    process = subprocess.Popen(command, start_new_session=os.name != "nt", **kwargs)
    try:
        returncode = process.wait(timeout=timeout)
    except BaseException:
        # Kill descendants while the parent still exists, including OK/game or
        # dependency-install children. Killing only Python leaves those running.
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=False, timeout=15,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        raise
    return subprocess.CompletedProcess(command, returncode)
