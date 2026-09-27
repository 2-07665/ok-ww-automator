"""Fluent desktop UI. Task execution stays in independent Python processes."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import queue
import subprocess

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, FluentWindow, InfoBar,
    LineEdit, MessageBox, NavigationItemPosition, PlainTextEdit,
    PrimaryPushButton, PushButton, SegmentedWidget, SimpleCardWidget,
    SubtitleLabel, TableWidget, TitleLabel,
)

from .env_discovery import AccountEnv, discover_account_envs
from .farm_progress import FarmProgress, FarmStatistics
from .windows_launcher import (
    APP_NAME, DEFAULT_WINDOW_SIZE, GAME_LAUNCH_COOLDOWN_MS, MAX_LOG_LINES,
    MINIMUM_ACCOUNT_TABLE_HEIGHT, MINIMUM_LOG_HEIGHT, MINIMUM_WINDOW_SIZE,
    LauncherConfigurationError, LauncherPaths, ManagedProcess,
    build_auto_farm_command, build_game_launch, build_ok_gui_command,
    build_scheduler_command, discover_launcher_paths, launch_game, launcher_start_path,
)


def duration_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class MetricCard(SimpleCardWidget):
    def __init__(self, title: str, unit: str, *, large: bool = False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(8)
        layout.addWidget(CaptionLabel(title, self))
        self.value = BodyLabel("—", self)
        self.value.setFont(QFont("Segoe UI", 38 if large else 24, QFont.Weight.DemiBold))
        self.value.setStyleSheet("color: #087f8c;" if large else "color: #243746;")
        layout.addWidget(self.value)
        layout.addWidget(CaptionLabel(unit, self))

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class LauncherWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.paths: LauncherPaths | None = None
        self.accounts: list[AccountEnv] = []
        self.process = ManagedProcess()
        self.operation = ""
        self.mode = "daily"
        self.statistics = FarmStatistics()
        self.log_path: Path | None = None
        self._close_when_idle = False
        self._game_launch_cooldown = False
        self._farm_error = ""
        self._farm_shutdown = False

        self.setWindowTitle(APP_NAME)
        self.resize(*DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(*MINIMUM_WINDOW_SIZE)
        self.setMicaEffectEnabled(False)
        self._build_farm_page()
        self._build_scheduler_page()
        self._build_tools_page()
        self._build_logs_page()
        self.addSubInterface(self.scheduler_page, FIF.CALENDAR, "日常 / 体力 / 周常")
        self.addSubInterface(self.tools_page, FIF.ROBOT, "OK 工具")
        self.addSubInterface(self.farm_page, FIF.GAME, "Auto Farm")
        self.addSubInterface(self.logs_page, FIF.DOCUMENT, "运行日志", NavigationItemPosition.BOTTOM)
        self.navigationInterface.setExpandWidth(200)
        self.navigationInterface.setMinimumExpandWidth(900)
        self.navigationInterface.expand(useAni=False)
        self._load_workspace()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_events)
        self.timer.start(100)

    def _page(self, name: str, title: str, subtitle: str):
        page = QWidget()
        page.setObjectName(name)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(18)
        heading = QVBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(TitleLabel(title, page))
        heading.addWidget(BodyLabel(subtitle, page))
        layout.addLayout(heading)
        return page, layout

    def _build_farm_page(self):
        self.farm_page, layout = self._page("farm", "Auto Farm", "固定 4C · 小卡速刷")

        status_card = SimpleCardWidget(self.farm_page)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(24, 18, 24, 18)
        self.farm_status = SubtitleLabel("准备就绪", status_card)
        self.farm_message = BodyLabel("在游戏中调整好角色与站位，然后开始速刷。", status_card)
        self.farm_message.setWordWrap(True)
        self.farm_message.setTextFormat(Qt.TextFormat.PlainText)
        status_layout.addWidget(self.farm_status)
        status_layout.addWidget(self.farm_message)
        layout.addWidget(status_card)

        primary = QHBoxLayout()
        primary.setSpacing(16)
        self.count_card = MetricCard("已完成战斗", "次 · 本次运行", large=True)
        self.speed_card = MetricCard("近期刷取速度", "次 / 小时 · 最近 5 分钟", large=True)
        primary.addWidget(self.count_card)
        primary.addWidget(self.speed_card)
        layout.addLayout(primary)

        secondary = QHBoxLayout()
        secondary.setSpacing(16)
        self.elapsed_card = MetricCard("已运行", "小时 : 分钟 : 秒")
        self.average_card = MetricCard("全程平均速度", "次 / 小时")
        self.cycle_card = MetricCard("平均每轮耗时", "秒 / 次 · 含等待与拾取")
        for card in (self.elapsed_card, self.average_card, self.cycle_card):
            secondary.addWidget(card)
        layout.addLayout(secondary)

        settings = SimpleCardWidget(self.farm_page)
        settings_layout = QGridLayout(settings)
        settings_layout.setContentsMargins(24, 18, 24, 18)
        settings_layout.setHorizontalSpacing(16)
        settings_layout.addWidget(SubtitleLabel("到点关机", settings), 0, 0)
        settings_layout.addWidget(CaptionLabel("系统本地时间 · 已过的时刻按次日计算", settings), 1, 0)
        self.stop_time = LineEdit(settings)
        self.stop_time.setText("03:00")
        self.stop_time.setPlaceholderText("HH:MM")
        self.stop_time.setFixedWidth(100)
        settings_layout.addWidget(self.stop_time, 0, 1, 2, 1)
        settings_layout.setColumnStretch(2, 1)
        self.remaining_label = SubtitleLabel("—", settings)
        self.remaining_label.setMinimumWidth(125)
        settings_layout.addWidget(CaptionLabel("距离结束", settings), 0, 3)
        settings_layout.addWidget(self.remaining_label, 1, 3)
        layout.addWidget(settings)

        actions = QHBoxLayout()
        self.farm_start = PrimaryPushButton(FIF.PLAY, "开始速刷", self.farm_page)
        self.farm_start.clicked.connect(self._launch_auto_farm)
        self.farm_stop = PushButton("停止", self.farm_page)
        self.farm_stop.clicked.connect(self._request_stop)
        actions.addWidget(self.farm_start)
        actions.addWidget(self.farm_stop)
        actions.addStretch()
        layout.addLayout(actions)
        note = CaptionLabel("使用当前已打开的游戏。统计为战斗次数，速度包含等待与拾取时间。", self.farm_page)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def _build_scheduler_page(self):
        self.scheduler_page, layout = self._page("scheduler", "日常 / 体力 / 周常", "体力 + 周常：先完成体力监控，再做周常，最后按配置关机。单独周常可重复运行。")
        self.mode_picker = SegmentedWidget(self.scheduler_page)
        self.mode_picker.addItem("daily", "每日任务", lambda: self._set_mode("daily"))
        self.mode_picker.addItem("stamina", "消耗体力", lambda: self._set_mode("stamina"))
        self.mode_picker.addItem("weekly", "周常乐园", lambda: self._set_mode("weekly"))
        self.mode_picker.addItem("stamina-weekly", "体力 + 周常", lambda: self._set_mode("stamina-weekly"))
        self.mode_picker.setCurrentItem("daily")
        layout.addWidget(self.mode_picker)

        self.account_table = TableWidget(self.scheduler_page)
        self.account_table.setColumnCount(2)
        self.account_table.setHorizontalHeaderLabels(["账号", "配置文件"])
        self.account_table.verticalHeader().hide()
        self.account_table.setBorderVisible(True)
        self.account_table.setBorderRadius(8)
        self.account_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.account_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.account_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.account_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.account_table.setMinimumHeight(MINIMUM_ACCOUNT_TABLE_HEIGHT)
        self.account_table.itemSelectionChanged.connect(self._sync_controls)
        layout.addWidget(self.account_table, 1)
        row = QHBoxLayout()
        self.account_buttons = []
        for text, callback in (
            ("全选", self.account_table.selectAll), ("清空", self.account_table.clearSelection),
            ("刷新", self._refresh_accounts), ("上移", lambda: self._move_accounts(-1)),
            ("下移", lambda: self._move_accounts(1)),
        ):
            button = PushButton(text, self.scheduler_page)
            button.clicked.connect(callback)
            self.account_buttons.append(button)
            row.addWidget(button)
        row.addStretch()
        self.game_button = PushButton("启动所选游戏", self.scheduler_page)
        self.game_button.clicked.connect(self._launch_selected_game)
        row.addWidget(self.game_button)
        layout.addLayout(row)
        self.scheduler_status = BodyLabel("请选择要运行的账号。", self.scheduler_page)
        self.scheduler_status.setWordWrap(True)
        self.scheduler_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.scheduler_status)
        actions = QHBoxLayout()
        self.scheduler_start = PrimaryPushButton(FIF.PLAY, "运行所选账号", self.scheduler_page)
        self.scheduler_start.clicked.connect(self._launch_scheduler)
        self.scheduler_stop = PushButton("停止", self.scheduler_page)
        self.scheduler_stop.clicked.connect(self._request_stop)
        actions.addWidget(self.scheduler_start)
        actions.addWidget(self.scheduler_stop)
        actions.addStretch()
        layout.addLayout(actions)

    def _build_tools_page(self):
        self.tools_page, layout = self._page("tools", "OK 工具", "打开完整的 OK 界面，使用声骸融合、词条识别等任务。")
        self.ok_button = PrimaryPushButton(FIF.ROBOT, "启动 OK GUI", self.tools_page)
        self.ok_button.clicked.connect(self._launch_ok_gui)
        layout.addWidget(self.ok_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.tools_status = BodyLabel("准备就绪", self.tools_page)
        self.tools_status.setWordWrap(True)
        layout.addWidget(self.tools_status)
        self.tools_stop = PushButton("停止 OK GUI", self.tools_page)
        self.tools_stop.clicked.connect(self._request_stop)
        layout.addWidget(self.tools_stop, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def _build_logs_page(self):
        self.logs_page, layout = self._page("logs", "运行日志", "排查问题时查看。完整输出会自动保存到本地文件。")
        self.log = PlainTextEdit(self.logs_page)
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        self.log.document().setMaximumBlockCount(MAX_LOG_LINES)
        self.log.setMinimumHeight(MINIMUM_LOG_HEIGHT)
        layout.addWidget(self.log, 1)
        self.open_log_button = PushButton(FIF.DOCUMENT, "打开日志文件", self.logs_page)
        self.open_log_button.clicked.connect(self._open_log)
        layout.addWidget(self.open_log_button, alignment=Qt.AlignmentFlag.AlignLeft)

    def _load_workspace(self):
        try:
            self.paths = discover_launcher_paths(launcher_start_path())
        except LauncherConfigurationError as exc:
            self.farm_status.setText("配置不可用")
            self.farm_message.setText(str(exc))
            self.scheduler_status.setText(str(exc))
            self._append_log(str(exc))
        else:
            self.setWindowIcon(QIcon(str(self.paths.upstream_root / "icons" / "icon.ico")))
            self._refresh_accounts()
        self._sync_controls()

    def _set_mode(self, mode: str):
        self.mode = mode

    def _selected_ids(self) -> list[str]:
        rows = sorted(index.row() for index in self.account_table.selectionModel().selectedRows())
        return [self.accounts[row].account_id for row in rows]

    def _fill_accounts(self, selected: set[str]):
        self.account_table.blockSignals(True)
        self.account_table.setRowCount(len(self.accounts))
        self.account_table.clearSelection()
        for row, account in enumerate(self.accounts):
            self.account_table.setItem(row, 0, QTableWidgetItem(account.account_id))
            self.account_table.setItem(row, 1, QTableWidgetItem(account.path.name))
            if account.account_id in selected:
                self.account_table.selectionModel().select(
                    self.account_table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )
        self.account_table.blockSignals(False)
        self._sync_controls()

    def _refresh_accounts(self):
        try:
            self.accounts = discover_account_envs(self.paths.automator_root / "env") if self.paths else []
        except (OSError, ValueError) as exc:
            self.accounts = []
            self._fill_accounts(set())
            message = f"账号配置不可用：{exc}"
            self.scheduler_status.setText(message)
            self._append_log(message)
            return
        self._fill_accounts({account.account_id for account in self.accounts})
        self.scheduler_status.setText("按列表顺序运行所选账号。" if self.accounts else "未发现账号配置。")

    def _move_accounts(self, direction: int):
        selected = set(self._selected_ids())
        indices = range(1, len(self.accounts)) if direction < 0 else range(len(self.accounts) - 2, -1, -1)
        for index in indices:
            other = index + direction
            if self.accounts[index].account_id in selected and self.accounts[other].account_id not in selected:
                self.accounts[index], self.accounts[other] = self.accounts[other], self.accounts[index]
        self._fill_accounts(selected)

    def _launch_auto_farm(self):
        if self.paths is None:
            return
        try:
            command = build_auto_farm_command(self.paths, self.stop_time.text())
        except ValueError as exc:
            self._warn(str(exc))
            return
        self.statistics = FarmStatistics()
        self._farm_error = ""
        self._farm_shutdown = False
        self._show_statistics()
        self.farm_status.setText("正在连接游戏")
        self.farm_message.setText("连接当前已打开的游戏，随后开始速刷。")
        self._start_operation("Auto Farm", command)

    def _launch_scheduler(self):
        if self.paths is None:
            return
        try:
            command = build_scheduler_command(self.paths, self.mode, self._selected_ids())
        except ValueError as exc:
            self._warn(str(exc))
            return
        self._start_operation(f"{self.mode.title()} scheduler", command)

    def _launch_ok_gui(self):
        if self.paths is not None:
            self._start_operation("OK GUI", build_ok_gui_command(self.paths))

    def _launch_selected_game(self):
        if self._game_launch_cooldown:
            return
        try:
            launch = build_game_launch(self.accounts, self._selected_ids())
            launch_game(launch)
        except (ValueError, OSError) as exc:
            self._warn(str(exc))
            return
        self.scheduler_status.setText(f"已启动游戏：{launch.account_id}")
        self._game_launch_cooldown = True
        self._sync_controls()
        QTimer.singleShot(GAME_LAUNCH_COOLDOWN_MS, self._finish_game_launch_cooldown)

    def _finish_game_launch_cooldown(self):
        self._game_launch_cooldown = False
        self._sync_controls()

    def _start_operation(self, operation: str, command: list[str]):
        if self.paths is None or self.process.is_active:
            return
        self.operation = operation
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.log_path = self.paths.automator_root / "logs" / f"launcher-{timestamp}.log"
        self.log.clear()
        self._append_log(subprocess.list2cmdline(command))
        try:
            self.process.start(operation, command, cwd=self.paths.workspace_root, log_path=self.log_path)
        except Exception as exc:
            self._append_log(str(exc))
        self._sync_controls()

    def _request_stop(self):
        if not self.process.is_active:
            return
        dialog = MessageBox("停止运行", "确定停止当前任务及其子进程？", self)
        dialog.yesButton.setText("停止")
        dialog.cancelButton.setText("继续运行")
        if dialog.exec():
            self._stop_operation()

    def _stop_operation(self):
        try:
            self.process.stop()
        except Exception as exc:
            self._close_when_idle = False
            self._warn(str(exc))
        self._sync_controls()

    def closeEvent(self, event):
        if not self.process.is_active:
            event.accept()
            return
        event.ignore()
        dialog = MessageBox("任务仍在运行", "停止当前任务并关闭启动器？", self)
        dialog.yesButton.setText("停止并关闭")
        dialog.cancelButton.setText("继续运行")
        if dialog.exec():
            self._close_when_idle = True
            self._stop_operation()

    def _poll_events(self):
        # Bound each GUI tick so a burst of logs cannot starve input or painting.
        for _ in range(200):
            try:
                event = self.process.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "output":
                self._append_log(event.text)
            elif event.kind == "progress" and event.progress is not None:
                self._apply_progress(event.progress)
            elif event.kind in {"started", "stopping", "finished"}:
                self._apply_process_status(event)
        self._sync_controls()
        if self._close_when_idle and not self.process.is_active:
            self.close()

    def _apply_process_status(self, event):
        if event.kind == "started":
            text = f"正在运行 · {event.operation}"
        elif event.kind == "stopping":
            text = "正在停止…"
        elif event.text == "completed":
            text = "已完成"
        elif event.text == "stopped":
            text = "已停止"
        else:
            text = f"运行失败 · {event.text if event.returncode is None else f'退出码 {event.returncode}'}"
        if event.operation == "Auto Farm":
            if event.kind != "started" and not self._farm_shutdown:
                self.farm_status.setText(text)
            if event.kind == "finished" and not self._farm_shutdown:
                self.farm_message.setText(
                    self._farm_error or ("本次统计已保留。" if event.text in {"completed", "stopped"}
                                         else "任务未能完成，可在运行日志中查看详细原因。")
                )
        elif event.operation == "OK GUI":
            self.tools_status.setText(text)
        else:
            self.scheduler_status.setText(text)

    def _apply_progress(self, progress: FarmProgress):
        if progress.state == "running":
            self.statistics.update(progress)
            self.farm_status.setText("正在速刷")
            self.farm_message.setText("到达设定时间后自动停止并关机。")
            self._show_statistics()
        elif progress.state == "connecting":
            self.remaining_label.setText(duration_text(progress.remaining))
        elif progress.state == "failed":
            self._farm_error = progress.message
            self.farm_status.setText("运行失败")
            self.farm_message.setText(progress.message)
        elif progress.state == "shutdown":
            self._farm_shutdown = True
            self.farm_status.setText("速刷已完成")
            self.farm_message.setText(progress.message)
            self.remaining_label.setText("00:00:00")

    def _show_statistics(self):
        stats = self.statistics
        self.count_card.set_value(f"{stats.count:,}")
        self.elapsed_card.set_value(duration_text(stats.elapsed))
        self.remaining_label.setText(duration_text(stats.remaining))
        for card, value in (
            (self.speed_card, stats.recent_hourly_rate),
            (self.average_card, stats.hourly_rate),
            (self.cycle_card, stats.seconds_per_fight),
        ):
            card.set_value(f"{value:,.1f}" if value is not None else "—")

    def _append_log(self, text: str):
        self.log.appendPlainText(text.rstrip("\r\n"))

    def _open_log(self):
        if self.log_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path)))

    def _warn(self, message: str):
        InfoBar.warning("无法执行", message, duration=6000, parent=self)

    def _sync_controls(self):
        active = self.process.is_active
        available = self.paths is not None and not active
        selected = len(self._selected_ids())
        self.farm_start.setEnabled(available)
        self.stop_time.setEnabled(not active)
        self.farm_stop.setEnabled(active and self.operation == "Auto Farm")
        self.scheduler_start.setEnabled(available and selected > 0)
        self.scheduler_stop.setEnabled(active and self.operation.endswith("scheduler"))
        self.mode_picker.setEnabled(not active)
        self.account_table.setEnabled(not active)
        for button in self.account_buttons:
            button.setEnabled(not active)
        self.game_button.setEnabled(available and selected == 1 and not self._game_launch_cooldown)
        self.ok_button.setEnabled(available)
        self.tools_stop.setEnabled(active and self.operation == "OK GUI")
        self.open_log_button.setEnabled(self.log_path is not None and self.log_path.is_file())
