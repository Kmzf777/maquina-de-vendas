from app.worker.main import TASK_SPECS


def test_tasks_de_conversao_registradas():
    specs = {name: (kind, secs) for name, kind, _fn, secs in TASK_SPECS}
    assert specs["conversions-sweep"] == ("periodic", 1800)
    assert specs["conversions-send"] == ("periodic", 300)


def test_ticks_de_conversoes_respeitam_o_dry_run(monkeypatch):
    import asyncio
    from app.conversions import sender, sweep
    from app.worker import main as wm
    chamadas = {}
    monkeypatch.setattr(sweep, "run_sweep", lambda dry_run=False: chamadas.setdefault("sweep", dry_run))
    monkeypatch.setattr(sender, "run_sender", lambda dry_run=False: chamadas.setdefault("sender", dry_run))
    monkeypatch.setenv("CONVERSIONS_DRY_RUN", "true")
    asyncio.run(wm._conversions_sweep_tick())
    asyncio.run(wm._conversions_send_tick())
    assert chamadas == {"sweep": True, "sender": True}
