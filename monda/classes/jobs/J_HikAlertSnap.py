from monda.classes.base.Job import Job


class J_HikAlertSnap(Job):

    job_class_name = "Job"
    job_class_name_short = "J:"
    required_config_entries = ["HIK_DEVICE"]

    def __init__(self, name: str, job_config: dict):
        super().__init__(name, job_config)

    def _initialize(self):
        return True

    def _work(self):
        pass