import time

from ok import find_color_rectangles
from src.task.BaseWWTask import BaseWWTask

from .char.cartethyia import Cartethyia

boss_health_color = {
    'r': (245, 255),
    'g': (30, 185),
    'b': (4, 75),
}


class FastFarmEchoTask(BaseWWTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = "小卡单人速刷位置固定的4C"
        self.name = "固定4C速刷"
        self.group_name = "My"
        self.default_config = {"刷多少次": 2000}
        self.stop_at = None
        self._fixed_char = Cartethyia(self)
        self._in_combat = False
        self.combat_check_grace_window = 1.0
        self.last_combat_check = 0

    def run(self):
        farm_target = self.config.get("刷多少次", 0)
        self._fixed_char.reset()
        self._in_combat = False
        self.last_combat_check = 0
        self.info_set("Fight Count", 0)

        self.ensure_main(esc=True, time_out= 60)
        self.run_until(self.simple_in_combat, "w", time_out=10, running=True)

        idx = 0
        while time.monotonic() < self.stop_at if self.stop_at is not None else idx < farm_target:
            idx += 1
            self.log_info(f"战斗: {idx}" if self.stop_at is not None else f"战斗: {idx}/{farm_target}")
            self.my_farm_once()

    def simple_pickup_echo(self):
        self.send_key('f', after_sleep=0.3)
        time.sleep(2.4)

    def my_farm_once(self):
        self.wait_until(self.simple_in_combat, time_out=300, raise_if_not_found=False)
        self._fixed_char.one_shot()
        while self.simple_in_combat():
            self._fixed_char.fight()
        self.info_incr("Fight Count", 1)
        self.simple_pickup_echo()
        self._fixed_char.post_fight()

    def simple_in_combat(self):
        now = time.monotonic()
        frame = self.frame
        if frame is None or not getattr(frame, "size", 0) or not frame.any():
            return self._in_combat
        if self.check_boss(frame):
            self._in_combat = True
            self.last_combat_check = now
            return True
        if self._in_combat and now - self.last_combat_check < self.combat_check_grace_window:
            return True
        self._in_combat = False
        return False

    def check_boss(self, frame):
        return self.find_one('boss_break_shield', frame=frame) or self.has_health_bar(frame)

    def has_health_bar(self, frame):
        min_height = max(1, self.height_of_screen(12 / 2160))
        min_width = max(1, self.width_of_screen(100 / 3840))
        boxes = find_color_rectangles(
            frame, boss_health_color, min_width, min_height,
            box=self.box_of_screen(1269 / 3840, 58 / 2160, 2533 / 3840, 200 / 2160),
        )
        return bool(boxes)
