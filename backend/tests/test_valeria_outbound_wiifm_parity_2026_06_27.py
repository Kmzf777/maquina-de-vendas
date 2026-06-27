"""Paridade WIIFM no outbound (lacuna exposta pelo sticky-outbound).

O sticky-outbound retem o lead frio na valeria_outbound; a Etapa 2 do outbound ainda usava
"pra te direcionar da melhor forma..." (sem ponte de valor). Espelhamos o WIIFM do inbound.
"""
from app.agent.prompts import get_stage_prompts


def _out() -> str:
    return get_stage_prompts("valeria_outbound")["secretaria"].lower()


def test_outbound_etapa2_tem_ponte_de_valor():
    low = _out()
    assert "ponte de valor" in low
    assert "wiifm" in low
    # a frase-ponte nova (espelhando o inbound) está presente
    assert "pra eu ja te trazer o que faz sentido" in low
    # a pergunta de mercado segue presente
    assert "sua demanda e pro mercado brasileiro ou pra exportacao/mercado externo?" in low


def test_outbound_etapa2_bane_frase_generica():
    low = _out()
    # "pra te direcionar..." agora só pode aparecer como PROIBIÇÃO explícita, não como a pergunta
    assert "proibido" in low
    assert "pra te direcionar" in low


def test_inbound_etapa2_ponte_preservada_sem_regressao():
    low = get_stage_prompts("valeria_inbound")["secretaria"].lower()
    assert "ponte de valor" in low and "wiifm" in low
