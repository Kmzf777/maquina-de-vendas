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

Task 3 (C-3) — reacao a erro de ferramenta no atacado ("o cliente NUNCA ve a cozinha")
+ emenda da regra 16 no base (motivo analitico do handoff). Declaracao: codigo
transversal (pricing.py/tools.py — comportamento testado em
test_match_products_tokens_2026_07_03.py) + prompt fluxo inbound, perfil atacado
(valeria_inbound/atacado.py) + 1 emenda no base (vale ambos os fluxos).

Casos reais que motivam a mudanca (janela 02/07):
- Edgar, 02/07 17:14-17:22: calcular_orcamento devolveu "não encontrado" sem opções e
  a Valeria improvisou "opa, parece que o sistema não achou o Suave em grãos de 500g"
  (produto ERRADO — o item inexistente era o Microlote 500g, nao o Suave), 2x, expondo
  "o sistema" ao cliente e substituindo item em silencio no orcamento.
- "Boa tarde.... Luiz", 02/07: o handoff saiu com motivo "handoff por tempo" quando o
  gatilho real era quantidade acima do lote — motivo generico cega o vendedor.
"""
from datetime import datetime

from app.agent.orchestrator import build_system_prompt
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
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
    # nenhuma das frases/dados originais da Etapa 1. Fix review C2: link e cupom agora
    # vivem na BOLHA MESCLADA ("o link é ... e o cupom é ...") — a informacao (URL da
    # loja + codigo ESPECIAL10) continua integralmente presente, so mudou a renderizacao.
    for marker in (
        "que bom, vou te passar um cupom de 10% de desconto pra usar na nossa loja online",
        "vale a pena conhecer, vou te passar um cupom de 10% de desconto pra nossa loja online",
        '"o link é loja.cafecanastra.com e o cupom é ESPECIAL10"',
        "qualquer duvida sobre os cafes, me chama aqui",
    ):
        assert marker in CONSUMO_PROMPT, f"conteudo original da Etapa 1 removido: {marker!r}"


def test_consumo_renderizacao_unica_do_script_do_cupom():
    # Fix review C2: havia 4 formas divergentes do script do cupom no arquivo (bolha com
    # \n\n interno na regra atomica; link/cupom em bolhas separadas na secao "Mensagem com
    # link e cupom"; Exemplo 1; Exemplo 4). Deve sobrar UMA forma — a bolha mesclada — nas
    # 4 renderizacoes (regra atomica, secao do script, Exemplo 1, Exemplo 4).
    assert CONSUMO_PROMPT.count('"o link é loja.cafecanastra.com e o cupom é ESPECIAL10"') == 4
    # as formas antigas sumiram: link com https em bolha propria e cupom em bolha propria
    assert "link: https" not in CONSUMO_PROMPT
    assert '"cupom: ESPECIAL10"' not in CONSUMO_PROMPT
    # a regra atomica proibe empilhar \n\n dentro de uma bolha (mesma linguagem do
    # precedente do base.py, regra 29b: "nao empilhe \n\n dentro de um passo")
    assert "nao empilhe \\n\\n dentro de nenhuma" in CONSUMO_PROMPT
    # brinde autorizado da review: "que bom." com ponto final (violava a regra 22 do base,
    # pre-existente no Exemplo 1) sumiu — virou quebra de bolha
    assert "que bom." not in CONSUMO_PROMPT


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


# ---------------------------------------------------------------------------
# Task 3 (C-3) — "o cliente NUNCA ve a cozinha" em atacado.py (inbound)
# ---------------------------------------------------------------------------

def test_atacado_contem_constraint_cliente_nunca_ve_a_cozinha():
    assert "o cliente NUNCA ve a cozinha" in ATACADO_PROMPT
    # dentro de <critical_constraints> e ANTES das <instructions> (instrucao critica
    # no inicio da secao correta, pratica do guia de prompting da frente)
    cc_start = ATACADO_PROMPT.index("<critical_constraints>")
    cc_end = ATACADO_PROMPT.index("</critical_constraints>")
    pos = ATACADO_PROMPT.index("o cliente NUNCA ve a cozinha")
    instructions_start = ATACADO_PROMPT.index("<instructions>")
    assert cc_start < pos < cc_end < instructions_start


def test_atacado_constraint_proibe_expor_sistema_e_substituir_item():
    cc_start = ATACADO_PROMPT.index("<critical_constraints>")
    cc_end = ATACADO_PROMPT.index("</critical_constraints>")
    block = ATACADO_PROMPT[cc_start:cc_end]
    # proibicoes nucleares do bloco: vazar "o sistema", substituir item em silencio,
    # e o limite de persistencia com motivo especifico no handoff
    assert '"o sistema nao achou"' in block
    assert "PROIBIDO substituir silenciosamente" in block
    assert "usando os nomes DISPONIVEIS que a propria ferramenta listou" in block
    assert "2a falha consecutiva" in block
    assert "nunca motivo generico" in block


def test_atacado_few_shot_edgar_com_marcadores_e_frase_real():
    few_shot_start = ATACADO_PROMPT.index("<few_shot_examples>")
    few_shot_end = ATACADO_PROMPT.index("</few_shot_examples>")
    block = ATACADO_PROMPT[few_shot_start:few_shot_end]
    assert "❌" in block
    assert "✅" in block
    # frase EXATA que o Edgar recebeu de verdade (02/07 17:15) — produto errado + "o sistema"
    assert '"opa, parece que o sistema não achou o Suave em grãos de 500g"' in block
    # resposta correta: tom de vendedora com a variacao real do catalogo
    assert "o Microlote em grãos vem só em pacotes de 250g" in block
    assert "Exemplo 8" in block


def test_atacado_nada_de_existente_foi_removido():
    for marker in (
        "## Pergunta direta tem prioridade absoluta",
        "## Circuit breaker",
        "## Stage lock — nao retornar para consumo apos PJ confirmado",
        "## Frete — nunca assuma regiao sem CEP",
        "## Apresentacao de precos — qualificadores obrigatorios",
        "## Kit Amostra — regra de preco fixo",
        "## Enviar fotos antes de encaminhar",
        "## Handoff para fechamento — regras",
        "## Objecao de preco — maximo 2 tentativas",
        "## Anti-interrogacao — Etapa 1",
        "<critical_constraints>",
        "</critical_constraints>",
        "<instructions>",
        "</instructions>",
        "<few_shot_examples>",
        "</few_shot_examples>",
        "## Exemplo 7 ",
    ):
        assert marker in ATACADO_PROMPT, f"marcador removido/alterado: {marker!r}"


# ---------------------------------------------------------------------------
# Task 3 (C-3) — emenda da regra 16 em base.py (motivo analitico, regra 18b)
# ---------------------------------------------------------------------------

def test_base_regra_16_emenda_motivo_analitico():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert "O motivo segue a regra 18b" in prompt
    assert "PROIBIDO 'handoff por tempo'" in prompt
    assert "pediu quantidade acima do lote" in prompt
    assert "objecao de preco apos 2 contornos" in prompt


def test_base_emenda_do_motivo_esta_dentro_da_regra_16_sem_renumerar():
    # A emenda mora DENTRO do bloco 16 (entre "16. ENCAMINHAR_HUMANO" e "16b."),
    # sem criar numero novo nem renumerar nada.
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    regra_16 = prompt.index("16. ENCAMINHAR_HUMANO")
    regra_16b = prompt.index("16b. HANDOFF VERBAL SEM TOOL")
    emenda = prompt.index("O motivo segue a regra 18b")
    assert regra_16 < emenda < regra_16b
    # invariantes de numeracao: 16b/17/18b continuam existindo uma unica vez
    assert prompt.count("16b. HANDOFF VERBAL SEM TOOL") == 1
    assert prompt.count("18b. OBSERVACOES ANALITICAS") == 1


def test_build_system_prompt_atacado_monta_sem_erro_e_final_instruction_e_ultima():
    lead = {"name": "Edgar", "company": None}
    prompt = build_system_prompt(lead, "atacado")
    assert prompt.rstrip().endswith("</final_instruction>")
    assert "o cliente NUNCA ve a cozinha" in prompt
    assert "O motivo segue a regra 18b" in prompt
    assert prompt.index("o cliente NUNCA ve a cozinha") < prompt.index("<final_instruction>")
    assert prompt.index("O motivo segue a regra 18b") < prompt.index("<final_instruction>")
