import re


from src.task.BaseWWTask import BaseWWTask
from .ui_boxes import get_ui_box


class MergeNavigationError(RuntimeError):
    """A recoverable failure before submitting a merge."""


class MergeOutcomeUnknown(RuntimeError):
    """Submission may have succeeded; never retry it automatically."""


class FiveToOneTask(BaseWWTask):

    MAX_RETRIES = 5
    RETRY_SLEEP_SECONDS = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = "五合一未锁定声骸"
        self.name = "数据坞五合一"
        self.group_name = "My"
        self.default_config = {}

    def run(self):
        self.log_info("开始五合一任务")
        self.info_set("Merge Count", 0)
        self.info_set("Remaining Merge Count", "未知")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self.enter_batch_merge()
                if not self.loop_merge():
                    raise RuntimeError("未确认材料已耗尽，五合一未完成")
            except MergeNavigationError as exc:
                if attempt == self.MAX_RETRIES:
                    raise RuntimeError(f"五合一导航失败，已重试 {self.MAX_RETRIES} 次: {exc}") from exc
                self.log_info(f"五合一导航失败，重试 {attempt + 1}/{self.MAX_RETRIES}: {exc}")
                self.ensure_main(esc=True, time_out=60)
                self.sleep(self.RETRY_SLEEP_SECONDS)
            else:
                self.ensure_main(esc=True, time_out=60)
                self.log_info("五合一完成!")
                return

    def enter_batch_merge(self):
        self.ensure_main(esc=True, time_out=60)
        self.log_info("在主页")
        self.open_esc_menu()
        self.sleep(1.0)
        if not self.wait_click_ocr(*get_ui_box("ESC菜单数据坞"), match="数据坞", time_out=30, raise_if_not_found=False, settle_time=0.2, after_sleep=1.0):
            raise MergeNavigationError("未找到数据坞入口")
        if not self.wait_ocr(*get_ui_box("数据坞左上角判断"), match="数据坞", time_out=30, raise_if_not_found=False, settle_time=0.2):
            raise MergeNavigationError("未进入数据坞")
        self.click_relative(0.04, 0.56, after_sleep=1.0)
        self.sleep(1.0)
        if not self.wait_click_ocr(*get_ui_box("数据坞标准融合入口"), match="标准融合", time_out=30, raise_if_not_found=False, settle_time=0.2):
            raise MergeNavigationError("未找到标准融合入口")
        self.sleep(1.0)
        if not self.wait_click_ocr(*get_ui_box("数据坞开始标准融合"), match="标准融合", time_out=20, raise_if_not_found=False, settle_time=0.2):
            raise MergeNavigationError("未打开融合材料选择页")

    def loop_merge(self):
        """
        Enter batch merge, select all, consume merges until no merges remain.
        """
        while True:
            if not self.wait_click_ocr(*get_ui_box("数据坞标准融合全选"), match="全选", time_out=20, raise_if_not_found=False, settle_time=0.2, after_sleep=0.5):
                raise MergeNavigationError("未找到全选按钮")

            merge_count = self._read_merge_count()
            if merge_count is None:
                raise MergeNavigationError("无法识别数据融合次数，不能视为零")
            self.info_set("Remaining Merge Count", merge_count)
            if merge_count == 0:
                self.log_info("MY-OK-WW: 未锁定声骸已耗尽，结束任务")
                return True

            # Only pre-submission navigation failures are retried. From this
            # click until the selection page returns, errors stop the task.
            if not self.wait_click_ocr(*get_ui_box("数据坞标准融合按钮"), match="标准融合", time_out=20, raise_if_not_found=False, settle_time=0.2, after_sleep=1.0):
                raise MergeOutcomeUnknown("未确认融合按钮点击结果，已停止；请检查游戏")

            # The warning may already be suppressed for this login.
            state = self.wait_until(self._merge_submission_state, time_out=20, settle_time=0.2)
            if state == "confirm":
                # Select "本次登录不再提示" before confirming this batch.
                self.click_relative(0.443, 0.552, after_sleep=0.2)
                if not self.wait_click_ocr(*get_ui_box("数据坞标准融合确认按钮"), match="确认", time_out=20, raise_if_not_found=False, settle_time=0.2, after_sleep=1.0):
                    raise MergeOutcomeUnknown("未确认融合提交状态，已停止；请检查游戏后重新运行")
                if not self.wait_ocr(*get_ui_box("数据坞标准融合获得声骸"), match="获得声骸", time_out=20, raise_if_not_found=False, settle_time=0.2):
                    raise MergeOutcomeUnknown("未看到获得声骸结果，未计数且未重复提交")
            elif state != "result":
                raise MergeOutcomeUnknown("未看到融合确认框或获得声骸结果，未计数且未重复提交")
            self.info_incr("Merge Count", merge_count)
            self.sleep(1.0)
            self.click_relative(0.5, 0.05, after_sleep=1.0)
            # Only retry navigation once the result page has really closed.
            if not self.wait_ocr(*get_ui_box("数据坞标准融合全选"), match="全选", time_out=20, raise_if_not_found=False, settle_time=0.2):
                raise MergeOutcomeUnknown("融合结果已计数，但未返回选择页，已停止")

    def _merge_submission_state(self):
        frame = self.frame
        if frame is None:
            return None
        if self.ocr(*get_ui_box("数据坞标准融合获得声骸"), match="获得声骸", frame=frame):
            return "result"
        if self.ocr(*get_ui_box("数据坞标准融合确认按钮"), match="确认", frame=frame):
            return "confirm"
        return None

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
