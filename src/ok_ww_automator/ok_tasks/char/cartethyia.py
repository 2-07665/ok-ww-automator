import time

class Cartethyia:
    SKILL_COOLDOWN = 14.0
    SKILL_COOLDOWN_MARGIN = 0.4
    ONE_SHOT_MAX_WAIT = 0.6
    SWORD2_ATTACK_SECONDS = 2.5
    HEAVY_ATTACK_RECOVERY_SECONDS = 1.0

    def __init__(self, task):
        self.task = task
        self.reset()

    def reset(self):
        self.has_sword1 = False # heavy
        self.has_sword2 = False # sustained normal attacks
        self.has_sword3 = False # skill
        self._normal_attack_started_at = None
        self._skill_ready_at = time.monotonic()

    def one_shot(self):
        self._normal_attack_started_at = None
        # A pre-cast E contributes no damage to the new boss: save three swords.
        if self.has_sword1 and self.has_sword2 and self.has_sword3:
            self.task.jump(after_sleep=0.3)
            self.task.click()
            self._consume_swords()
            return

        # E hitting the boss plus a two-sword plunge is enough. Otherwise use normals.
        if self.skill_cd() <= self.ONE_SHOT_MAX_WAIT:
            if not self.has_sword1:
                self.use_heavy_attack()
            wait_time = self.skill_cd()
            if wait_time > 0:
                time.sleep(wait_time)
            self.use_skill()
            self.task.click()
            self._consume_swords()

    def _consume_swords(self):
        self._skill_ready_at -= sum((self.has_sword1, self.has_sword2, self.has_sword3))
        self.has_sword1 = False
        self.has_sword2 = False
        self.has_sword3 = False
        self._normal_attack_started_at = None

    def fight(self):
        for _ in range(3):
            self._normal_attack()
            time.sleep(0.2)

    def _normal_attack(self):
        if self._normal_attack_started_at is None:
            self._normal_attack_started_at = time.monotonic()
        self.task.click()
        if time.monotonic() - self._normal_attack_started_at > self.SWORD2_ATTACK_SECONDS:
            self.has_sword2 = True
    
    def post_fight(self):
        self._normal_attack_started_at = None
        if not self.has_sword1:
            self.use_heavy_attack()

        # Prepare a three-sword plunge; with no sword2, save E's damage for the boss.
        if self.has_sword2 and not self.has_sword3 and self.skill_available():
            self.use_skill()

    def skill_cd(self):
        return self._skill_ready_at - time.monotonic()

    def skill_available(self):
        return self.skill_cd() <= 0

    def use_skill(self):
        self._normal_attack_started_at = None
        self.task.send_key("e")
        self._skill_ready_at = time.monotonic() + self.SKILL_COOLDOWN + self.SKILL_COOLDOWN_MARGIN
        time.sleep(0.4)
        self.has_sword3 = True
        
    def use_heavy_attack(self):
        self._normal_attack_started_at = None
        self.task.mouse_down()
        time.sleep(0.4)
        self.task.mouse_up()
        # Allow the heavy attack to finish before E can accept input.
        time.sleep(self.HEAVY_ATTACK_RECOVERY_SECONDS)
        self.has_sword1 = True
