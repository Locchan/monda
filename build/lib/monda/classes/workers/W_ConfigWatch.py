from monda.classes.base.Worker import Worker
from monda.utils.misc import read_config


class W_ConfigWatch(Worker):

    worker_class_name = "W_ConfigWatch"
    worker_class_name_short = "W:CfgWatch"


    def _initialize(self) -> bool:
        self._update_status("Watching config.")
        return True

    def _work(self) -> None:
        read_config()
