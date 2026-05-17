from qfluentwidgets import FluentIcon

from ok import Logger, TaskDisabledException
logger = Logger.get_logger(__name__)

from src.task.ForgeryTask import ForgeryTask
from src.task.TacetTask import TacetTask
from src.task.SimulationTask import SimulationTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.BaseCombatTask import BaseCombatTask


class StaminaTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Stamina Task"
        self.group_name = "My"
        self.group_icon = FluentIcon.SYNC
        self.icon = FluentIcon.ALBUM
        self.support_tasks = ["Tacet Suppression", "Forgery Challenge", "Simulation Challenge"]
        self.default_config = {
            'Which to Farm': self.support_tasks[0],
            'Which Tacet Suppression to Farm': 1,  # starts with 1
            'Which Forgery Challenge to Farm': 1,  # starts with 1
            'Material Selection': 'Shell Credit',
        }
        self.config_description = {
            'Which Tacet Suppression to Farm': 'The Tacet Suppression number in the F2 list.',
            'Which Forgery Challenge to Farm': 'The Forgery Challenge number in the F2 list.',
            'Material Selection': 'Resonator EXP / Weapon EXP / Shell Credit',
        }
        material_option_list = ['Resonator EXP', 'Weapon EXP', 'Shell Credit']
        self.config_type = {
            'Which to Farm': {
                'type': "drop_down",
                'options': self.support_tasks
            },
            'Material Selection': {
                'type': 'drop_down',
                'options': material_option_list
            },
        }
        self.description = "Consume excess stamina"

    def run(self):
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=180)

        target = self.config.get('Which to Farm', self.support_tasks[0])

        if target == self.support_tasks[0]:
            self.get_task_by_class(TacetTask).farm_tacet(config=self.config)
        elif target == self.support_tasks[1]:
            self.get_task_by_class(ForgeryTask).farm_forgery(config=self.config)
        else:
            self.get_task_by_class(SimulationTask).farm_simulation(config=self.config)
