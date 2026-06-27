"""Tom robotizado (caso Rubens 5531999844461): banir a fórmula fixa "[fato] é [elogio]"."""
from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT

TZ = timezone(timedelta(hours=-3))


def _base() -> str:
    return build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(TZ)).lower()


def test_base_tem_regra_anti_formula():
    low = _base()
    assert "anti-formula" in low or "anti-fórmula" in low
    # proíbe o molde mecânico elogio-a-cada-turno
    assert "elogio" in low
    assert "todo turno" in low or "toda mensagem" in low or "a cada turno" in low


def test_base_anti_formula_cita_padrao_proibido():
    low = _base()
    # cita o padrão concreto que apareceu na falha (fato repetido + "é" + elogio genérico)
    assert "é um ponto ótimo" in low or "é um grande diferencial" in low or "[fato]" in low or "[elogio]" in low


def test_atacado_fewshot_direto_ao_ponto_sem_elogio():
    low = ATACADO_PROMPT.lower()
    # existe um exemplo que NÃO abre com elogio — vai direto ao ponto
    assert "direto ao ponto" in low
    # a Nota alerta contra elogiar toda fala do lead
    assert "sem elogiar" in low or "nao elogie" in low or "não elogie" in low
