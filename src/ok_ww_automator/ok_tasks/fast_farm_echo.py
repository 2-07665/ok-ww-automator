import time
from qfluentwidgets import FluentIcon
from ok import find_color_rectangles

from .char.cartethyia import Cartethyia
from src.task.BaseWWTask import BaseWWTask

boss_health_color = {
    'r': (245, 255),  # Red range
    'g': (30, 185),  # Green range
    'b': (4, 75)  # Blue range
}

class FastFarmEchoTask(BaseWWTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = "单人速刷位置固定的4C"
        self.name = "固定4C速刷"
        self.group_name = "My"
        self.group_icon = FluentIcon.SYNC
        self.icon = FluentIcon.ALBUM
        self.default_config = {"刷多少次": 2000}

        self._fixed_char = Cartethyia(self)

        self._in_combat = False
        self.combat_check_grace_window = 1.0
        self.last_combat_check = 0
        
    def run(self):
        farm_target = self.config.get("刷多少次", 0)
        self.info_set("Fight Count", 0)

        self.ensure_main(esc=True, time_out= 60)
        self.run_until(self.simple_in_combat, "w", time_out=10, running=True)

        for idx in range(farm_target):
            self.log_info(f"战斗: {idx + 1}/{farm_target}")
            self.my_farm_once()
            self.info_incr("Fight Count", 1)

    def simple_pickup_echo(self):
        self.send_key('f', after_sleep=0.3)
        time.sleep(2.4)

# region Combat
    def my_farm_once(self):
        self.wait_until(self.simple_in_combat, time_out=300, raise_if_not_found=False)
        self._fixed_char.one_shot()
        while self.simple_in_combat():
            self._fixed_char.fight()

        self.simple_pickup_echo()
        self._fixed_char.post_fight()

    def simple_in_combat(self):
        now = time.time()
        if self.check_boss():
            self._in_combat = True
            self.last_combat_check = now
            return True
        if self._in_combat:
            if now - self.last_combat_check < self.combat_check_grace_window:
                return True
        self._in_combat = False
        return False
    
    def check_boss(self):
        return self.has_f_break_shield() or self.has_health_bar()

    def has_f_break_shield(self):
        return self.find_one('boss_break_shield') # or self.find_one('boss_break_lock')

    def has_health_bar(self):
        min_height = self.height_of_screen(12 / 2160)
        min_width = self.width_of_screen(100 / 3840)

        boxes = find_color_rectangles(self.frame, boss_health_color,
                                      min_width, min_height,
                                      box=self.box_of_screen(1269 / 3840, 58 / 2160, 2533 / 3840, 200 / 2160))
        if boxes:
            return True
        return False
            
# endregion
