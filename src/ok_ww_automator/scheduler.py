"""Single entrypoint intended for Windows Task Scheduler."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .config import AppConfig, load_config
from .env_discovery import AccountEnv, discover_account_envs, select_accounts
from .runners import RUN_STATUS_FAILURE, RunnerContext, RunnerError, SystemPowerController, run_mode
from .updater import build_update_plan, run_commands

RunMode = Literal["daily", "stamina", "weekly", "stamina-weekly"]
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SchedulerJob:
    account: AccountEnv
    mode: str


@dataclass(frozen=True)
class SchedulerPlan:
    project_root: Path
    accounts: tuple[AccountEnv, ...]
    jobs: tuple[SchedulerJob, ...]
    update_commands: tuple[str, ...]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve() if args.project_root else DEFAULT_PROJECT_ROOT
    env_dir = (project_root / args.env_dir).resolve()
    ww_root = Path(args.ww_root).resolve() if args.ww_root else (project_root.parent / "ok-wuthering-waves").resolve()

    try:
        plan = build_scheduler_plan(
            project_root=project_root,
            env_dir=env_dir,
            selected_accounts=args.account,
            mode=args.mode,
            skip_update=args.skip_update,
            ww_root=ww_root,
            ww_remote=args.ww_remote,
            ww_branch=args.ww_branch,
        )
        print_plan(plan, dry_run=args.dry_run)
        if args.dry_run:
            return 0
        validate_jobs(plan.jobs, project_root=project_root)
        if args.mode == "weekly":
            # WeeklyRunner checks weekly success before updating or starting the game.
            run_jobs(
                plan.jobs, project_root=project_root, env_dir=env_dir, ww_root=ww_root,
                ww_remote=args.ww_remote, ww_branch=args.ww_branch,
                run_now=args.run_now, skip_update=args.skip_update,
            )
            return 0
        if not args.skip_update:
            update_plan = build_update_plan(ww_root=ww_root, remote=args.ww_remote, branch=args.ww_branch)
            run_commands(update_plan.commands)
        if args.mode == "stamina-weekly":
            run_stamina_weekly_jobs(
                plan.jobs, project_root=project_root, env_dir=env_dir, ww_root=ww_root,
                ww_remote=args.ww_remote, ww_branch=args.ww_branch,
            )
            return 0
        run_jobs(
            plan.jobs,
            project_root=project_root,
            env_dir=env_dir,
            ww_root=ww_root,
            ww_remote=args.ww_remote,
            ww_branch=args.ww_branch,
            **({"shutdown_request_file": Path(args.shutdown_request_file)} if args.shutdown_request_file else {}),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ok-ww-automator scheduled jobs.")
    parser.add_argument("--project-root", help="Automator project root. Defaults to this package checkout.")
    parser.add_argument("--env-dir", default="env", help="Directory containing account env files.")
    parser.add_argument("--account", action="append", help="Account id to run. Can be supplied multiple times.")
    parser.add_argument("--mode", choices=["daily", "stamina", "weekly", "stamina-weekly"], required=True)
    parser.add_argument("--shutdown-request-file", help=argparse.SUPPRESS)
    parser.add_argument("--run-now", action="store_true", help="Run weekly manually, even if this week already succeeded.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without updating or running jobs.")
    parser.add_argument("--skip-update", action="store_true", help="Skip ok-wuthering-waves update commands.")
    parser.add_argument("--ww-root", help="Path to ok-wuthering-waves. Defaults beside this repo.")
    parser.add_argument("--ww-remote", default="origin")
    parser.add_argument("--ww-branch", default="master")
    args = parser.parse_args(argv)
    if args.shutdown_request_file and (args.mode != "stamina" or len(args.account or []) != 1):
        parser.error("--shutdown-request-file requires --mode stamina and exactly one --account")
    return args


def build_scheduler_plan(
    *,
    project_root: Path,
    env_dir: Path,
    selected_accounts: list[str] | None,
    mode: RunMode,
    skip_update: bool,
    ww_root: Path,
    ww_remote: str = "origin",
    ww_branch: str = "my",
) -> SchedulerPlan:
    accounts = select_accounts(discover_account_envs(env_dir), selected_accounts)
    if not accounts:
        raise RuntimeError(f"No account env files found in {env_dir}")

    jobs = []
    for resolved_mode in resolve_modes(mode):
        for account in accounts:
            jobs.append(SchedulerJob(account=account, mode=resolved_mode))

    update_commands: tuple[str, ...] = ()
    if not skip_update:
        update_commands = tuple(command.display() for command in build_update_plan(ww_root=ww_root, remote=ww_remote, branch=ww_branch).commands)

    return SchedulerPlan(
        project_root=project_root,
        accounts=tuple(accounts),
        jobs=tuple(jobs),
        update_commands=update_commands,
    )


def resolve_modes(mode: RunMode) -> tuple[str, ...]:
    if mode == "stamina-weekly":
        return ("stamina", "weekly")
    return (mode,)


def run_job(
    job: SchedulerJob, *, project_root: Path, ww_root: Path,
    run_now: bool = False, prepare: Callable[[float], None] | None = None,
    shutdown_request_file: Path | None = None,
) -> None:
    app_config = validate_job(job, project_root=project_root)
    result = run_mode(job.mode, RunnerContext(app_config=app_config, ww_root=ww_root, run_now=run_now,
                                            prepare=prepare, shutdown_request_file=shutdown_request_file))
    if result.status == RUN_STATUS_FAILURE:
        raise RunnerError(f"Account {job.account.account_id} {job.mode} task failed: {result.error}")


def run_jobs(
    jobs: tuple[SchedulerJob, ...],
    *,
    project_root: Path,
    env_dir: Path,
    ww_root: Path,
    ww_remote: str,
    ww_branch: str,
    run_now: bool = False,
    skip_update: bool = True,
    shutdown_request_file: Path | None = None,
) -> None:
    if len(jobs) == 1:
        if jobs[0].mode == "weekly":
            def prepare(timeout: float) -> None:
                run_commands(build_update_plan(ww_root=ww_root, remote=ww_remote, branch=ww_branch).commands,
                             timeout=timeout)

            run_job(jobs[0], project_root=project_root, ww_root=ww_root,
                    run_now=run_now, prepare=None if skip_update else prepare)
        else:
            run_job(jobs[0], project_root=project_root, ww_root=ww_root,
                    shutdown_request_file=shutdown_request_file)
        return

    errors: list[str] = []
    for job in jobs:
        try:
            weekly_options = {"run_now": run_now, "skip_update": skip_update} if job.mode == "weekly" else {}
            run_job_subprocess(
                job,
                project_root=project_root,
                env_dir=env_dir,
                ww_root=ww_root,
                ww_remote=ww_remote,
                ww_branch=ww_branch,
                **weekly_options,
            )
        except subprocess.CalledProcessError as exc:
            errors.append(f"{job.account.account_id}/{job.mode}: exited {exc.returncode}")

    if errors:
        raise RuntimeError(f"{len(errors)} job(s) failed: " + "; ".join(errors))


def run_job_subprocess(
    job: SchedulerJob,
    *,
    project_root: Path,
    env_dir: Path,
    ww_root: Path,
    ww_remote: str,
    ww_branch: str,
    run_now: bool = False,
    skip_update: bool = True,
    shutdown_request_file: Path | None = None,
) -> None:
    command = [
        sys.executable,
        "-m",
        "ok_ww_automator.scheduler",
        "--project-root",
        str(project_root),
        "--env-dir",
        str(env_dir),
        "--ww-root",
        str(ww_root),
        "--ww-remote",
        ww_remote,
        "--ww-branch",
        ww_branch,
        "--mode",
        job.mode,
        "--account",
        job.account.account_id,
    ]
    if skip_update:
        command.append("--skip-update")
    if run_now:
        command.append("--run-now")
    if shutdown_request_file is not None:
        command.extend(("--shutdown-request-file", str(shutdown_request_file)))
    env = dict(os.environ)
    env["ENV_FILE"] = str(job.account.path)
    subprocess.run(command, env=env, check=True)


def run_stamina_weekly_jobs(
    jobs: tuple[SchedulerJob, ...], *, project_root: Path, env_dir: Path,
    ww_root: Path, ww_remote: str, ww_branch: str,
) -> None:
    errors = []
    with tempfile.TemporaryDirectory(prefix="ok-ww-shutdown-") as directory:
        shutdown_request = Path(directory) / "requested.txt"
        try:
            # Plan order is all stamina accounts (including their Healthchecks),
            # then all weekly accounts. Each runner remains process-isolated.
            for job in jobs:
                try:
                    run_job_subprocess(
                        job, project_root=project_root, env_dir=env_dir, ww_root=ww_root,
                        ww_remote=ww_remote, ww_branch=ww_branch,
                        shutdown_request_file=shutdown_request if job.mode == "stamina" else None,
                    )
                except Exception as exc:
                    message = f"{job.account.account_id}/{job.mode}: {exc}"
                    errors.append(message)
                    print(f"ERROR: {message}", file=sys.stderr)
        finally:
            if shutdown_request.exists():
                SystemPowerController().request_shutdown("stamina-weekly")
    if errors:
        raise RunnerError(f"{len(errors)} job(s) failed: " + "; ".join(errors))


def validate_jobs(jobs: tuple[SchedulerJob, ...], *, project_root: Path) -> None:
    for job in jobs:
        validate_job(job, project_root=project_root)


def validate_job(job: SchedulerJob, *, project_root: Path) -> AppConfig:
    env = dict(os.environ)
    env["ENV_FILE"] = str(job.account.path)

    # Validate that the selected env file can be parsed before handing off to runners.
    return load_config(env=env, project_root=project_root, env_file=job.account.path)


def print_plan(plan: SchedulerPlan, *, dry_run: bool) -> None:
    print(f"Project: {plan.project_root}")
    print(f"Dry run: {'yes' if dry_run else 'no'}")
    if plan.update_commands:
        print("Update commands:")
        for command in plan.update_commands:
            print(f"  {command}")
    else:
        print("Update commands: skipped")

    print("Accounts:")
    for account in plan.accounts:
        print(f"  {account.account_id}: {account.path}")

    print("Jobs:")
    for job in plan.jobs:
        print(f"  {job.account.account_id}: {job.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
