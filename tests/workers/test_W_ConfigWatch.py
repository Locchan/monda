from monda.classes.workers.W_ConfigWatch import W_ConfigWatch


def test_config_watch_does_not_watch_changes():
    assert W_ConfigWatch.watch_config_changes is False


def test_config_watch_work_reads_config(merge_worker):
    # Not in WORKER_CONFIG typically; initialize via bypass like main does
    w = W_ConfigWatch("config_watch", 5)
    w.config = {}
    w.initialized = True
    from monda.utils.status import get_or_create_worker

    entry, _ = get_or_create_worker(w.name)
    w._status_entry = entry
    assert w._initialize() is True
    w._work()  # should not raise
    assert w._refresh_config() == "ok"
