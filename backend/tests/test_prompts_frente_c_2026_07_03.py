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

from app.agent.orchestrator import _build_catalog_block, build_system_prompt
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT
from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
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


# ---------------------------------------------------------------------------
# Task 4 (C-4) — higiene de nome: ramo sem-nome trata saudacao como nome ausente
# ---------------------------------------------------------------------------

def test_base_ramo_sem_nome_trata_saudacao_como_nome_ausente():
    # Defesa em profundidade (base.py): mesmo que um nome-saudacao ("Olá, boa tarde")
    # escape da sanitizacao em leads.service.sanitize_display_name, a instrucao do
    # ramo "sem nome" manda a Valeria tratar como SEM nome e chamar salvar_nome — casos
    # reais 01-02/07 ("Olá, boa tarde", "Boa tarde.... Luiz") motivaram a emenda.
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert "Se o cadastro tiver um nome que parece saudacao" in prompt
    assert "descubra o nome real e chame salvar_nome" in prompt


# ---------------------------------------------------------------------------
# Task 5 (C-5) — reforco do marcar_interesse no momento-preco
# ---------------------------------------------------------------------------
# Declaracao: fluxo ambos-via-base (checklist, no base.py compartilhado) + few-shots fluxo
# inbound, perfis atacado (valeria_inbound/atacado.py) e private_label
# (valeria_inbound/private_label.py).
#
# Motivacao (janela 01-02/07): marcar_interesse NAO foi chamado NENHUMA vez (0 follow-ups
# agendados) apesar de 8 conversas chegarem ao momento-preco. A Frente B3 ja criou a rede
# DETERMINISTICA (gatilho pos-preco no processor: quote_flag OU "R$" na resposta final —
# ver test_processor_price_followup_2026_07_03.py) e essa e a rede PRIMARIA, valendo
# independente do LLM chamar ou nao a tool. As mudancas desta task (C-5) sao REFORCO DE
# PROMPT: fazem o sinal RICO (nivel="quente"/"morno" + motivo analitico via
# marcar_interesse, regra 18b) voltar a fluir — sinal que o gatilho deterministico sozinho
# nao entrega (ele so sabe "cotou preco", nao o nivel de interesse nem o motivo qualificado
# pro vendedor humano). A regra 19 do base ("MARCAR_INTERESSE — SOMENTE INTERESSE COMERCIAL
# GENUINO") NAO foi alterada nesta task — C-5 so ADICIONA pressao de checklist + exemplos
# que apontam pra ela, nunca modifica seu texto.


def test_base_checklist_contem_item_26_marcar_interesse_no_momento_preco():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert (
        "26. O lead perguntou preco/condicoes ou pediu orcamento NESTE turno? "
        "Se sim: ja chamei marcar_interesse? (regra 19 — sem isso o follow-up automatico nao arma)"
        in prompt
    )


def test_base_item_26_vem_depois_do_item_25_dentro_do_checklist_sem_colidir():
    # Escopado AO CHECKLIST: ha uma regra 26 pre-existente em <constraints> ("26. LEAD QUE JA
    # E NOSSO CLIENTE"), numeracao independente da lista do checklist — nao e colisao real,
    # mas a contagem so faz sentido restrita ao bloco do checklist.
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    checklist_start = prompt.index("# CHECKLIST ANTES DE RESPONDER")
    instructions_end = prompt.index("</instructions>")
    checklist_block = prompt[checklist_start:instructions_end]
    item_25 = checklist_block.index("25. Prometi enviar/passar algo")
    item_26 = checklist_block.index("26. O lead perguntou preco/condicoes")
    assert item_25 < item_26
    assert checklist_block.count("\n26. ") == 1


def test_base_regra_19_marcar_interesse_intocada():
    # C-5 e reforco de PROMPT (checklist + few-shots) — a regra 19 em si (constraints) nao
    # pode ter sido alterada, duplicada ou movida.
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    assert prompt.count("19. MARCAR_INTERESSE — SOMENTE INTERESSE COMERCIAL GENUINO") == 1
    regra_19 = prompt.index("19. MARCAR_INTERESSE — SOMENTE INTERESSE COMERCIAL GENUINO")
    regra_20 = prompt.index("20. CORRECAO DE IDENTIDADE — ATUALIZAR NOME IMEDIATAMENTE")
    block = prompt[regra_19:regra_20]
    assert "Sem esse sinal, o follow-up automatico nao e agendado." in block


def test_base_nada_de_existente_foi_removido_na_task_5():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    for marker in (
        "25. Prometi enviar/passar algo NESTA mensagem?",
        "24. O lead deu uma negativa REFLEXA",
        "32. PROMESSA DE ENVIO = ENTREGA NO MESMO TURNO",
        "31. LIMITADOR DE HANDOFF",
        "26. LEAD QUE JA E NOSSO CLIENTE",
        "# CHECKLIST ANTES DE RESPONDER",
        "<constraints>",
        "</constraints>",
        "<instructions>",
        "</instructions>",
    ):
        assert marker in prompt, f"marcador removido/alterado: {marker!r}"


# --- atacado.py: Exemplo 9 (calcular_orcamento + marcar_interesse no mesmo turno) --------

def test_atacado_few_shot_marcar_interesse_no_momento_preco():
    few_shot_start = ATACADO_PROMPT.index("<few_shot_examples>")
    few_shot_end = ATACADO_PROMPT.index("</few_shot_examples>")
    block = ATACADO_PROMPT[few_shot_start:few_shot_end]
    assert "Exemplo 9" in block
    assert "marcar_interesse" in block
    assert 'nivel="quente"' in block
    assert "calcular_orcamento" in block
    # motivo analitico (regra 18b), nao generico — e referencia explicita a regra 19
    assert "regra 18b" in block
    assert "regra 19" in block


def test_atacado_few_shot_9_cita_rede_b3_como_primaria_e_isto_como_reforco():
    few_shot_start = ATACADO_PROMPT.index("<few_shot_examples>")
    block = ATACADO_PROMPT[few_shot_start:]
    exemplo_9 = block.index("Exemplo 9")
    trecho = block[exemplo_9:]
    assert "B3" in trecho
    assert "rede primaria" in trecho
    assert "reforco" in trecho


def test_atacado_exemplo_9_mantem_a_voz_da_valeria():
    few_shot_start = ATACADO_PROMPT.index("<few_shot_examples>")
    exemplo_9 = ATACADO_PROMPT.index("## Exemplo 9")
    exemplo_end = ATACADO_PROMPT.index("</few_shot_examples>")
    assert few_shot_start < exemplo_9 < exemplo_end
    trecho = ATACADO_PROMPT[exemplo_9:exemplo_end]
    # qualificador de preco aprovado do atacado (secao "Apresentacao de precos" do arquivo)
    assert "gira em torno de" in trecho or "fica por volta de" in trecho
    # a bolha de resposta ao lead termina em pergunta (1 pergunta, regra do silencio)
    assert "?" in trecho


def test_atacado_nada_de_existente_foi_removido_na_task_5():
    for marker in (
        "## Exemplo 1 ", "## Exemplo 2 ", "## Exemplo 3 ", "## Exemplo 3b ",
        "## Exemplo 4 ", "## Exemplo 5 ", "## Exemplo 6 ", "## Exemplo 7 ", "## Exemplo 8 ",
        "o cliente NUNCA ve a cozinha",
        "<critical_constraints>", "</critical_constraints>",
        "<few_shot_examples>", "</few_shot_examples>",
    ):
        assert marker in ATACADO_PROMPT, f"marcador removido/alterado: {marker!r}"


# --- private_label.py: few-shot analogo (primeira cobertura desta frente p/ este arquivo) -

def test_private_label_few_shot_marcar_interesse_no_momento_preco():
    few_shot_start = PRIVATE_LABEL_PROMPT.index("<few_shot_examples>")
    few_shot_end = PRIVATE_LABEL_PROMPT.index("</few_shot_examples>")
    block = PRIVATE_LABEL_PROMPT[few_shot_start:few_shot_end]
    assert "Exemplo 5" in block
    assert "marcar_interesse" in block
    assert 'nivel="quente"' in block
    assert "regra 18b" in block
    assert "regra 19" in block
    assert "B3" in block
    assert "rede primaria" in block


def test_private_label_segue_formato_local_sem_marcadores_do_atacado():
    # private_label.py NAO usa "## Exemplo N" (formato do atacado.py) nem blocos "Nota:" —
    # usa "Exemplo N — titulo", separador "---" e anotacoes entre colchetes (ex.: "[para e
    # aguarda resposta do cliente]"). O exemplo novo segue ESSE formato local, nao o do
    # arquivo vizinho (constraint da frente: few-shots no MESMO formato dos vizinhos).
    assert "## Exemplo 5" not in PRIVATE_LABEL_PROMPT
    assert "Exemplo 5 —" in PRIVATE_LABEL_PROMPT


def test_private_label_nada_de_existente_foi_removido():
    # Primeira cobertura estrutural deste arquivo na Frente C (nao foi tocado em C1-C4) —
    # trava os marcadores pre-existentes pra qualquer edicao futura da frente.
    for marker in (
        "## Regra Prioritaria — Pergunta Direta",
        "## Vocabulario Proibido",
        "## Circuit Breaker — 8 Turnos",
        "## Regra Anti-Loop — Confirmacao",
        "## Regra de Handoff Limpo",
        "## Limitador de Handoff — Anti-Spam (regra 31)",
        "## Regras Absolutas de Fechamento",
        "<critical_constraints>", "</critical_constraints>",
        "<instructions>", "</instructions>",
        "<few_shot_examples>", "</few_shot_examples>",
        "Exemplo 1 —", "Exemplo 2 —", "Exemplo 3 —", "Exemplo 4 —",
    ):
        assert marker in PRIVATE_LABEL_PROMPT, f"marcador removido/alterado: {marker!r}"


def test_build_system_prompt_private_label_monta_sem_erro_e_final_instruction_e_ultima():
    lead = {"name": "Arthur", "company": None}
    prompt = build_system_prompt(lead, "private_label")
    assert prompt.rstrip().endswith("</final_instruction>")
    assert "marcar_interesse" in prompt
    assert 'nivel="quente"' in prompt
    assert prompt.index("Exemplo 5") < prompt.index("<final_instruction>")


def test_build_system_prompt_atacado_c5_reforco_antes_do_final_instruction():
    lead = {"name": "Edgar", "company": None}
    prompt = build_system_prompt(lead, "atacado")
    assert prompt.rstrip().endswith("</final_instruction>")
    assert "Exemplo 9" in prompt
    assert prompt.index("Exemplo 9") < prompt.index("<final_instruction>")
    # o item 26 do checklist (base.py) tambem precisa estar presente na montagem final
    assert "26. O lead perguntou preco/condicoes" in prompt
    assert prompt.index("26. O lead perguntou preco/condicoes") < prompt.index("<final_instruction>")


# ---------------------------------------------------------------------------
# Fix wave (2026-07-03) — minors do per-task review da Frente C, item C1.
# ---------------------------------------------------------------------------
# C1-2: a ETAPA 0.5 listava "quero saca de 60kg" como exemplo de demanda concreta
# generica, o que fazia essa mensagem SOZINHA (sem outra intencao junto) rodar os
# passos 1-3 do fast-path (reconhecimento + pergunta de classificacao + mudar_stage)
# em vez de ir direto pro Joao Bras. A regra PRECEDENCIA SACA/GRAO VERDE pre-existente
# so cobria o caso multi-intencao (saca + outra demanda na mesma mensagem) — o base.py
# ("## Cliente quer comprar grao cru ou saca de cafe") sempre trata saca como handoff
# direto, sem classificacao nenhuma. Fix: acrescenta ao FINAL do bloco PRECEDENCIA a
# regra de intencao UNICA (nao mexe no paragrafo multi-intencao existente).
#
# C1-1: a pergunta de classificacao do Exemplo 8 (Javier) vinha seca, sem a ponte de
# valor (WIIFM) que a regra 17b do base marca como OBRIGATORIA pra toda pergunta de
# qualificacao/triagem. Fix: prefixa a pergunta do Exemplo 8 com uma ponte de valor
# curta. O Exemplo 9 (Melina) fica como esta — variedade e desejavel, nem todo turno
# precisa da ponte explicita (anti-formula).


def test_secretaria_precedencia_saca_contem_regra_intencao_unica():
    # (a) String-chave estavel da regra nova — nao pina o paragrafo inteiro, so o
    # marcador que precisa sobreviver a qualquer reescrita futura do texto ao redor.
    precedencia_start = SECRETARIA_PROMPT.index("PRECEDENCIA SACA/GRAO VERDE")
    etapa_1 = SECRETARIA_PROMPT.index("ETAPA 1: APRESENTACAO")
    block = SECRETARIA_PROMPT[precedencia_start:etapa_1]
    assert "UNICA demanda" in block


def test_secretaria_precedencia_saca_unica_vai_direto_pro_joao_sem_classificar():
    # A regra de intencao unica precisa mandar pular a classificacao (pergunta +
    # mudar_stage) e chamar encaminhar_humano pro Joao Bras na mesma resposta —
    # mesmo fluxo do base ("Cliente quer comprar grao cru ou saca de cafe").
    precedencia_start = SECRETARIA_PROMPT.index("PRECEDENCIA SACA/GRAO VERDE")
    etapa_1 = SECRETARIA_PROMPT.index("ETAPA 1: APRESENTACAO")
    block = SECRETARIA_PROMPT[precedencia_start:etapa_1]
    assert "UNICA demanda" in block
    unica_pos = block.index("UNICA demanda")
    resto = block[unica_pos:]
    assert "pule" in resto.lower()
    assert 'encaminhar_humano(vendedor="Joao Bras"' in resto
    # intencao unica NAO roteia — mudar_stage so pode ser citado como o passo que se
    # pula, nunca como instrucao de executar
    assert "execute mudar_stage" not in resto
    assert "mudar_stage(" not in resto


def test_secretaria_precedencia_multi_intencao_continua_intacta():
    # Regressao: o paragrafo multi-intencao pre-existente (caso saimon) nao pode ter
    # sido alterado por esta fix wave — cada fragmento abaixo vive numa linha fisica
    # unica do arquivo-fonte, entao a checagem e robusta a como o texto novo foi
    # encaixado ao redor dele.
    assert (
        "PRECEDENCIA SACA/GRAO VERDE (multi-intencao): se o lead menciona saca/grao verde JUNTO de"
        in SECRETARIA_PROMPT
    )
    assert (
        'outra demanda (ex: "saca de 60kg OU cafe com minha marca"), NUNCA ignore a parte da saca:'
        in SECRETARIA_PROMPT
    )
    assert (
        "diga em uma bolha que saca/grao verde e direto com o Joao Bras, e ENTAO conduza a outra"
        in SECRETARIA_PROMPT
    )
    assert "demanda. Nenhuma das duas intencoes pode ficar sem resposta." in SECRETARIA_PROMPT


def test_secretaria_exemplo_8_pergunta_leva_ponte_de_valor_wiifm():
    # (b) A pergunta de classificacao do Exemplo 8 (Javier) agora leva uma ponte de
    # valor (WIIFM) curta ANTES da pergunta, per regra 17b do base. Continua com 1
    # unica pergunta na bolha (regra do silencio) e nao usa a muleta "me diz uma coisa".
    exemplo_8 = SECRETARIA_PROMPT.index("Exemplo 8")
    exemplo_9 = SECRETARIA_PROMPT.index("Exemplo 9")
    block = SECRETARIA_PROMPT[exemplo_8:exemplo_9]
    assistant_pos = block.index("Assistant:")
    nota_pos = block.index("Nota:")
    dialogue = block[assistant_pos:nota_pos]
    assert "sem te encher de coisa que nao e pra voce" in dialogue
    assert "essa compra e pro seu negocio, consumo proprio ou pra colocar sua marca no pacote?" in dialogue
    assert dialogue.count("?") == 1
    assert "me diz uma coisa" not in block.lower()


def test_secretaria_exemplo_9_permanece_inalterado():
    # Regressao: Exemplo 9 (Melina) fica como esta — anti-formula, nem todo turno
    # precisa da ponte de valor explicita.
    exemplo_9 = SECRETARIA_PROMPT.index("Exemplo 9")
    exemplo_10 = SECRETARIA_PROMPT.index("Exemplo 10")
    block = SECRETARIA_PROMPT[exemplo_9:exemplo_10]
    assert '"desconto por volume muda direto conforme a quantidade que voce fecha"' in block
    assert '"essa compra e pro seu negocio ou consumo proprio?"' in block


def test_build_system_prompt_secretaria_fix_wave_c1_monta_sem_erro():
    lead = {"name": "Saca-Unica", "company": None}
    prompt = build_system_prompt(lead, "secretaria")
    assert prompt.rstrip().endswith("</final_instruction>")
    assert "UNICA demanda" in prompt
    assert prompt.index("UNICA demanda") < prompt.index("<final_instruction>")
    assert "sem te encher de coisa que nao e pra voce" in prompt


# ---------------------------------------------------------------------------
# Harmonizacao pos-review (2026-07-03) — mini-wave de 5 itens recomendada pelo
# review final da Frente C. Declaracao: fluxo inbound (secretaria) + ambos-via-base
# (base) + codigo (orchestrator.py). Todos os 5 itens sao clausulas de escopo/excecao
# — nenhuma regra existente foi removida.
#
# Item 1 — secretaria.py Exemplo 10: o anuncio de handoff FUTURO da saca ("ja te
# deixo com ele no fim") e superficie que a regra 16b do base (handoff verbal sem
# tool) bane na letra fria — precisa da excecao explicita: a tool sai no fim do
# funil da OUTRA demanda, nunca fica esquecida.
# Item 2 — base.py circuit breaker "desconto": escopado aos stages comerciais
# (atacado/private_label/exportacao); na SECRETARIA (lead ainda nao classificado)
# vale primeiro a ETAPA 0.5 (reconhecer + classificar).
# Item 3 — base.py ORDEM DE EXECUCAO: se o catalogo/ferramentas do novo estagio
# ainda nao estiverem disponiveis NESTE turno, o hook sai e a pergunta concreta e
# respondida no turno seguinte — nunca inventar valor.
# Item 4 — orchestrator.py _build_catalog_block: harmoniza a frase de produto-fora-
# da-lista com a constraint do atacado (variacao inexistente != produto que nao
# trabalhamos).
# Item 5 (teste em test_outbound_prompt_separation.py, nao aqui — e codigo puro de
# orchestrator, nao pin estrutural de prompt) — sanitize_display_name no call site
# do contexto outbound de 1o turno (orchestrator.py ~L721).
# ---------------------------------------------------------------------------


def test_secretaria_exemplo_10_declara_excecao_regra_16b():
    # Item 1: a Nota do Exemplo 10 declara que o anuncio de handoff FUTURO da saca
    # e a excecao prevista da regra 16b — nao o handoff abandonado que a 16b bane.
    exemplo_10 = SECRETARIA_PROMPT.index("Exemplo 10")
    few_shot_end = SECRETARIA_PROMPT.index("</few_shot_examples>")
    block = SECRETARIA_PROMPT[exemplo_10:few_shot_end]
    assert "excecao prevista da regra 16b do base" in block
    assert "encaminhar_humano sai no fim do funil da outra demanda" in block


def test_base_circuit_breaker_desconto_escopado_por_stage():
    # Item 2: o handoff imediato de desconto vale nos stages comerciais; na
    # secretaria, a ETAPA 0.5 roda primeiro (reconhecer + classificar).
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    situacoes_start = prompt.index("SITUACOES COMERCIAIS")
    proxima_bullet = prompt.index("Lead repetiu a MESMA objecao")
    block = prompt[situacoes_start:proxima_bullet]
    assert "atacado, private_label, exportacao" in block
    assert "ETAPA 0.5" in block
    assert "SECRETARIA" in block
    # regressao: o exemplo do <examples> (contexto de stage comercial) NAO foi tocado
    assert '"tem desconto pra pedido grande?"' in prompt


def test_base_ordem_execucao_contempla_dados_indisponiveis_do_novo_estagio():
    # Item 3: meia-frase nova na ORDEM DE EXECUCAO, dentro da secao certa.
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 7, 3, 10, 0))
    ordem_inicio = prompt.index("# ORDEM DE EXECU")
    modelo_escrita = prompt.index("# MODELO DE ESCRITA")
    dados_indisponiveis = prompt.index("dados do novo estágio ainda não estiverem disponíveis")
    assert ordem_inicio < dados_indisponiveis < modelo_escrita
    assert "NUNCA invente valor" in prompt


def test_catalog_block_harmoniza_variacao_vs_produto_fora_da_lista():
    # Item 4: _build_catalog_block diferencia VARIACAO (peso/moagem) de PRODUTO que
    # a Cafe Canastra nao trabalha, espelhando a constraint do atacado.py.
    block = _build_catalog_block("X")
    assert "VARIAÇÃO de um produto listado" in block
    assert "diga que essa variação não existe e ofereça a mais próxima" in block
    assert "não trabalha" in block
    assert "encaminhe para o Joao Bras" in block
