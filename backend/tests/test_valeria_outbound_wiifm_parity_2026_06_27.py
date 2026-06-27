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


def _out_etapa2() -> str:
    """Recorta SÓ o bloco da Etapa 2 (entre '## etapa 2:' e '## etapa 3:') para asserções precisas —
    senão 'proibido'/'pra te direcionar' de outras seções (regra de ouro 0) dariam falso-positivo."""
    low = _out()
    start = low.find("## etapa 2:")
    end = low.find("## etapa 3:")
    assert start != -1 and end != -1 and end > start, "marcadores de Etapa 2/3 não encontrados"
    return low[start:end]


def test_outbound_etapa2_bane_frase_generica():
    etapa2 = _out_etapa2()
    # dentro da Etapa 2, "pra te direcionar..." só aparece como PROIBIÇÃO explícita, nunca como a pergunta
    assert "proibido" in etapa2
    assert "pra te direcionar" in etapa2
    # e a pergunta de qualificação real é a frase-ponte, não a frase genérica
    assert "pra eu ja te trazer o que faz sentido" in etapa2


def test_inbound_etapa2_ponte_preservada_sem_regressao():
    low = get_stage_prompts("valeria_inbound")["secretaria"].lower()
    assert "ponte de valor" in low and "wiifm" in low
