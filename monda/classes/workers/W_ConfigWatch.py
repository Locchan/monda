from monda.classes.base.Worker import Worker
from monda.utils.misc import read_config


class W_ConfigWatch(Worker):

    worker_class_name = "W_ConfigWatch"
    worker_class_name_short = "W:CfgWatch"

    required_config_entries = []

    def _initialize(self):
        return True

    def _work(self):
        read_config()
