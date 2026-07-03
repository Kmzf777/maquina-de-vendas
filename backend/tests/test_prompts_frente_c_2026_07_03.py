"""Testes estruturais da Frente C — Engenharia de Prompt e Tools (Valeria).

Arquivo unico da frente (criado na Task 1/C-1, estendido pelas tasks seguintes da
mesma frente). NAO sao testes de comportamento de LLM — sao pinos de regressao de
edicao de prompt: presenca dos blocos novos, ausencia dos textos removidos, e
invariantes estruturais (ex.: a montagem final do prompt continua valida e
<final_instruction> permanece a ultima tag).

Task 1 (C-1) — fast-path de demanda concreta na triagem.
Declaracao: fluxo inbound, perfis secretaria (valeria_inbound/secretaria.py) e base
(prompts/base.py — compartilhado inbound+outbound, a emenda vale pros dois fluxos).

Casos reais que motivam a mudanca (janela 01-02/07):
- Javier, 02/07 12:54: pediu "12 pacotes de 250g, quanto fica o total?" e recebeu o
  questionario completo da triagem ("com quem eu to falando?" -> mercado) sem a
  pergunta dele ser respondida.
- Melina, 02/07 15:11: perguntou desconto por volume e levou o script generico de
  deflexao, sem reconhecimento nem resposta.
- saimon, 02/07 14:06: pediu saca de 60kg OU cafe com marca propria; a parte da
  saca foi ignorada (nunca endereçada, nem com o direcionamento pro Joao Bras).
"""
from datetime import datetime

from app.agent.orchestrator import build_system_prompt
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT


# ---------------------------------------------------------------------------
# Task 1 (C-1) — ETAPA 0.5 fast-path em secretaria.py
# ---------------------------------------------------------------------------

def test_secretaria_contem_etapa_0_5_fast_path():
    assert "ETAPA 0.5" in SECRETARIA_PROMPT
    assert "DEMANDA CONCRETA NA ABERTURA" in SECRETARIA_PROMPT


def test_secretaria_etapa_0_5_vem_antes_da_etapa_1_dentro_do_triage_flow():
    triage_start = SECRETARIA_PROMPT.index("<triage_flow>")
    triage_end = SECRETARIA_PROMPT.index("</triage_flow>")
    # Usa o cabecalho da secao ("## ETAPA 0.5:"), nao a string solta "ETAPA 0.5" —
    # essa tambem aparece antes do triage_flow, como referencia cruzada dentro de
    # <critical_constraints> ("... ETAPA 0.5, passo 1)").
    etapa_05 = SECRETARIA_PROMPT.index("## ETAPA 0.5:")
    etapa_1 = SECRETARIA_PROMPT.index("ETAPA 1: APRESENTACAO")
    # ETAPA 0.5 tem prioridade sobre as Etapas 1-3: precisa estar dentro do
    # triage_flow e ANTES da ETAPA 1 (fast-path roda antes da triagem completa).
    assert triage_start < etapa_05 < etapa_1 < triage_end


def test_secretaria_contem_precedencia_saca():
    # Regra da multi-intencao (caso saimon): saca/grao verde nunca fica sem resposta.
    assert "PRECEDENCIA SACA" in SECRETARIA_PROMPT


def test_secretaria_deflexao_generica_isolada_foi_removida():
    # A deflexao antiga respondia SEMPRE com a frase generica, mesmo diante de um
    # pedido objetivo (raiz das falhas Javier/Melina/saimon). A nova regra exige
    # reconhecimento especifico (ETAPA 0.5, passo 1) antes de qualquer deflexao.
    assert 'responda: "vou te explicar tudo isso ja ja' not in SECRETARIA_PROMPT


def test_secretaria_critical_constraints_emenda_reconhecimento():
    assert "<critical_constraints>" in SECRETARIA_PROMPT
    constraints_start = SECRETARIA_PROMPT.index("<critical_constraints>")
    constraints_end = SECRETARIA_PROMPT.index("</critical_constraints>")
    block = SECRETARIA_PROMPT[constraints_start:constraints_end]
    assert "RECONHECA o pedido especifico (ETAPA 0.5, passo 1)" in block


def test_secretaria_few_shots_novos_citam_os_tres_casos_reais():
    few_shot_start = SECRETARIA_PROMPT.index("<few_shot_examples>")
    few_shot_end = SECRETARIA_PROMPT.index("</few_shot_examples>")
    block = SECRETARIA_PROMPT[few_shot_start:few_shot_end]
    assert "Javier" in block
    assert "Melina" in block
    assert "saimon" in block
    # os pedidos concretos dos 3 casos precisam aparecer RECONHECIDOS no exemplo
    assert "12 pacotes de 250g" in block
    assert "desconto" in block.lower()
    assert "saca de 60kg" in block


def test_secretaria_few_shots_sem_promessa_vazia():
    # "ja te respondo" / "ja te conto" isoladas sem entrega sao promessa vazia
    # (raiz da falha Melina). Os novos exemplos nao podem reintroduzir a muleta.
    few_shot_start = SECRETARIA_PROMPT.index("<few_shot_examples>")
    block = SECRETARIA_PROMPT[few_shot_start:].lower()
    assert "ja te respondo" not in block


def test_secretaria_nada_de_existente_foi_removido():
    # Regressao: ETAPAs, tags e o ultimo exemplo pre-existentes continuam intactos.
    for marker in (
        "## ETAPA 0: TRIAGEM IMEDIATA",
        "## ETAPA 1: APRESENTACAO E COLETA DE NOME",
        "## ETAPA 2: IDENTIFICACAO DO MERCADO",
        "## ETAPA 3: IDENTIFICACAO DA DEMANDA ESPECIFICA",
        "## ETAPA 4: QUALIFICACAO E DIRECIONAMENTO",
        "<critical_constraints>",
        "</critical_constraints>",
        "<triage_flow>",
        "</triage_flow>",
        "<few_shot_examples>",
        "</few_shot_examples>",
        "Exemplo 7 ",
    ):
        assert marker in SECRETARIA_PROMPT, f"marcador removido/alterado: {marker!r}"


# ---------------------------------------------------------------------------
# Task 1 (C-1) — ORDEM DE EXECUCAO em base.py (compartilhado inbound + outbound)
# ---------------------------------------------------------------------------

def test_base_contem_regra_pergunta_concreta_pos_mudar_stage():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert "PERGUNTA CONCRETA" in prompt
    assert "ANTES do hook de descoberta do novo est" in prompt  # tolerante a acento


def test_base_regra_pergunta_concreta_esta_na_secao_ordem_de_execucao():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    ordem_inicio = prompt.index("# ORDEM DE EXECU")  # "EXECUÇÃO" — tolerante a acento
    modelo_escrita = prompt.index("# MODELO DE ESCRITA")
    pergunta_concreta = prompt.index("PERGUNTA CONCRETA")
    assert ordem_inicio < pergunta_concreta < modelo_escrita


# ---------------------------------------------------------------------------
# Task 1 (C-1) — build_system_prompt monta sem erro, final_instruction intacta
# ---------------------------------------------------------------------------

def test_build_system_prompt_secretaria_monta_sem_erro_e_final_instruction_e_ultima():
    lead = {"name": "Maria", "company": None}
    prompt = build_system_prompt(lead, "secretaria")
    assert prompt.rstrip().endswith("</final_instruction>")
    assert "ETAPA 0.5" in prompt
    assert "PERGUNTA CONCRETA" in prompt
    assert prompt.index("ETAPA 0.5") < prompt.index("<final_instruction>")
    assert prompt.index("PERGUNTA CONCRETA") < prompt.index("<final_instruction>")
