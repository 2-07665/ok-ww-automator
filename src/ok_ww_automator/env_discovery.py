"""Discover runnable account env files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EXAMPLE_ENV_NAMES = {".env.example"}


@dataclass(frozen=True)
class AccountEnv:
    account_id: str
    path: Path

    @property
    def display_path(self) -> str:
        return self.path.as_posix()


def discover_account_envs(env_dir: Path) -> list[AccountEnv]:
    if not env_dir.exists():
        return []
    accounts = []
    paths = list(env_dir.glob("*.env"))
    default_env = env_dir / ".env"
    if default_env.exists():
        paths.append(default_env)
    seen: set[Path] = set()
    for path in sorted(paths):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.name in EXAMPLE_ENV_NAMES:
            continue
        accounts.append(AccountEnv(account_id=account_id_from_env_path(path), path=resolved))
    return accounts


def select_accounts(accounts: list[AccountEnv], selected_ids: list[str] | None = None) -> list[AccountEnv]:
    if not selected_ids:
        return accounts

    by_id = {account.account_id: account for account in accounts}
    missing = [account_id for account_id in selected_ids if account_id not in by_id]
    if missing:
        raise ValueError(f"Unknown account env: {', '.join(missing)}")
    return [by_id[account_id] for account_id in selected_ids]


def account_id_from_env_path(path: Path) -> str:
    if path.name == ".env":
        return "default"
    name = path.name
    if name.endswith(".env"):
        return name.removesuffix(".env")
    return path.stem
