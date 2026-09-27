"""Weekly Garden scheduling and per-account durable completion records."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import sqlite3
import time
from dataclasses import replace
from typing import Callable

from .config import AppConfig
from .game_clients import WeeklyGameClient
from .models import RunResult, SheetRunConfig
from .notices import WxPusherNoticeClient
from .time_utils import BEIJING_TZ, now

WEEKLY_TIMEOUT_SECONDS = 40 * 60
WEEKLY_MAX_ATTEMPTS = 2  # First attempt plus at most one retry per invocation.


def week_start(value: dt.datetime) -> dt.datetime:
    local = value.astimezone(BEIJING_TZ)
    monday = (local - dt.timedelta(days=local.weekday())).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    return monday if local >= monday else monday - dt.timedelta(days=7)


def weekly_notice_start(start: dt.datetime, day: int) -> dt.datetime:
    notice = (start + dt.timedelta(days=day - 1)).replace(hour=0)
    return max(start, notice)  # Monday's new week begins at 04:00.


class WeeklyRunner:
    def __init__(
        self,
        app_config: AppConfig,
        game_client: WeeklyGameClient,
        *,
        run_now: bool = False,
        prepare: Callable[[float], None] | None = None,
        clock: Callable[[], dt.datetime] = now,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        timeout_seconds: float = WEEKLY_TIMEOUT_SECONDS,
    ) -> None:
        self.config = app_config
        self.game_client = game_client
        self.run_now = run_now
        self.prepare = prepare
        self.clock = clock
        self.sleep = sleep
        self.monotonic = monotonic
        self.timeout_seconds = timeout_seconds

    def run(self) -> RunResult:
        current = self.clock().astimezone(BEIJING_TZ)
        result = RunResult("weekly", current, None, "skipped")
        # The env file identifies an account, independently of optional notice labels.
        account = os.path.normcase(str(self.config.env_path.resolve()))
        key = hashlib.sha256(account.encode("utf-8")).hexdigest()[:24]
        directory = self.config.project_root / ".state" / "weekly"
        directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(directory / f"{key}.sqlite3", timeout=0)
        db.row_factory = sqlite3.Row
        try:
            # Keep the write lock throughout the run: simultaneous scheduler/GUI
            # requests for this account must not both launch the game. A killed
            # process releases the lock automatically; no stale lock file remains.
            try:
                db.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
                result.decision = "此账号的周常任务正在运行"
                return result
            db.execute("""CREATE TABLE IF NOT EXISTS weeks (
                week TEXT PRIMARY KEY, deadline TEXT, success INTEGER NOT NULL DEFAULT 0,
                error TEXT, finalized INTEGER NOT NULL DEFAULT 0
            )""")
            start = week_start(current)
            week = start.date().isoformat()
            # If the machine was off at the deadline, report an unfinished recorded
            # week on the next invocation, even if a new game week has begun.
            for row in db.execute(
                "SELECT * FROM weeks WHERE week < ? AND success = 0 AND finalized = 0 AND deadline IS NOT NULL",
                (week,),
            ).fetchall():
                previous = RunResult("weekly", current, current, "failure")
                self._finish_failure(db, row, previous)
                print(f"Weekly: {previous.decision}; {previous.error}")

            deadline = weekly_notice_start(start, self.config.weekly_run.notice_day)
            db.execute("INSERT OR IGNORE INTO weeks (week) VALUES (?)", (week,))
            db.execute("UPDATE weeks SET deadline = ? WHERE week = ?", (deadline.isoformat(), week))
            row = db.execute("SELECT * FROM weeks WHERE week = ?", (week,)).fetchone()
            if row["success"] and not self.run_now:
                result.decision = f"{week} 起的这一周已成功，跳过"
                return result

            if not self.run_now and current.isoweekday() not in self.config.weekly_run.run_days:
                result.decision = "今天不在此账号的周常执行日内，跳过"
                if current >= deadline:
                    self._finish_failure(db, row, result)
                return result

            error = self._attempt(start)
            if error is None:
                db.execute("UPDATE weeks SET success = 1, error = NULL WHERE week = ?", (week,))
                result.status = "success"
                result.decision = f"{week} 起的这一周 Garden 已完成"
                return result
            db.execute("UPDATE weeks SET error = ? WHERE week = ?", (error, week))
            result.status = "failure" if row["success"] else "needs review"
            result.error = error
            result.decision = (
                "本次手动运行失败；保留本周此前的成功记录"
                if row["success"] else "本次周常未成功，等待下次触发或手动重试"
            )
            row = db.execute("SELECT * FROM weeks WHERE week = ?", (week,)).fetchone()
            if self.clock().astimezone(BEIJING_TZ) >= deadline:
                self._finish_failure(db, row, result)
            return result
        finally:
            db.commit()
            db.close()
            result.ended_at = self.clock().astimezone(BEIJING_TZ)
            print(f"Weekly: {result.status}; {result.decision or ''}; {result.error or ''}")

    def _attempt(self, start: dt.datetime) -> str | None:
        attempts = min(self.config.retry.max_attempts, WEEKLY_MAX_ATTEMPTS)
        deadline = self.monotonic() + self.timeout_seconds
        timeout_error = f"周常达到总时限 {self.timeout_seconds / 60:g} 分钟，已终止本次执行"
        try:
            if self.prepare is not None:
                self.prepare(max(0, deadline - self.monotonic()))
        except Exception as exc:
            return timeout_error if self.monotonic() >= deadline else f"准备游戏失败: {exc}"
        error = "Garden 未确认完成"
        for attempt in range(attempts):
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return timeout_error
            if week_start(self.clock()) != start:
                return "已跨过周一 04:00，本次未计为该周成功"
            try:
                outcome = self.game_client.run_weekly(timeout=remaining)
                if outcome.completed is True:
                    if week_start(self.clock()) != start:
                        return "任务执行跨过周一 04:00，本次未计为该周成功"
                    if outcome.task_error:
                        print(f"Garden 已确认完成，保留上游报错供排查: {outcome.task_error}")
                    return None
                error = outcome.task_error or "Garden 未确认完成"
            except Exception as exc:
                error = str(exc)
            if self.monotonic() >= deadline:
                return timeout_error
            if attempt + 1 < attempts:
                self.sleep(min(self.config.retry.delay_seconds, max(0, deadline - self.monotonic())))
        return error

    def _finish_failure(self, db: sqlite3.Connection, row: sqlite3.Row, result: RunResult) -> None:
        if row["success"]:
            return
        result.status = "failure"
        result.error = row["error"] or "本周到通知日仍没有成功记录"
        result.decision = f"周常失败：{row['week']} 起的这一周；通知日起 {row['deadline']}（北京时间）"
        result.ended_at = self.clock().astimezone(BEIJING_TZ)
        if row["finalized"]:
            return
        notice = self.config.notice
        if notice.enabled and "wxpusher" in notice.channels and notice.wxpusher_spt:
            try:
                notice = replace(notice, account_id=notice.account_id or self.config.env_path.stem)
                WxPusherNoticeClient(notice).notify(result, SheetRunConfig())
            except Exception as exc:
                # Leave delivery pending for the next invocation.
                result.error += f"；wxPusher 通知失败: {exc}"
                return
        db.execute("UPDATE weeks SET finalized = 1 WHERE week = ?", (row["week"],))
