"""Read echo substats and periodically send the existing local UDP protocol."""

import json
import re
import socket

from qfluentwidgets import FluentIcon
from ok import Logger, TaskDisabledException
from src.task.BaseWWTask import BaseWWTask

from .echo_stats import parse_echo_stats

logger = Logger.get_logger(__name__)


class EchoOCRTask(BaseWWTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Echo OCR"
        self.description = "OCR识别声骸副词条"
        self.group_name = "My"
        self.icon = FluentIcon.ALBUM
        self.default_config = {"识别间隔(s)": 2.0, "端口": 9999}
        self._is_echo_page = False
        self._is_echo_upgrade_page = False
        self._last_sent_message = None
        self._socket = None

    def run(self):
        scan_interval = float(self.config.get("识别间隔(s)", 2.0))
        port = int(self.config.get("端口", 9999))
        self._is_echo_page = False
        self._is_echo_upgrade_page = False
        self._last_sent_message = None
        self.info_set("在声骸装备界面", "否")
        self.info_set("在声骸强化界面", "否")

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            self._socket = sock
            try:
                while self._is_task_active():
                    self.sleep(scan_interval)
                    frame = self.frame
                    if frame is None:
                        continue
                    self._check_echo_page(frame)
                    self._check_echo_upgrade_page(frame)
                    if self._is_echo_page:
                        texts = self.ocr(0.74, 0.29, 0.96, 0.45, frame=frame)
                    elif self._is_echo_upgrade_page:
                        texts = self.ocr(0.11, 0.29, 0.36, 0.51, frame=frame)
                    else:
                        continue
                    self.send_echo_stat(texts, "127.0.0.1", port)
            except TaskDisabledException:
                logger.info("Echo OCR task stopped manually")
            finally:
                self._socket = None

    def _is_task_active(self):
        return bool(getattr(self, "enabled", True) and getattr(self, "running", True))

    def _check_echo_page(self, frame):
        is_echo_page = bool(self.ocr(
            0.74, 0.90, 0.84, 0.95, match=["卸下", "装配", "替换"], frame=frame,
        ))
        if is_echo_page != self._is_echo_page:
            self._is_echo_page = is_echo_page
            self.info_set("在声骸装备界面", "是" if is_echo_page else "否")

    def _check_echo_upgrade_page(self, frame):
        is_echo_upgrade_page = bool(self.ocr(
            0.0, 0.0, 0.15, 0.10, match=re.compile(r"^声\D[强強]化$"), frame=frame,
        ))
        if is_echo_upgrade_page != self._is_echo_upgrade_page:
            self._is_echo_upgrade_page = is_echo_upgrade_page
            self.info_set("在声骸强化界面", "是" if is_echo_upgrade_page else "否")

    def send_echo_stat(self, texts, host, port):
        buff_entries = parse_echo_stats(texts)
        if not buff_entries:
            return  # Keep the receiver's previous result, as requested.
        payload = {"buffEntries": buff_entries}
        message = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._socket.sendto(message, (host, port))
        # Periodic retransmission is intentional; only identical log lines are suppressed.
        if message != self._last_sent_message:
            logger.info(f"Sent new OCR result {payload}")
        self._last_sent_message = message
