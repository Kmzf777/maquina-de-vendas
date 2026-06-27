"""Ponte de Valor (WIIFM) + contorno de RBO (Anchor-Disrupt-Ask) — correções de prompt.

Caso real: lead 5511971052959 (Demétrio), persona valeria_inbound, stage secretaria.
Erro 1: pergunta de qualificação sem Ponte de Valor. Erro 2: rendição imediata ao
RBO "não estou comprando" (registrar_sem_interesse_atual precoce).

Testes de conteúdo de prompt (substring), no padrão de test_base_prompt.py.
"""
from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt

TZ_BR = timezone(timedelta(hours=-3))


def _base() -> str:
    return build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(TZ_BR)).lower()


# --- Erro 1: Ponte de Valor / WIIFM (global) ---

def test_base_tem_regra_ponte_de_valor_wiifm():
    low = _base()
    assert "ponte de valor" in low
    assert "wiifm" in low
    # a justificativa tem que beneficiar o LEAD, não a operação interna
    assert "beneficie o lead" in low


def test_base_ponte_proibe_justificar_so_com_interesse_interno():
    low = _base()
    # proíbe explicitamente "pra eu te direcionar" como única justificativa
    assert "pra eu te direcionar" in low or "interesse interno" in low


# --- Erro 2: RBO Anchor-Disrupt-Ask (global) ---

def test_base_tem_regra_rbo_anchor_disrupt_ask():
    low = _base()
    assert "rbo" in low
    assert "anchor-disrupt-ask" in low
    # os três passos do framework
    assert "ancore" in low
    assert "quebre o padrao" in low or "quebre o padrão" in low
    assert "baixo atrito" in low


def test_base_rbo_proibe_descarte_na_primeira_negativa_reflexa():
    low = _base()
    assert "registrar_sem_interesse_atual" in low
    # cobre o gatilho exato do caso real
    assert "nao estou comprando" in low or "não estou comprando" in low
    # só descarta se reafirmar depois do contorno
    assert "reafirmar" in low


def test_base_rbo_tem_caminho_de_aceite():
    low = _base()
    # happy path: se o lead aceitar o pedido de baixo atrito, não engaveta — entrega valor + 1 pergunta
    assert "se o lead aceitar" in low
    assert "pergunta leve de descoberta" in low


def test_base_18b_guard_referencia_regra_29b():
    low = _base()
    # a regra 18B aponta para a 29b antes de aceitar negativa reflexa inicial
    assert "regra 29b" in low


def test_base_checklist_tem_item_anti_descarte_precoce():
    low = _base()
    # item de checklist que trava o descarte precoce
    assert "negativa reflexa" in low


# --- secretaria (stage do caso real): Ponte de Valor + few-shot de RBO ---

from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT


def _sec() -> str:
    return SECRETARIA_PROMPT.lower()


def test_secretaria_etapa2_tem_ponte_de_valor():
    low = _sec()
    assert "ponte de valor" in low
    assert "wiifm" in low
    # ainda faz a pergunta de mercado (sem regressão) — frase completa e exata,
    # não a substring frágil "exporta" (que casaria com qualquer "exportacao")
    assert "sua demanda e pro mercado brasileiro ou pra exportacao/mercado externo?" in low


def test_secretaria_tem_fewshot_rbo_anchor_disrupt_ask():
    low = _sec()
    # cobre o gatilho exato do caso real e o contorno
    assert "nao estou comprando" in low or "não estou comprando" in low
    assert "nao to aqui pra te empurrar" in low or "não to aqui pra te empurrar" in low
    # não descarta na primeira negativa
    assert "primeira negativa" in low or "reafirmar" in low


def test_secretaria_fewshot_rbo_tem_continuacao_de_aceite():
    low = _sec()
    # happy path no few-shot: lead aceita ("pode mandar") e a IA entrega valor + 1 pergunta leve
    assert "pode mandar" in low
    assert "negocio ou" in low or "consumo" in low


def test_secretaria_preserva_triagem_imediata_sem_regressao():
    low = _sec()
    # regressão: a triagem de licitação/laudo e o handoff continuam presentes
    assert "triagem imediata" in low
    assert "encaminhar_humano" in low
