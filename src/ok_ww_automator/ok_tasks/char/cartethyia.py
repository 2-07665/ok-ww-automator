import time

class Cartethyia:

    def __init__(self, task):
        self.task = task
        self.has_sword1 = False # heavy
        #self.has_sword2 = False # a4
        self.has_sword3 = False # skill
        
        self.last_skill_time = time.time() - 12.0

    def one_shot(self):
        if self.has_sword3:
            self.task.jump(after_sleep=0.3)
            self.task.click()
            self.has_sword1 = False
            self.has_sword3 = False
            return
        
        wait_time = self.skill_cd()
        if wait_time < 1.0:
            if wait_time > 0.0:
                time.sleep(wait_time)
            self.use_skill()
            self.task.click()
            self.has_sword1 = False
            self.has_sword3 = False

    def fight(self):
        self.task.click()
        time.sleep(0.2)
        self.task.click()
        time.sleep(0.2)
        self.task.click()
        time.sleep(0.2)
    
    def post_fight(self):
        if self.skill_available():
            self.use_skill()

        if not self.has_sword1:
            self.use_heavy_attack()

    def skill_cd(self):
        return self.last_skill_time + 12.0 - time.time()

    def skill_available(self):
        return True if self.skill_cd() < 0 else False

    def use_skill(self):
        self.task.send_key("e")
        self.last_skill_time = time.time()
        time.sleep(0.4)
        self.has_sword3 = True
        
    def use_heavy_attack(self):
        self.task.mouse_down()
        time.sleep(0.4)
        self.task.mouse_up()
        self.has_sword1 = True