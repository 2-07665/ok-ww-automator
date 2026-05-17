import re

from qfluentwidgets import FluentIcon
from ok import Logger
logger = Logger.get_logger(__name__)

from src.task.BaseWWTask import BaseWWTask
from .ui_boxes import get_ui_box


class FiveToOneTask(BaseWWTask):

    MAX_RETRIES = 5
    RETRY_SLEEP_SECONDS = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = "自动五合一未锁定声骸"
        self.name = "数据坞五合一"
        self.group_name = "My"
        self.group_icon = FluentIcon.SYNC
        self.icon = FluentIcon.ALBUM
        self.default_config = {}

    def run(self):
        self.log_info("开始五合一任务")
        self.info_set("Merge Count", 0)
        self.info_set("Remaining Merge Count", 1)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self.enter_batch_merge()
                self.loop_merge()
            except Exception as exc:
                logger.error("MY-OK-WW: Merge task attempt failed", exc)
            finally:
                self.ensure_main(esc=True, time_out=60)

            remaining_merge_count = self.info_get("Remaining Merge Count")
            if remaining_merge_count == 0:
                break
            if attempt < self.MAX_RETRIES:
                self.log_info(
                    f"MY-OK-WW: Merge task exited early. Retrying {attempt + 1}/{self.MAX_RETRIES}"
                )
                self.sleep(self.RETRY_SLEEP_SECONDS)

        self.ensure_main(esc=True, time_out=60)
        self.log_info("五合一完成!")

    def enter_batch_merge(self):
        self.ensure_main(esc=True, time_out=60)
        self.log_info("在主页")
        self.open_esc_menu()
        self.sleep(1.0)
        self.wait_click_ocr(*get_ui_box("ESC菜单数据坞"), match="数据坞", time_out=30, raise_if_not_found=True, settle_time=0.2, after_sleep=1.0)
        self.wait_ocr(*get_ui_box("数据坞左上角判断"), match="数据坞", time_out=30, raise_if_not_found=True, settle_time=0.2)
        self.click_relative(0.04, 0.56, after_sleep=1.0)
        self.sleep(1.0)
        self.wait_click_ocr(*get_ui_box("数据坞标准融合入口"), match="标准融合", time_out=30, raise_if_not_found=True, settle_time=0.2)
        self.sleep(1.0)
        self.wait_click_ocr(*get_ui_box("数据坞开始标准融合"), match="标准融合", time_out=20, raise_if_not_found=True, settle_time=0.2)

    def loop_merge(self):
        """
        Enter batch merge, select all, consume merges until no merges remain.
        """
        while True:
            if not self.wait_click_ocr(*get_ui_box("数据坞标准融合全选"), match="全选", time_out=20, raise_if_not_found=False, settle_time=0.2, after_sleep=0.5):
                self.log_info("MY-OK-WW: 未找到全选按钮，结束任务")
                return

            merge_count = self._read_merge_count()
            if merge_count is None:
                self.log_info("MY-OK-WW: 无法识别数据融合次数，结束任务")
                return
            self.info_set("Remaining Merge Count", merge_count)
            if merge_count == 0:
                self.log_info("MY-OK-WW: 未锁定声骸已耗尽，结束任务")
                return

            if not self.wait_click_ocr(*get_ui_box("数据坞标准融合按钮"), match="标准融合", time_out=20, raise_if_not_found=False, settle_time=0.2, after_sleep=1.0):
                self.log_info("MY-OK-WW: 未找到标准融合按钮，结束任务")
                return

            self.wait_click_ocr(*get_ui_box("数据坞标准融合确认按钮"), match="确认", time_out=20, raise_if_not_found=False, settle_time=0.2, after_sleep=1.0)
            self.wait_ocr(*get_ui_box("数据坞标准融合获得声骸"), match="获得声骸", time_out=20, raise_if_not_found=False, settle_time=0.2)
            self.info_incr("Merge Count", merge_count)
            self.sleep(1.0)
            self.click_relative(0.5, 0.05, after_sleep=1.0)

    def _read_merge_count(self):
        """
        Read the current merge count from the bottom-right text "数据融合次数：num".
        """
        result = self.ocr(*get_ui_box("数据坞数据融合次数"), match=re.compile(r"数据融合次数[:：]\s*\d+"))
        if not result:
            return None
        match = re.search(r"数据融合次数[:：]\s*(\d+)", result[0].name)
        if not match:
            return None
        
        try:
            return int(match.group(1))
        except ValueError:
            return None
