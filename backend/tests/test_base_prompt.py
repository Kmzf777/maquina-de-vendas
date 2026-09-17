from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt, build_context_block

TZ_BR = timezone(timedelta(hours=-3))

def _now():
    return datetime.now(TZ_BR)


def test_base_prompt_no_context():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "Valeria" in prompt
    assert "Cafe Canastra" in prompt
    assert "CONTEXTO DO LEAD" not in prompt


def test_base_prompt_with_name():
    prompt = build_base_prompt(lead_name="João", lead_company=None, now=_now())
    assert "João" in prompt


# ── Implicit caching: prefixo estatico estavel + volatil por ultimo ──────────
def test_base_prompt_static_prefix_is_identical_across_leads():
    """GARANTIA DE CACHE: tudo ANTES de <context> tem que ser byte-identico entre leads
    diferentes — senao o implicit caching do Gemini nao pega (prefixo instavel). Este teste
    trava a regressao de reintroduzir dado volatil (nome/data/dossie) antes de <context>."""
    now = _now()
    p1 = build_base_prompt("João", "Cafeteria A", now,
                           lead_context={"name": "João", "notes": "quer 50kg", "rolling_summary": "## DOSSIÊ DO LEAD\n* X"})
    p2 = build_base_prompt("Maria", "Hotel Sol", now,
                           lead_context={"name": "Maria", "notes": "quer 200kg", "rolling_summary": "## DOSSIÊ DO LEAD\n* Y"})

    assert "<context>" in p1 and "<context>" in p2
    prefix1 = p1.split("<context>")[0]
    prefix2 = p2.split("<context>")[0]
    # o prefixo estatico (role+constraints+instructions+examples) e igual byte a byte
    assert prefix1 == prefix2, "prefixo estatico divergiu entre leads — implicit caching quebrado"
    # e o prefixo carrega o grosso do prompt (o corpo estatico), nao um pedaco minusculo
    assert len(prefix1) > 20000, "prefixo estatico pequeno demais — bloco estatico nao esta no prefixo"


def test_base_prompt_volatile_content_comes_after_static_body():
    """O bloco volatil <context> (nome/empresa/dossie) vem DEPOIS do corpo estatico
    (<examples> e o ultimo bloco estatico antes de <context>)."""
    ctx = {"name": "Maria", "company": "Hotel Sol", "rolling_summary": "## DOSSIÊ DO LEAD\n* memoria viva"}
    prompt = build_base_prompt(None, None, _now(), lead_context=ctx)
    idx_examples = prompt.find("<examples>")
    idx_context = prompt.find("<context>")
    idx_name = prompt.find("Maria")
    assert idx_examples != -1 and idx_context != -1
    assert idx_context > idx_examples, "<context> deve vir depois de <examples>"
    assert idx_name > idx_context, "conteudo volatil (nome) deve estar dentro/depois de <context>"
    # nada de dado do lead vaza pro corpo estatico
    assert "Maria" not in prompt.split("<context>")[0]
    assert "memoria viva" not in prompt.split("<context>")[0]


def test_base_prompt_exige_ponto_de_interrogacao():
    """A regra 'sem ponto final' nao pode derrubar o '?': perguntas DEVEM terminar com '?'."""
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "PONTO DE INTERROGACAO OBRIGATORIO" in prompt
    # a regra de ponto final permanece (so o '.' e banido, intencional)
    assert "SEM PONTO FINAL" in prompt
    low = prompt.lower()
    assert "termina com \"?\"" in low or "terminar com \"?\"" in low or "terminar toda frase interrogativa com \"?\"" in low


def test_base_prompt_with_lead_context_name():
    ctx = {"name": "Maria", "company": "Hotel Sol", "previous_stage": "atacado", "notes": "Quer 50kg/mês"}
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now(), lead_context=ctx)
    assert "Maria" in prompt
    assert "Hotel Sol" in prompt
    assert "atacado" in prompt
    assert "50kg" in prompt


def test_base_prompt_lead_context_overrides_name():
    """lead_context.name takes priority over lead_name when both provided."""
    ctx = {"name": "Maria"}
    prompt = build_base_prompt(lead_name="João", lead_company=None, now=_now(), lead_context=ctx)
    assert "Maria" in prompt


def test_private_label_prompt_responde_pergunta_direta():
    """A regra de perguntas diretas deve estar no prompt de private_label."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert "pergunta direta" in prompt_lower, (
        "Prompt private_label não contém a regra de pergunta direta"
    )
    assert "antes de qualquer" in prompt_lower or "responda a pergunta primeiro" in prompt_lower, (
        "Regra de prioridade ausente"
    )


def test_atacado_prompt_responde_pergunta_direta():
    """A regra de perguntas diretas deve estar no prompt de atacado."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    assert "pergunta direta" in prompt_lower, (
        "Prompt atacado não contém a regra de pergunta direta"
    )
    # Regra deve aparecer antes das etapas
    idx_regra = prompt_lower.find("pergunta direta")
    for marker in ["etapa 1", "## etapa", "fluxo:"]:
        idx_marker = prompt_lower.find(marker)
        if idx_marker != -1:
            assert idx_regra < idx_marker, (
                f"Regra de pergunta direta deve aparecer antes de '{marker}' no prompt"
            )
            break


def test_atacado_prompt_tem_circuit_breaker():
    """O prompt de atacado deve ter circuit breaker para evitar loop."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    tem_circuit_breaker = (
        "CIRCUIT BREAKER" in ATACADO_PROMPT or
        "circuit breaker" in ATACADO_PROMPT.lower()
    )
    assert tem_circuit_breaker, (
        "Prompt atacado não contém CIRCUIT BREAKER para evitar loop"
    )


def test_atacado_prompt_guardrail_registrar_pedido():
    """O prompt de atacado deve distinguir pedido confirmado de orçamento."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    tem_guardrail = (
        "orcamento" in prompt_lower or
        "orçamento" in prompt_lower or
        "nao registrar" in prompt_lower or
        "não registrar" in prompt_lower or
        "quanto fica" in prompt_lower
    )
    assert tem_guardrail, (
        "Prompt atacado não distingue pedido confirmado de orçamento/cotação"
    )


def test_atacado_prompt_fardo_escala_joao_bras():
    """Quando lead pede preço de fardo, prompt deve obrigar escalação para João Brás."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    assert "fardo" in prompt_lower, (
        "Prompt atacado não contém instrução para fardo"
    )
    assert "nao cite preco por unidade" in prompt_lower or \
           "nao sao precos de fardo" in prompt_lower or \
           "preco de fardo" in prompt_lower, (
        "Prompt atacado não instrui que preços unitários ≠ preços de fardo"
    )


def test_consumo_prompt_anti_loop():
    """Prompt consumo deve ter regra anti-loop após link enviado."""
    from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT
    assert "NAO REPITA O LINK" in CONSUMO_PROMPT or "NAO repita o link" in CONSUMO_PROMPT, (
        "Prompt consumo não contém regra anti-repetição de link"
    )
    assert "PERGUNTA DIRETA" in CONSUMO_PROMPT or "pergunta direta" in CONSUMO_PROMPT.lower(), (
        "Prompt consumo não contém regra de pergunta direta pós-link"
    )
    assert "SEM RETOMADA" in CONSUMO_PROMPT or "retomada" in CONSUMO_PROMPT.lower(), (
        "Prompt consumo não contém regra de sem retomada"
    )


def test_base_prompt_silencio_pos_handoff():
    """Base prompt deve ter regra de silêncio após encaminhar_humano."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime, timezone, timedelta
    prompt = build_base_prompt(
        lead_name=None, lead_company=None,
        now=datetime.now(timezone(timedelta(hours=-3)))
    )
    assert "ULTIMO TURNO" in prompt or "ultimo turno" in prompt.lower(), (
        "Base prompt não contém regra de silêncio pós-handoff (ULTIMO TURNO)"
    )
    assert "NAO pergunte nome" in prompt or "nao pergunte nome" in prompt.lower(), (
        "Base prompt não proíbe perguntar nome após handoff"
    )


def test_private_label_proibe_nome_apos_handoff():
    """Prompt private_label deve proibir perguntar nome após handoff."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert ("proibido na mensagem de handoff" in prompt_lower or
            "proibido" in prompt_lower and "handoff" in prompt_lower), (
        "Prompt private_label não contém proibição explícita na mensagem de handoff"
    )


def test_private_label_calcula_preco_por_quantidade():
    """Prompt private_label deve ter regra de cálculo de preço por quantidade."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert "calcule" in prompt_lower or "calcul" in prompt_lower, (
        "Prompt private_label não contém instrução de cálculo por quantidade"
    )
    assert "nao sabe calcular" in prompt_lower or "nao diga que nao sabe" in prompt_lower, (
        "Prompt private_label não proíbe dizer que não sabe calcular"
    )


def test_atacado_fardo_qualifica_antes_de_escalar():
    """Prompt atacado deve pedir produto antes de escalar fardo quando não há qualificação prévia."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    assert "qualificacao previa" in prompt_lower or "sem qualificacao" in prompt_lower or \
           "nao ha qualificacao" in prompt_lower, (
        "Prompt atacado não contém exceção de qualificação prévia para fardo"
    )
    assert "qual produto voce precisa" in ATACADO_PROMPT, (
        "Prompt atacado não pergunta qual produto antes de escalar fardo sem contexto"
    )


def test_base_prompt_espelha_saudacao_lead():
    """Base prompt deve ter regra de espelhar a saudação do lead."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime, timezone, timedelta
    prompt = build_base_prompt(
        lead_name=None, lead_company=None,
        now=datetime.now(timezone(timedelta(hours=-3)))
    )
    assert "SAUDACAO DO LEAD" in prompt, (
        "Base prompt não contém regra SAUDACAO DO LEAD"
    )
    assert "ESPELHE" in prompt, (
        "Base prompt não contém instrução ESPELHE para saudação do lead"
    )


def test_atacado_inbound_handoff_instrui_encaminhar_humano():
    """Seção de handoff do atacado inbound deve instruir encaminhar_humano diretamente."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    # Encontra a seção de handoff (case-insensitive)
    for marker in ["## etapa de handoff para fechamento", "etapa de handoff", "handoff para fechamento"]:
        idx = prompt_lower.find(marker)
        if idx != -1:
            handoff_section = ATACADO_PROMPT[idx:]
            assert "encaminhar_humano" in handoff_section
            return
    assert False, "Seção de handoff não encontrada no prompt atacado"


def test_private_label_inbound_etapa3_responde_todas_perguntas():
    """Etapa 3 do private_label não deve limitar respostas a 1 pergunta antes do handoff."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    # O texto antigo proibia responder mais de 1 pergunta antes do handoff
    assert "no maximo 1 pergunta de detalhe" not in prompt_lower
    # Deve instruir a responder todas as perguntas
    assert ("responda quantas" in prompt_lower or
            "todas as perguntas" in prompt_lower or
            "perguntas diretas" in prompt_lower), (
        "Prompt private_label não instrui a responder perguntas diretas antes do handoff"
    )



def test_base_prompt_regra_nome_moderacao_forte():
    """base_prompt deve conter regra explícita de frequência máxima de uso do nome."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    prompt = build_base_prompt("Débora", None, datetime.now())
    assert "4-5" in prompt or "cinco" in prompt or "5 turnos" in prompt, (
        "Regra de frequência de nome (máx 1 vez a cada 4-5 turnos) não encontrada no prompt."
    )
    assert "consecutiv" in prompt.lower(), (
        "Regra proibindo uso do nome em mensagens consecutivas não encontrada no prompt."
    )


def test_base_prompt_nome_no_antipadrao():
    """ANTI-PADRÕES deve listar repetição de nome como proibido."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    prompt = build_base_prompt("Débora", None, datetime.now())
    antipadrao_section = prompt.split("ANTI-PADROES")[1].split("COMO VOCE FALA")[0] if "ANTI-PADROES" in prompt else ""
    assert "nome" in antipadrao_section.lower(), (
        "ANTI-PADROES não menciona proibição de repetição do nome do lead."
    )


def test_base_prompt_checklist_verifica_nome():
    """CHECKLIST deve incluir verificação de uso excessivo do nome."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    prompt = build_base_prompt("Débora", None, datetime.now())
    checklist_section = prompt.split("CHECKLIST ANTES DE RESPONDER")[1] if "CHECKLIST ANTES DE RESPONDER" in prompt else ""
    assert "nome" in checklist_section.lower(), (
        "CHECKLIST não inclui verificação de uso do nome do lead."
    )


def test_private_label_inbound_preco_vem_do_catalogo():
    """Preços não são mais hardcoded no prompt — vêm do <catalogo_de_produtos>."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "R$26,70" not in PRIVATE_LABEL_PROMPT, "Preço hardcoded ainda presente no inbound"
    assert "R$48,70" not in PRIVATE_LABEL_PROMPT, "Preço hardcoded ainda presente no inbound"
    assert "<catalogo_de_produtos>" in PRIVATE_LABEL_PROMPT, "Diretriz de catálogo ausente no inbound"


def test_private_label_inbound_sem_produtos_removidos():
    """Drip Coffee e Cápsulas Nespresso não devem estar no prompt inbound."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "Drip Coffee" not in PRIVATE_LABEL_PROMPT
    assert "Capsulas Nespresso" not in PRIVATE_LABEL_PROMPT


def test_private_label_outbound_preco_vem_do_catalogo():
    """Preços não são mais hardcoded no prompt — vêm do <catalogo_de_produtos>."""
    from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT
    assert "R$26,70" not in PRIVATE_LABEL_PROMPT, "Preço hardcoded ainda presente no outbound"
    assert "R$48,70" not in PRIVATE_LABEL_PROMPT, "Preço hardcoded ainda presente no outbound"
    assert "<catalogo_de_produtos>" in PRIVATE_LABEL_PROMPT, "Diretriz de catálogo ausente no outbound"


def test_private_label_outbound_sem_produtos_removidos():
    """Drip Coffee e Cápsulas Nespresso não devem estar no prompt outbound."""
    from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT
    assert "Drip Coffee" not in PRIVATE_LABEL_PROMPT
    assert "Capsulas Nespresso" not in PRIVATE_LABEL_PROMPT


def test_outbound_secretaria_trata_abertura_template():
    from app.agent.prompts import get_stage_prompts
    p = get_stage_prompts("valeria_outbound")["secretaria"]
    # seção dedicada a responder o lead após o template "atualizando cadastro / Falo com X?"
    assert "## RESPOSTA À ABERTURA" in p
    assert "cadastro" in p.lower()


def test_outbound_handoff_para_joao():
    from app.agent.prompts import get_stage_prompts
    full = "\n".join(get_stage_prompts("valeria_outbound").values())
    assert "João" in full


# ── Nome proprio acima da minuscula + fim do pedido de nome (17/09/2026) ─────
# Auditoria de 90 dias: 22% das auto-mencoes saem "valeria" e 18,3% das mencoes
# ao nome do lead saem minusculas — a regra de minuscula, por vir PRIMEIRO e sem
# subordinacao, vencia a lista de excecoes. E a pergunta de nome (8 ocorrencias
# reais, ultima em 14/08) e atrito puro: 97% dos leads ja chegam com nome.

def test_estilo_enuncia_nome_proprio_antes_da_minuscula():
    """A regra dura de nome proprio precisa vir ANTES da regra de minusculas — e a
    minuscula tem que estar explicitamente subordinada a ela."""
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    idx_proprio = prompt.find("NOME PROPRIO SEMPRE COM MAIUSCULA")
    idx_minuscula = prompt.find("MINUSCULAS EM TUDO QUE NAO FOR NOME PROPRIO")
    assert idx_proprio != -1, "regra dura de nome proprio ausente na secao ## Estilo"
    assert idx_minuscula != -1, "regra de minuscula subordinada ausente na secao ## Estilo"
    assert idx_proprio < idx_minuscula, (
        "a minuscula voltou a ser enunciada antes do nome proprio — e a primeira regra "
        "que o modelo obedece (foi assim que 'aqui é a valeria' saiu 340x)"
    )
    # a formulacao antiga (minuscula como regra dominante) nao pode voltar
    assert "MINUSCULAS POR PADRAO" not in prompt


def test_estilo_traz_a_saudacao_de_abertura_como_exemplo():
    """Caso de maior volume da auditoria (340 disparos) entra como par CORRETO/ERRADO."""
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert 'CORRETO: "aqui é a Valéria, do comercial da Café Canastra"' in prompt
    assert 'ERRADO: "aqui é a valeria, do comercial da café canastra"' in prompt
    # cidade/estado generico segue no enunciado: a guarda deterministica NAO cobre
    assert "cidades/estados" in prompt


def test_voice_card_enuncia_nome_proprio_antes_da_minuscula():
    """O cartao de voz do follow-up carrega a copia condensada da mesma regra."""
    from app.agent.prompts.voice_card import VALERIA_VOICE_CARD
    idx_proprio = VALERIA_VOICE_CARD.find("NOME PROPRIO SEMPRE COM MAIUSCULA")
    idx_minuscula = VALERIA_VOICE_CARD.find("MINUSCULAS EM TUDO QUE NAO FOR NOME PROPRIO")
    assert idx_proprio != -1 and idx_minuscula != -1
    assert idx_proprio < idx_minuscula
    assert "MINUSCULAS POR PADRAO" not in VALERIA_VOICE_CARD


def test_contexto_sem_nome_nao_manda_perguntar_o_nome():
    """As perguntas literais saem do prompt — o modelo copia o que le."""
    block = build_context_block(lead_name=None, lead_company=None, now=_now())
    low = block.lower()
    assert "qual seu nome" not in low
    assert "com quem eu estou falando" not in low
    assert "com quem eu to falando" not in low


def test_contexto_sem_nome_proibe_pedir_o_nome():
    block = build_context_block(lead_name=None, lead_company=None, now=_now())
    assert "PROIBIDO PEDIR O NOME" in block
    # segue a conversa sem nome e so grava se o lead disser por conta propria
    assert "espontaneamente" in block.lower()
    assert "salvar_nome" in block


def test_contexto_com_nome_mantem_correcao_de_identidade():
    """A correcao de identidade e REATIVA (quem levanta o assunto e o lead) e nao pode
    ser vitima colateral da proibicao de pedir o nome — sem ela a Valeria fica presa a
    um nome errado."""
    block = build_context_block(lead_name="Maria", lead_company=None, now=_now())
    assert "CORRECAO DE IDENTIDADE" in block
    assert "pergunte de forma natural ('pode me dizer seu nome?')" in block
    assert "salvar_nome" in block


def test_regra_25_proibe_pedir_o_nome_em_vez_de_limitar_a_uma_vez():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "PROIBIDO PEDIR O NOME DO LEAD" in prompt
    # a regra antiga tolerava UMA pergunta de nome
    assert "NUNCA PERGUNTE O NOME MAIS DE UMA VEZ" not in prompt


# ── Os prompts de estagio nao podem contradizer a regra 25 ──────────────────
# A secretaria (inbound e outbound) mandava COLETAR o nome numa etapa dedicada —
# instrucao que vinha DEPOIS do base na montagem do prompt e ganhava dele. Sem
# limpar isso, a proibicao do base e letra morta.

def _secretaria(fluxo: str) -> str:
    from app.agent.prompts import get_stage_prompts
    return get_stage_prompts(fluxo)["secretaria"]


def test_secretaria_inbound_nao_manda_coletar_nome():
    low = _secretaria("valeria_inbound").lower()
    assert "coletar o nome" not in low
    assert "coleta de nome" not in low
    assert "solicite o nome" not in low
    assert "com quem eu to falando" not in low
    # o inbound nao tem caminho de negacao de identidade (regra 35 e do outbound, onde o
    # nome vem do cadastro) — entao aqui a pergunta nao tem excecao nenhuma
    assert "com quem voce fala" not in low
    assert "logo apos confirmar o nome" not in low


def test_secretaria_outbound_nao_manda_coletar_nome():
    low = _secretaria("valeria_outbound").lower()
    assert "coletar o nome" not in low
    assert "coleta de nome" not in low
    assert "solicite o nome" not in low
    assert "com quem eu to falando" not in low
    # o "pergunte o nome apenas se nao tiver sido informado" da ETAPA 1 tambem sai
    assert "pergunte o nome" not in low


def test_secretaria_outbound_so_pergunta_quem_fala_na_negacao_de_identidade():
    """A regra 35 MANDA perguntar com quem se fala quando o numero trocou de dono — e
    reativo e sancionado, e vive no bloco de resposta a abertura. Da metade do FUNIL em
    diante essa pergunta e a proibicao da regra 25 com outra roupa: proibida.

    Este recorte existe porque o assert de 'pergunte o nome' nao pega estas duas
    formulacoes ('pergunte com naturalidade com quem voce fala agora' / 'saber com quem
    voce fala') — foi o ponto cego que deixou o conflito passar."""
    prompt = _secretaria("valeria_outbound")
    corte = prompt.index("# FUNIL - SECRETARIA OUTBOUND")
    assert "com quem voce fala" in prompt[:corte].lower(), (
        "o caminho reativo da regra 35 (numero trocou de dono) sumiu"
    )
    assert "com quem voce fala" not in prompt[corte:].lower()


def test_secretaria_inbound_etapa1_nao_e_mais_etapa_de_coleta():
    prompt = _secretaria("valeria_inbound")
    assert "## ETAPA 1: APRESENTACAO\n" in prompt
    assert "PROIBIDO PEDIR O NOME" in prompt


def test_secretaria_inbound_salva_nome_oferecido_espontaneamente():
    """O caminho que SOBREVIVE: o lead se apresenta sozinho e ela grava."""
    prompt = _secretaria("valeria_inbound")
    assert "espontaneamente" in prompt
    assert 'salvar_nome("Ana Lima")' in prompt


def test_secretaria_inbound_regra_c_nao_conta_mais_a_pergunta_de_nome():
    prompt = _secretaria("valeria_inbound")
    assert "Regra C" in prompt
    # a aritmetica antiga somava a pergunta de nome como pergunta 1
    assert "entre a coleta de nome (Etapa 1)" not in prompt
    assert "PRIMEIRA pergunta da conversa" in prompt


def test_secretaria_outbound_mantem_correcao_de_identidade():
    """Reativo (quem levanta o assunto e o lead) — nao pode virar dano colateral."""
    prompt = _secretaria("valeria_outbound")
    assert "CORRECAO DE NOME / IDENTIDADE" in prompt
    assert "Chame salvar_nome com o nome informado IMEDIATAMENTE" in prompt


def test_secretaria_outbound_mantem_few_shots_de_nome_oferecido():
    """Os 2 exemplos em que o LEAD da o nome e ela salva sao o comportamento desejado."""
    prompt = _secretaria("valeria_outbound")
    assert 'salvar_nome("Johny")' in prompt
    assert 'salvar_nome("Luciano")' in prompt


def test_regra_25_abre_excecao_para_negacao_de_identidade():
    """A regra 35 MANDA perguntar com quem se fala quando o numero trocou de dono. Se a
    excecao da regra 25 so citar a regra 20, o base se contradiz — e o prompt de estagio,
    que carrega a mesma ordem e e montado DEPOIS, ganha a disputa."""
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    idx_25 = prompt.index("25. PROIBIDO PEDIR O NOME DO LEAD")
    bloco_25 = prompt[idx_25:prompt.index("26.", idx_25)]
    assert "regras 20 e 35" in bloco_25


def test_checklist_21_preserva_a_pergunta_de_identidade():
    """O checklist e o ultimo portao antes de responder: se o item 21 for incondicional,
    ele apaga a pergunta que as regras 20 e 35 mandam fazer."""
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    # "21." aparece 2x no prompt (regra 21 e item 21 do checklist) — recorte o checklist
    checklist = prompt[prompt.index("CHECKLIST ANTES DE RESPONDER"):]
    item_21 = [l for l in checklist.splitlines() if l.startswith("21. ")][0]
    assert "nunca se pede o nome do lead" in item_21
    assert "regras 20 e 35" in item_21


def test_hooks_de_consumo_escrevem_a_marca_com_maiuscula():
    """Hook de copia literal em minuscula e um contraexemplo da regra dura de nome
    proprio — e few-shot vence regra enunciada."""
    for fluxo in ("valeria_inbound", "valeria_outbound"):
        prompt = _secretaria(fluxo)
        assert "site da cafe canastra" not in prompt, fluxo
        assert "site da Cafe Canastra" in prompt, fluxo


def test_contexto_outbound_1o_turno_so_manda_nomear_quando_ha_nome():
    """A bolha (1) mandava 'abra reconhecendo o lead pelo primeiro nome' mesmo sem nome —
    convite direto a pedir o nome."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
    com_nome = build_outbound_first_turn_context("template x", "Maria")
    sem_nome = build_outbound_first_turn_context("template x", None)
    assert "pelo primeiro nome" in com_nome
    assert "Use o nome UMA vez" in com_nome
    assert "pelo primeiro nome" not in sem_nome
    assert "Use o nome UMA vez" not in sem_nome
    # e o turno sem nome nao pode virar convite a pedir o nome
    assert "PROIBIDO pedir o nome" in sem_nome
    # o resto do arco continua nos dois
    for txt in (com_nome, sem_nome):
        assert "ack de sistema seco" in txt
        assert "PONTE DE CONTEXTO" in txt


# ── ICP: lead de cafe commodity/tradicional nao vira handoff (17/09/2026) ────
# Producao, 90 dias: 116 leads sinalizaram commodity/tradicional e 82 (70,7%) foram
# entregues ao Joao — 14 pontos ACIMA da media geral (56,9%). Nenhum prompt inbound
# tinha regra de ICP; o "objecao de preco -> handoff", o circuit breaker que se declara
# incondicional e o "nao encerre com registrar_sem_interesse_atual" convertiam esse lead
# em "qualificado" por construcao. O motivo do descarte foi conferido contra a guarda 18C
# de tools.py (_ADIAMENTO_MORNO_SIGNALS): nao contem nenhum sinal de adiamento morno.

_MOTIVO_ICP_COMMODITY = (
    'registrar_sem_interesse_atual(motivo="lead busca café commodity/tradicional'
    ' — fora do ICP de café especial")'
)


def _atacado(fluxo: str) -> str:
    from app.agent.prompts import get_stage_prompts
    return get_stage_prompts(fluxo)["atacado"]


def _secao_icp_commodity(fluxo: str) -> str:
    """Recorta a secao de ICP commodity do prompt de atacado montado.

    Ancora no motivo do descarte (unico desta secao — o do auto-produtor termina em
    'fora do ICP de atacado') e sobe ate o titulo da secao."""
    prompt = _atacado(fluxo)
    idx = prompt.find('fora do ICP de café especial")')
    assert idx != -1, f"secao de ICP commodity ausente no atacado {fluxo}"
    inicio = prompt.rfind("\n#", 0, idx)
    fim = prompt.find("\n#", idx)
    return prompt[inicio:fim if fim != -1 else len(prompt)]


def test_atacado_inbound_tem_secao_icp_commodity():
    """O conceito de ICP passa a existir no inbound — antes so existia no outbound."""
    secao = _secao_icp_commodity("valeria_inbound").lower()
    assert "fora do icp" in secao
    assert "o mais barato" in secao, "sinal de commodity ausente"
    assert "supermercado" in secao, "preco de supermercado ausente como sinal"


def test_atacado_inbound_icp_descarta_em_vez_de_encaminhar():
    secao = _secao_icp_commodity("valeria_inbound")
    assert _MOTIVO_ICP_COMMODITY in secao, (
        "motivo do descarte divergiu do texto conferido contra a guarda 18C"
    )
    proibicao = [l for l in secao.splitlines() if "encaminhar_humano" in l and "PROIBIDO" in l]
    assert proibicao, "a secao precisa PROIBIR encaminhar_humano neste caminho"


def test_atacado_inbound_icp_vence_o_circuit_breaker():
    """O circuit breaker se declara 'incondicional e sobrepoe qualquer outra regra de
    fluxo' — sem precedencia explicita ele segue convertendo o lead fora do ICP em handoff."""
    secao = _secao_icp_commodity("valeria_inbound").lower()
    assert "precedencia" in secao or "precedência" in secao
    assert "circuit breaker" in secao
    assert "objecao de preco" in secao, "a regra das 2 tentativas tem que ser nomeada"
    # e o proprio circuit breaker deixa de se declarar incondicional sem ressalva
    prompt = _atacado("valeria_inbound")
    cb = prompt[prompt.index("## Circuit breaker"):]
    cb = cb[:cb.index("\n##", 1)]
    assert "ICP" in cb, "o circuit breaker segue incondicional — precisa citar a excecao de ICP"


def test_atacado_inbound_icp_preserva_os_nao_sinais():
    """Dos 116 leads do coorte, muitos so PERGUNTAVAM a diferenca entre as categorias —
    desqualificar em bloco destruiria lead bom."""
    secao = _secao_icp_commodity("valeria_inbound").lower()
    assert "gourmet" in secao, "a pergunta de categoria precisa constar como NAO-sinal"
    assert "migrar" in secao or "ampliar" in secao, (
        "quem vende tradicional HOJE e quer migrar/ampliar nao e sinal"
    )
    assert "classico" in secao or "clássico" in secao, (
        "o Classico atende quem quer o cafe mais proximo do tradicional"
    )


def test_atacado_outbound_espelha_a_secao_icp():
    secao = _secao_icp_commodity("valeria_outbound")
    assert _MOTIVO_ICP_COMMODITY in secao
    low = secao.lower()
    assert "o mais barato" in low and "supermercado" in low
    assert "gourmet" in low
    assert "classico" in low or "clássico" in low


def _regra_7(prompt: str) -> str:
    bloco = prompt[prompt.index("# REGRAS ABSOLUTAS"):]
    idx = bloco.index("\n7. ")
    return bloco[idx:bloco.index("\n8. ", idx)]


def test_regra_7_nao_e_mais_proibicao_absoluta_de_nomear_a_categoria():
    """Producao: 64 violacoes em 57 leads em 90 dias — inclusive a resposta CERTA
    ("a gente não trabalha com café tradicional, só com café especial"), que a regra
    proibia. Regra inseguivel nao e regra."""
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert 'NUNCA DIZER "CAFE TRADICIONAL"' not in prompt
    regra = _regra_7(prompt).lower()
    assert "tradicional" in regra
    assert "categoria" in regra, "a regra precisa autorizar nomear a categoria do lead"


def test_regra_7_ainda_proibe_chamar_o_nosso_cafe_de_tradicional():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    regra = _regra_7(prompt).lower()
    assert "proibido" in regra or "nunca" in regra
    assert "especia" in regra, "a regra tem que reafirmar que o nosso cafe e especial"


def test_voice_card_espelha_a_regra_7_corrigida():
    from app.agent.prompts.voice_card import VALERIA_VOICE_CARD
    assert 'NUNCA diga "cafe tradicional"' not in VALERIA_VOICE_CARD
    # o cartao quebra linha no meio das frases — normalize antes de procurar
    low = " ".join(VALERIA_VOICE_CARD.lower().split())
    assert "tradicional" in low
    assert "nunca chame o nosso cafe de tradicional" in low
