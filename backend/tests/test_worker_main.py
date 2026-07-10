"""Registro de domínios do worker: cobertura e isolamento."""
from app.worker import main


def test_task_specs_cobrem_todos_os_dominios():
    names = {spec[0] for spec in main.TASK_SPECS}
    assert names == {
        "broadcasts", "followups", "automation",
        "llm-parking", "memory", "channel-health", "reconcile",
    }


def test_dominios_quentes_sao_event_driven():
    kinds = {spec[0]: spec[1] for spec in main.TASK_SPECS}
    assert kinds["broadcasts"] == "event"
    assert kinds["followups"] == "event"
    assert kinds["automation"] == "event"
    assert kinds["reconcile"] == "periodic"


def test_shim_do_container_aponta_para_o_novo_runtime():
    from app.campaign import worker as shim
    assert shim.run_worker is main.run_worker
