from app.worker.main import TASK_SPECS


def test_tasks_de_conversao_registradas():
    specs = {name: (kind, secs) for name, kind, _fn, secs in TASK_SPECS}
    assert specs["conversions-sweep"] == ("periodic", 1800)
    assert specs["conversions-send"] == ("periodic", 300)
