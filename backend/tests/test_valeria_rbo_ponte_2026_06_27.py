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
