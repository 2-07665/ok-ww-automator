"""Auto-update commands for the upstream automation project."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .processes import run_with_timeout


@dataclass(frozen=True)
class CommandSpec:
    args: tuple[str, ...]
    cwd: Path | None = None

    def display(self) -> str:
        return " ".join(self.args)


@dataclass(frozen=True)
class UpdatePlan:
    ww_root: Path
    commands: tuple[CommandSpec, ...]


def build_update_plan(
    *,
    ww_root: Path,
    remote: str = "origin",
    branch: str = "master",
    requirements_file: Path | None = None,
    python_exe: Path | None = None,
) -> UpdatePlan:
    resolved_root = ww_root.resolve()
    requirements = requirements_file or resolved_root / "requirements.txt"
    if not requirements.is_absolute():
        requirements = resolved_root / requirements
    interpreter = str(python_exe or sys.executable)
    return UpdatePlan(
        ww_root=resolved_root,
        commands=(
            CommandSpec(("git", "-C", str(resolved_root), "fetch", remote, "--prune")),
            # Refuse conflicts and divergent history instead of destroying local work.
            CommandSpec(("git", "-C", str(resolved_root), "merge", "--ff-only", f"{remote}/{branch}")),
            CommandSpec(("uv", "pip", "install", "--python", interpreter, "-r", str(requirements)), cwd=resolved_root),
        ),
    )


def run_commands(commands: Sequence[CommandSpec], *, timeout: float | None = None) -> None:
    deadline = time.monotonic() + timeout if timeout is not None else None
    for command in commands:
        if deadline is None:
            subprocess.run(command.args, cwd=command.cwd, check=True)
        else:
            result = run_with_timeout(command.args, cwd=command.cwd, timeout=deadline - time.monotonic())
            result.check_returncode()
