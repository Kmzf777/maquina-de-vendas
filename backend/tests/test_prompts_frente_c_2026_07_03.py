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

Task 2 (C-2) — promessa de envio = entrega no mesmo turno + consumo atomico + anti-eco
de despedida. Declaracao: fluxo ambos-via-base (regra 32 + item 25 do checklist, no
base.py compartilhado) e perfis base + consumo (valeria_inbound/consumo.py, inbound).

Casos reais que motivam a mudanca (janela 01-02/07):
- Melina, 02/07 15:14: recebeu "vou te passar um cupom de 10% de desconto pra primeira
  compra la" e o cupom NUNCA veio — a Valeria anunciou o cupom num turno e nao entregou
  o link/codigo no mesmo turno (nem depois). Caso DIFERENTE do Melina citado acima na
  Task 1 (aquele e as 15:11, pergunta de desconto ignorada; este e as 15:14, promessa de
  cupom sem entrega).
- Javier, 02/07 14:57-14:58: depois da despedida "bom café pra você", reagiu com 👍 e
  recebeu a MESMA despedida "bom café pra você" de novo (eco). O Javier do cupom, em
  contraste, recebeu o dele inline no mesmo turno (link + ESPECIAL10) — mostra que o
  padrao correto ja existia mas nao era garantido/obrigatorio no prompt.
"""
from datetime import datetime

from app.agent.orchestrator import build_system_prompt
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT
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


# ---------------------------------------------------------------------------
# Task 2 (C-2) — regra 32 (promessa=entrega no mesmo turno) + checklist 25 em base.py
# ---------------------------------------------------------------------------

def test_base_contem_regra_32_promessa_entrega_mesmo_turno():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert "PROMESSA DE ENVIO = ENTREGA NO MESMO TURNO" in prompt
    # cita a falha real (Melina, 02/07) que motivou a regra — a frase quebra linha no
    # source (mesmo estilo de wrap das demais regras do arquivo), entao checa em 2 partes.
    assert "vou te passar um" in prompt
    assert "cupom de 10%" in prompt
    assert "o cupom nunca veio" in prompt


def test_base_regra_32_numeracao_nao_colide():
    # O arquivo ia ate a regra 31 (LIMITADOR DE HANDOFF) antes desta task. Garante que a
    # nova regra 32 nao duplica um numero ja existente e fica no lugar certo: logo apos a
    # 31, ainda dentro de <constraints>, antes da secao de tools.
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert prompt.count("\n32. ") == 1
    constraints_start = prompt.index("<constraints>")
    constraints_end = prompt.index("</constraints>")
    regra_31 = prompt.index("31. LIMITADOR DE HANDOFF")
    regra_32 = prompt.index("32. PROMESSA DE ENVIO")
    tools_section = prompt.index("# TOOLS OBRIGATORIAS")
    assert constraints_start < regra_31 < regra_32 < tools_section < constraints_end


def test_base_checklist_contem_item_25_promessa():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert "25. Prometi enviar/passar algo NESTA mensagem?" in prompt
    checklist_start = prompt.index("# CHECKLIST ANTES DE RESPONDER")
    item_24 = prompt.index("24. O lead deu uma negativa REFLEXA")
    item_25 = prompt.index("25. Prometi enviar/passar algo")
    instructions_end = prompt.index("</instructions>")
    assert checklist_start < item_24 < item_25 < instructions_end


def test_base_nada_de_existente_foi_removido_na_task_2():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    for marker in (
        "31. LIMITADOR DE HANDOFF",
        "24. O lead deu uma negativa REFLEXA",
        "# TOOLS OBRIGATORIAS",
        "# CHECKLIST ANTES DE RESPONDER",
        "<constraints>",
        "</constraints>",
        "<instructions>",
        "</instructions>",
    ):
        assert marker in prompt, f"marcador removido/alterado: {marker!r}"


# ---------------------------------------------------------------------------
# Task 2 (C-2) — REGRA ATOMICA DO CUPOM + anti-eco de despedida em consumo.py
# ---------------------------------------------------------------------------

def test_consumo_contem_regra_atomica_do_cupom():
    assert "REGRA ATOMICA DO CUPOM" in CONSUMO_PROMPT
    assert "SAEM NO MESMO TURNO" in CONSUMO_PROMPT
    assert "PROIBIDO enviar a 1a bolha sem as demais no mesmo turno" in CONSUMO_PROMPT


def test_consumo_regra_atomica_esta_na_etapa_1_dentro_de_instructions():
    instructions_start = CONSUMO_PROMPT.index("<instructions>")
    instructions_end = CONSUMO_PROMPT.index("</instructions>")
    etapa_1 = CONSUMO_PROMPT.index("## Etapa 1: Loja Online")
    regra_atomica = CONSUMO_PROMPT.index("### REGRA ATOMICA DO CUPOM")
    etapa_2 = CONSUMO_PROMPT.index("## Etapa 2: Encerramento")
    assert instructions_start < etapa_1 < regra_atomica < etapa_2 < instructions_end


def test_consumo_regra_atomica_preserva_conteudo_original_da_etapa_1():
    # A regra atomica so TORNA indivisivel o que ja existia — nao pode ter apagado
    # nenhuma das frases/dados originais da Etapa 1 (link/cupom/frases).
    for marker in (
        "que bom, vou te passar um cupom de 10% de desconto pra usar na nossa loja online",
        "vale a pena conhecer, vou te passar um cupom de 10% de desconto pra nossa loja online",
        "link: https://loja.cafecanastra.com",
        "cupom: ESPECIAL10",
        "qualquer duvida sobre os cafes, me chama aqui",
    ):
        assert marker in CONSUMO_PROMPT, f"conteudo original da Etapa 1 removido: {marker!r}"


def test_consumo_few_shot_negativo_usa_frase_real_da_melina():
    few_shot_start = CONSUMO_PROMPT.index("<few_shot_examples>")
    block = CONSUMO_PROMPT[few_shot_start:]
    assert "❌" in block
    assert "✅" in block
    # frase exata que a Melina recebeu de verdade (02/07 15:14) — o cupom nunca veio.
    assert '"vou te passar um cupom de 10% de desconto pra primeira compra la"' in block


def test_consumo_contem_regra_anti_eco_despedida():
    assert "ANTI-ECO DE DESPEDIDA" in CONSUMO_PROMPT
    assert "nunca o mesmo texto 2x" in CONSUMO_PROMPT
    critical_start = CONSUMO_PROMPT.index("<critical_constraints>")
    critical_end = CONSUMO_PROMPT.index("</critical_constraints>")
    anti_eco = CONSUMO_PROMPT.index("ANTI-ECO DE DESPEDIDA")
    assert critical_start < anti_eco < critical_end


def test_consumo_few_shot_anti_eco_nao_repete_a_mesma_despedida():
    few_shot_start = CONSUMO_PROMPT.index("<few_shot_examples>")
    block = CONSUMO_PROMPT[few_shot_start:]
    # o gatilho (reacao do lead pos-despedida) e a resposta nova precisam estar no exemplo,
    # e a resposta nova NAO pode ser a despedida repetida (caso real Javier).
    assert "👍" in block
    exemplo_5 = block.index("Exemplo 5")
    trecho = block[exemplo_5:]
    assert '"valeu"' in trecho or "to por aqui" in trecho


def test_consumo_nada_de_existente_foi_removido():
    for marker in (
        "<critical_constraints>",
        "</critical_constraints>",
        "REGRA 1 — NAO REPITA O LINK",
        "REGRA 2 — PERGUNTA DIRETA",
        "REGRA 3 — SEM RETOMADA",
        "<instructions>",
        "</instructions>",
        "## Etapa 2: Encerramento apos link e cupom",
        "### Consumo nao e encerramento definitivo",
        "## Situacoes adversas",
        "<few_shot_examples>",
        "</few_shot_examples>",
        "Exemplo 1 ",
        "Exemplo 2 ",
        "Exemplo 3 ",
    ):
        assert marker in CONSUMO_PROMPT, f"marcador removido/alterado: {marker!r}"


def test_build_system_prompt_consumo_monta_sem_erro_e_final_instruction_e_ultima():
    lead = {"name": "Melina", "company": None}
    prompt = build_system_prompt(lead, "consumo")
    assert prompt.rstrip().endswith("</final_instruction>")
    assert "REGRA ATOMICA DO CUPOM" in prompt
    assert "PROMESSA DE ENVIO = ENTREGA NO MESMO TURNO" in prompt
    assert prompt.index("REGRA ATOMICA DO CUPOM") < prompt.index("<final_instruction>")
    assert prompt.index("PROMESSA DE ENVIO") < prompt.index("<final_instruction>")
