"""Auto-update commands for the upstream automation project."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


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
) -> UpdatePlan:
    resolved_root = ww_root.resolve()
    requirements = requirements_file or resolved_root / "requirements.txt"
    return UpdatePlan(
        ww_root=resolved_root,
        commands=(
            CommandSpec(("git", "-C", str(resolved_root), "fetch", remote, "--prune")),
            CommandSpec(("git", "-C", str(resolved_root), "reset", "--hard", f"{remote}/{branch}")),
            CommandSpec(("uv", "pip", "install", "-r", str(requirements)), cwd=resolved_root),
        ),
    )


def run_commands(commands: Sequence[CommandSpec]) -> None:
    for command in commands:
        subprocess.run(command.args, cwd=command.cwd, check=True)
