"""Camada 2 do bot de botões: um texto livre vira UMA das 6 classes de `engine.CLASSES`.

Ela existe porque a máquina de estados sozinha só entende 40% da realidade: no
broadcast mais limpo do histórico (29/07, 494 entregues, 60 respostas) **24 pessoas
clicaram um botão e 36 digitaram texto livre**. Um fluxo puro de botões trava nos 60%
— e, pior, deixa passar o pedido de saída: hoje há **52 leads em produção que
clicaram "Nao tenho interesse" e seguem com `opt_out = false`**, elegíveis à próxima
campanha (risco #1 da spec, LGPD + qualidade do número). A classe SAIR aqui é o que
fecha esse buraco no caminho de texto.

O que este módulo NÃO é: ele não conversa e não escreve uma única palavra para o
cliente. Devolve uma classe; toda mensagem de saída continua declarada em
`app/button_flow/flows.py` e escolhida por `app/button_flow/engine.py:398`
(`_decidir_classe`). Sem persona, sem catálogo, sem histórico longo — o turno modal
da ValerIA custa ~35.565 tokens de input; este custa ~350 (1.284 chars de instrução,
dos quais ~700 são os exemplos verbatim do dossiê, que são o piso).

Decisões de desenho e os incidentes que as impuseram:

  - **`json_mode=True` de verdade.** A fachada OpenAI-shape engolia `response_format`
    em `**_ignored` e queimou 1.366 gerações sem JSON garantido em 08/07 (ver
    `app/agent/gemini_client.py:16-18` e `app/agent/memory_manager.py:196-200`). O
    núcleo nativo manda `response_mime_type="application/json"`; o parse tolerante de
    `_extrair_classe` fica como defesa em profundidade, não como plano A.

  - **Passa pelo `budget_guard`.** O kill-switch diário nasceu desarmado e um runaway
    do `rolling_summary` queimou ~R$149 antes de alguém olhar (FinOps P0, 12/07 —
    `app/agent/budget_guard.py:9-12`). Uma chamada por turno de exceção em 900 leads
    é barata, mas "barata" foi exatamente o adjetivo do runaway. Com o teto estourado
    devolvemos RUIDO, que é o caminho seguro: o motor reoferece os botões e, na
    segunda vez, entrega ao João — o lead nunca fica sem resposta.

  - **Contabiliza em `token_usage`.** O `budget_guard` só enxerga o que está lá: o
    resumo de qualificação rodou off-book por meses e mascarava o gasto real
    (`app/agent/summary.py:178-180`). `call_type='button_flow_classify'` isola esta
    linha na auditoria.

  - **Timeout explícito.** `gemini_client.generate` não tem knob de timeout e o lead
    está esperando dentro da janela de 24h. Preferimos nudgear em 12s a pendurar o
    worker do buffer: o custo de um RUIDO é uma pergunta a mais; o de um turno
    pendurado é a thread inteira.

  - **Env por `os.getenv`, nunca `Settings`.** `app/config.py:65-69` tem
    `extra: "allow"`: a var é aceita no `.env` mas o atributo não é criado, e
    `settings.recuperacao_classifier_model` levantaria AttributeError no primeiro
    turno, depois de o operador jurar que configurou. Molde: `app/bling/config.py:27-43`.
    Prefixo `RECUPERACAO_*`, o mesmo de `app/button_flow/config.py` — as duas funções
    daqui podem migrar para lá sem trocar o nome de nenhuma variável.

NUNCA levanta. Timeout, quota, JSON quebrado, classe inventada — tudo cai em RUIDO,
que é a única saída sem efeito destrutivo: reoferece os botões uma vez e, na segunda,
devolve ao humano.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from app.agent.gemini_client import generate, user_content
from app.button_flow import engine

logger = logging.getLogger(__name__)

# flash-lite é o mais barato da tabela `model_pricing` que serve aqui (US$0,10/M de
# input contra US$0,30 do flash) e é o que o repo já usa nas tarefas mecânicas —
# transcrição, dossiê e resumo de handoff (app/config.py:51-57). A tarefa é uma
# escolha entre 6 rótulos com os exemplos na frente, não redação; e o erro caro
# (rebaixar SAIR indevido) está travado deterministicamente em `_proteger_saida`,
# fora do alcance do modelo.
_MODELO_PADRAO = "gemini-2.5-flash-lite"
_TIMEOUT_PADRAO = 12.0

# {"classe":"PERGUNTA"} cabe folgado. Teto baixo de propósito: com thinking desligado
# não há razão para o modelo escrever mais, e um teto alto só abre espaço para prosa
# que teríamos de jogar fora.
_MAX_OUTPUT_TOKENS = 64

# Tetos de entrada. O pedido colado mais longo do dataset ("Pedido divina terra Plaza
# / CNPJ ... / 10 uni") cabe em 600 chars, e a classe já se decide nas primeiras
# linhas — truncar protege o orçamento de ~300 tokens de quem cola um catálogo.
_MAX_CHARS_TEXTO = 600
_MAX_CHARS_HISTORICO = 300

# Teto do prompt, em chars. Os exemplos verbatim já são ~700 chars: o piso é alto de
# propósito e a folga é curta. Existe como constante para o teste travar — este módulo
# só se paga enquanto for estreito, e a tentação de "só mais um exemplo" é o primeiro
# passo para a terceira persona que a spec §D1 existe para não construir.
MAX_CHARS_INSTRUCAO = 1300

# Os exemplos são VERBATIM do dataset (dossiê §6.5) — não são inventados para o
# prompt. Trocar por paráfrase é perder o registro real do cliente (sem acento, com
# erro de digitação, com CNPJ colado no meio). Sem acento também no resto: o texto
# que chega do WhatsApp raramente tem, e o prompt fica mais barato em tokens.
INSTRUCAO_SISTEMA = """Classifique a resposta do cliente em UMA classe. Devolva so {"classe":"..."}.

SAIR: pede para parar de receber mensagens. "para de me mandar isso", "descadastrar meu numero", "me tira da lista", "nao quero mais receber", "STOP PROMOTIONS"
QUENTE: quer repor, pede tabela/preco ou ja manda pedido. "Quero voltar a parceria", "Me manda a tabela", "quanto ta hoje o classico 2kg?", "Pedido divina terra Plaza / CNPJ 15-737-471-0002-35 / Cafe canastra suave 250gr 10 uni"
ADIAR: tem estoque ou quer falar depois. "por essa semana ainda esta ok o estoque", "acabamos de receber reposicao", "mais pra frente", "vou ver e te falo"
ENGANO: nega o pretexto ou nao e a pessoa. "nao fiz nenhum pedido", "eu nunca comprei esse cafe", "numero errado amigo", "esse celular nao e mais da magda"
PERGUNTA: duvida operacional, sem compra clara. "qual o pedido minimo?", "voces entregam em Alagoas?"
RUIDO: saudacao solta, emoji, audio nao transcrito, midia sem contexto, nada decidivel.

Desempates:
- Duvida entre SAIR e ADIAR: responda ADIAR. Quem so pediu tempo nao e descadastrado.
- Duvida entre QUENTE e PERGUNTA: responda QUENTE.
- "obrigado", "ja compro com o Joao", "acabei de repor" nunca sao SAIR.
- "Nao" sozinho e RUIDO, nunca SAIR: nesta base significa "o nome do cadastro esta errado"."""

# Pontuação que o lead cola no fim de uma resposta de uma palavra.
_PONTUACAO = " \t\n\r.!?,;:…\"'“”‘’()"

# Negativa isolada. Dos ~11 leads que clicaram "Nao" no template outbound, 4 viraram
# lead válido: o "Nao" respondia à pergunta do template ("falo com {{1}}?") e queria
# dizer "o nome no seu cadastro está errado" — a base do Bling importou razão social
# e handles como `leads.name`. Tratar isso como recusa descadastraria justamente quem
# está engajado. RUIDO reoferece os botões, que é a pergunta certa. Resolvido aqui,
# sem gastar token: é a decisão que menos depende de modelo em todo o módulo.
_NEGATIVAS_ISOLADAS = frozenset({"nao", "n", "nn"})

# ── Detector determinístico de pedido de parada ─────────────────────────────
# Opt-out é o único efeito IRREVERSÍVEL do fluxo e é o risco #1 da spec (52 leads em
# produção clicaram "Nao tenho interesse" e seguem com `opt_out = false`). Por isso
# ele é decidido AQUI, por padrão, e em dois pontos:
#
#   1. ANTES da chamada ao LLM (`classificar`), fail-CLOSED. Antes desta correção só
#      existia curto-circuito determinístico CONTRA o opt-out: com o kill-switch
#      diário armado (`app/agent/budget_guard.py:9-12`) ou o provedor fora,
#      `classificar("me tira da lista")` devolvia RUIDO e o lead seguia elegível ao
#      próximo disparo — num dia inteiro de teto estourado isso valeria para 100%
#      dos turnos de texto livre.
#   2. Dentro de `_proteger_saida`, para que a rede de proteção do "obrigado" nunca
#      consiga inverter um pedido explícito.
#
# Casamos por PADRÃO, não por frase verbatim. A lista anterior tinha ~19 substrings
# quase copiadas do dossiê e, combinada com a marca NUNCA-SAIR "obrigad" (que casa em
# QUALQUER posição), rebaixava para ADIAR toda fórmula educada de descadastro fora da
# lista: "Obrigado, mas pode parar de enviar essas mensagens" era respondido com
# "Beleza! Quando faz sentido eu te chamar de novo?" e botões de 30/60/90 dias.
# A gramática do pedido é sempre a mesma — VERBO DE PARADA mirando o ENVIO — e é isso
# que os padrões abaixo codificam.

_NAO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def _alisar(texto: str | None) -> str:
    """Normaliza e troca toda pontuação por UM espaço.

    `engine.normalizar` tira acento e caixa, mas não a vírgula — e os padrões abaixo
    contam palavras entre o verbo e o alvo. Sem alisar, "Favor cancelar, meu
    cadastro" escaparia por causa de uma vírgula, que é exatamente o tipo de detalhe
    que fez a lista verbatim anterior falhar.
    """
    return _NAO_ALFANUMERICO.sub(" ", engine.normalizar(texto)).strip()


# O ALVO do verbo: aquilo que a frase precisa estar mirando para ser descadastro, e
# não um "cancela esse pedido" comercial. `pedido`, `mercadoria` e afins estão FORA
# de propósito — "cancelar meu pedido" não é opt-out.
_ALVO = (
    r"(?:mensage\w*|msg\w*|envio\w*|lista|cadastr\w*|contat\w*|numero\w*|nome\w*|"
    r"promo\w*|publicid\w*|publicit\w*|propaganda\w*|divulga\w*|spam|disparo\w*|"
    r"notifica\w*|comunicad\w*|mand\w*|envi\w*)"
)

# Verbos de parada. "para" sozinho é a preposição mais comum do português ("me manda
# para o meu whatsapp a lista de precos") — só vale como verbo colado a "de"/"com".
# "sair" ficou de fora pelo mesmo motivo ("vou sair agora, me manda a lista depois"):
# entra pelas âncoras verbatim, onde só casa em "sair da lista".
_VERBO_PARADA = (
    r"(?:parar|pare|parem|para\s+(?:de|com)|cancel\w+|remov\w+|remova|retir\w+|"
    r"tir(?:a|ar|e|em)|exclu(?:a|ir|am|i|o)|suspend\w+|desativ\w+|interromp\w+|"
    r"cess(?:ar|e|em)|bloque\w+|encerr\w+)"
)

# Palavras de enchimento aceitas ENTRE a negação e o verbo. Vocabulário fechado de
# propósito: com um `\w+` genérico, "nao sei se vou conseguir receber" viraria opt-out.
_ENCHIMENTO = (
    r"(?:me|nos|lhe|mais|nunca|quero|queria|desejo|deseja|pretendo|preciso|precisa|"
    r"tenho|temos|gostaria|interesse|aceito|autorizo|favor|por|prefiro|nada|vou|"
    r"vamos|e|em|de|do|da|a|o|que|nem|com)"
)

# Objeto COMERCIAL logo depois de "receber": "nao vou receber o pedido essa semana"
# é reclamação de entrega, não descadastro.
_OBJETO_COMERCIAL = r"(?:pedido|mercadoria|produto|entrega|carga|nota|boleto|amostra)"

# 1) Marcas que JÁ SÃO o pedido de saída, sem precisar de complemento.
_RE_OPTOUT_DIRETO = re.compile(
    r"\b(?:descadastr\w*|desinscre\w*|desinscri\w*|unsubscribe|opt\s?out|stop)\b"
)

# 2) Verbo de parada mirando o envio, com até 2 palavras no meio ("cancelar meu
#    cadastro", "parar com essas mensagens", "me tira da lista", "para de me mandar").
#    Duas e não três: com três, "me tira uma duvida do envio" viraria opt-out.
_RE_PARADA_DIRIGIDA = re.compile(
    rf"\b{_VERBO_PARADA}\b(?:\s+\w+){{0,2}}\s+{_ALVO}\b"
)

# 3) Recusa de RECEBER. Só o infinitivo: "nao recebi o pedido" é reclamação.
_RE_RECUSA_RECEBER = re.compile(
    rf"\b(?:nao|nunca)\b(?:\s+{_ENCHIMENTO}\b){{0,4}}\s+receber\b"
    rf"(?!\s+(?:o|a|os|as|meu|minha|esse|essa|este|esta)?\s*{_OBJETO_COMERCIAL})"
)

# 4) "nao autorizo mais o envio", "nunca autorizei esse tipo de mensagem".
_RE_NAO_AUTORIZO = re.compile(
    rf"\b(?:nao|nunca)\b(?:\s+{_ENCHIMENTO}\b){{0,2}}\s+autoriz\w+"
)

# 5) Recusa de ENVIO com qualificador de definitividade DEPOIS do verbo
#    ("nao me mande mais mensagens"). O qualificador é obrigatório: sem ele,
#    "nao me manda o pedido ainda" — que é ADIAR — viraria opt-out irreversível.
_RE_RECUSA_ENVIO = re.compile(
    rf"\b(?:nao|nunca)\b(?:\s+{_ENCHIMENTO}\b){{0,4}}\s+(?:mand\w+|envi\w+)\b"
    rf"(?:\s+\w+){{0,2}}\s+(?:mais|nada|nenhum\w*|isso|essas?|esses?|{_ALVO})\b"
)

# 5b) O mesmo pedido com o qualificador ANTES do verbo ("nao precisa mais mandar").
_RE_RECUSA_ENVIO_INVERTIDA = re.compile(
    rf"\b(?:nao|nunca)\b(?:\s+{_ENCHIMENTO}\b){{0,3}}\s+(?:mais|nunca)\b"
    rf"(?:\s+{_ENCHIMENTO}\b){{0,2}}\s+(?:mand\w+|envi\w+)\b"
)

_PADROES_DE_PARADA = (
    _RE_OPTOUT_DIRETO, _RE_PARADA_DIRIGIDA, _RE_RECUSA_RECEBER,
    _RE_NAO_AUTORIZO, _RE_RECUSA_ENVIO, _RE_RECUSA_ENVIO_INVERTIDA,
)

# Âncoras que a gramática acima não expressa sem abrir brecha (ver os comentários de
# `_VERBO_PARADA` sobre "sair" e a ausência de alvo em "me bloqueia").
_ANCORAS_VERBATIM = (
    "sair da lista", "sair dessa lista", "sair desta lista",
    "me bloqueia", "me bloquear", "vou bloquear", "vou te bloquear",
    "chega de mensagem", "sem mais mensagem",
)


def pediu_para_parar(texto: str | None) -> bool:
    """True quando o texto contém um pedido EXPLÍCITO de parar o envio.

    Determinístico e sem LLM: é a única prova que autoriza SAIR sozinha e a única
    que `_proteger_saida` não pode contrariar.
    """
    alisado = _alisar(texto)
    if not alisado:
        return False
    if any(ancora in alisado for ancora in _ANCORAS_VERBATIM):
        return True
    return any(padrao.search(alisado) for padrao in _PADROES_DE_PARADA)


# Frases que o dossiê marca como NUNCA-SAIR, com o prejuízo já contabilizado:
# Rafael Monteiro escreveu "Eu ja sou cliente de voces. Faco meus pedidos com o Joao",
# recebeu opt-out e comprou R$ 2.490 dez dias depois; a Verde Vale disse "acabamos de
# receber reposicao", recebeu opt-out e comprou R$ 1.178,90. As duas são ADIAR — o
# desempate "na dúvida, ADIAR" está no prompt, mas opt-out é o único efeito
# IRREVERSÍVEL do fluxo e não pode depender só de o modelo ter lido a regra.
# Rebaixar não fecha porta nenhuma: o nó de prazo continua oferecendo o botão
# "Parar mensagens" a um toque.
_NUNCA_E_SAIR = (
    "obrigad", "ja sou cliente", "sou cliente de voces", "compro com o joao",
    "pedidos com o joao", "acabei de repor", "acabamos de repor",
    "acabamos de receber", "acabei de receber", "ja comprei", "ja compro",
)


def modelo() -> str:
    """Modelo do classificador. Env RECUPERACAO_CLASSIFIER_MODEL."""
    return (os.getenv("RECUPERACAO_CLASSIFIER_MODEL") or "").strip() or _MODELO_PADRAO


def timeout_segundos() -> float:
    """Teto de espera pela classificação. Env RECUPERACAO_CLASSIFIER_TIMEOUT_S."""
    bruto = (os.getenv("RECUPERACAO_CLASSIFIER_TIMEOUT_S") or "").strip()
    if not bruto:
        return _TIMEOUT_PADRAO
    try:
        valor = float(bruto)
    except ValueError:
        logger.warning(
            "[BUTTON FLOW] RECUPERACAO_CLASSIFIER_TIMEOUT_S invalido (%r) — usando %.1fs",
            bruto, _TIMEOUT_PADRAO,
        )
        return _TIMEOUT_PADRAO
    return valor if valor > 0 else _TIMEOUT_PADRAO


def _sem_pontuacao(texto: str) -> str:
    return texto.strip(_PONTUACAO)


def _montar_entrada(texto: str, historico_curto: str) -> str:
    partes = []
    historico = (historico_curto or "").strip()
    if historico:
        partes.append(f"Contexto: {historico[:_MAX_CHARS_HISTORICO]}")
    partes.append(f"Resposta do cliente: {texto[:_MAX_CHARS_TEXTO]}")
    return "\n".join(partes)


def _extrair_classe(bruto: str | None) -> str | None:
    """Saída do modelo -> classe válida, ou None se não der para aproveitar nada.

    Tolerante de propósito (mesma lição de memory_manager._extract_json_object): o
    JSON pode vir com cerca de markdown ou prosa em volta. Se nem isso, aceita a
    palavra solta — mas só quando UMA classe aparece no texto; duas seriam um modelo
    hesitando em voz alta, e adivinhar qual dele vale é pior que devolver RUIDO.

    O varrimento por substring é o ÚLTIMO recurso e só vale quando o JSON nem
    parseou. Se parseou como objeto, o campo `classe` é a resposta do modelo e é a
    palavra final: antes, `{"classe":"TALVEZ","justificativa":"o cliente pediu para
    SAIR mais tarde"}` caía no fallback e o "SAIR" da JUSTIFICATIVA decidia a classe
    — uma palavra em prosa descadastrando um lead.
    """
    texto = (bruto or "").strip()
    if not texto:
        return None
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio != -1 and fim > inicio:
        try:
            objeto = json.loads(texto[inicio:fim + 1])
        except (json.JSONDecodeError, ValueError):
            objeto = None
        if isinstance(objeto, dict):
            valor = objeto.get("classe") or objeto.get("class")
            if isinstance(valor, str) and valor.strip().upper() in engine.CLASSES:
                return valor.strip().upper()
            return None
    achadas = [c for c in engine.CLASSES if c in texto.upper()]
    return achadas[0] if len(achadas) == 1 else None


def _proteger_saida(classe: str, texto: str) -> str:
    """Rede determinística sobre a única classe irreversível. Ver `_NUNCA_E_SAIR`.

    A cortesia MODULA o julgamento; ela nunca o inverte. Havendo pedido explícito de
    parada, `pediu_para_parar` vence e a rede nem chega a rodar — em `classificar` o
    texto já teria saído como SAIR antes do LLM. A checagem continua aqui porque esta
    função é a guarda da classe irreversível e precisa valer sozinha, para quem a
    chamar de fora do caminho feliz.
    """
    if classe != engine.CLASSE_SAIR:
        return classe
    if pediu_para_parar(texto):
        return classe
    normalizado = _alisar(texto)
    if any(marca in normalizado for marca in _NUNCA_E_SAIR):
        logger.warning(
            "[BUTTON FLOW] classificador disse SAIR sem pedido de parada em %r — "
            "rebaixando para ADIAR (casos Rafael Monteiro e Verde Vale)", texto[:120],
        )
        return engine.CLASSE_ADIAR
    return classe


def _budget_estourado() -> bool:
    """True se o kill-switch diário está ativo. Fail-open: erro aqui não bloqueia.

    Import tardio pelo mesmo motivo de app/buffer/parking.py:438 — budget_guard puxa
    o cliente Supabase e não deve carregar no import deste módulo.
    """
    try:
        from app.agent import budget_guard
        return budget_guard.is_exceeded()
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao ler o budget guard (seguindo): %s", exc)
        return False


def _contabilizar(resultado, modelo_usado: str, lead_id: str | None) -> None:
    """Grava a linha em token_usage. Fail-soft: contabilidade nunca derruba o turno."""
    try:
        uso = getattr(resultado, "usage_metadata", None)
        if not uso:
            return
        from app.agent import token_tracker
        token_tracker.track_token_usage(
            lead_id=lead_id,
            stage="",
            model=modelo_usado,
            call_type="button_flow_classify",
            prompt_tokens=uso.prompt_token_count or 0,
            completion_tokens=uso.billed_output_tokens or 0,
            cached_tokens=uso.cached_content_token_count or 0,
            reasoning_tokens=uso.thoughts_token_count or 0,
        )
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao contabilizar token_usage (ignorado): %s", exc)


async def classificar(
    texto: str, *, historico_curto: str = "", lead_id: str | None = None,
) -> str:
    """Classifica UM texto livre em uma de `engine.CLASSES`. Nunca levanta.

    `historico_curto` é opcional e entra truncado: serve para desambiguar um "sim"
    ou um "pode ser" que só faz sentido colado à pergunta anterior. NÃO é o histórico
    do lead — mandar conversa inteira aqui transformaria o classificador na persona
    que a spec §4 existe para não construir.

    `lead_id` é opcional e só serve para a linha de `token_usage` sair atribuída; a
    classificação é idêntica com ou sem ele.

    Qualquer falha devolve RUIDO. Não é um default preguiçoso: RUIDO é a única classe
    sem efeito destrutivo — o motor reoferece os botões uma vez e, na segunda, silencia
    e entrega ao João (`engine.decidir`, regra de nudge). Devolver PERGUNTA custaria um
    handoff indevido; devolver SAIR descadastraria alguém por causa de um timeout.
    """
    limpo = (texto or "").strip()
    if not limpo or not any(c.isalnum() for c in limpo):
        # Áudio não transcrito, figurinha, emoji solto, mídia sem legenda: é RUIDO por
        # definição (dossiê §6.5) e não vale uma chamada.
        return engine.CLASSE_RUIDO

    if engine.normalizar(_sem_pontuacao(limpo)) in _NEGATIVAS_ISOLADAS:
        logger.info("[BUTTON FLOW] negativa isolada %r -> RUIDO (sem LLM)", limpo[:40])
        return engine.CLASSE_RUIDO

    # O risco #1 da spec pede literalmente "short-circuit determinístico fail-CLOSED"
    # (2026-09-09-valeria-recuperacao-botoes-design.md:420), e até aqui só havia
    # curto-circuito determinístico CONTRA o opt-out: com o teto diário estourado
    # ou o Gemini fora, "me tira da lista" caía no RUIDO logo abaixo e o lead seguia
    # elegível ao próximo disparo. Reconhecer o pedido antes da chamada custa zero
    # token e não depende de infraestrutura nenhuma.
    if pediu_para_parar(limpo):
        logger.info(
            "[BUTTON FLOW] pedido explicito de parada %r -> SAIR (sem LLM)", limpo[:80]
        )
        return engine.CLASSE_SAIR

    if _budget_estourado():
        logger.warning(
            "[BUTTON FLOW] teto diario de LLM estourado — classificador devolvendo RUIDO"
        )
        return engine.CLASSE_RUIDO

    modelo_usado = modelo()
    try:
        resultado = await asyncio.wait_for(
            generate(
                modelo_usado,
                contents=[user_content(_montar_entrada(limpo, historico_curto))],
                system_instruction=INSTRUCAO_SISTEMA,
                json_mode=True,
                thinking_off=True,
                temperature=0.0,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            ),
            timeout=timeout_segundos(),
        )
    except Exception as exc:
        logger.warning(
            "[BUTTON FLOW] classificador falhou (%s: %s) — devolvendo RUIDO",
            type(exc).__name__, exc,
        )
        return engine.CLASSE_RUIDO

    _contabilizar(resultado, modelo_usado, lead_id)

    classe = _extrair_classe(getattr(resultado, "text", None))
    if classe is None:
        logger.warning(
            "[BUTTON FLOW] saida inutilizavel do classificador (%.120s) — devolvendo RUIDO",
            getattr(resultado, "text", None) or "",
        )
        return engine.CLASSE_RUIDO

    protegida = _proteger_saida(classe, limpo)
    logger.info("[BUTTON FLOW] classe=%s texto=%.80s", protegida, limpo)
    return protegida
