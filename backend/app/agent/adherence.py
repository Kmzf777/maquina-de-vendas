"""Guardas determinísticas de aderência do agente (2026-07-04).

Funções PURAS (sem I/O, sem efeitos colaterais) usadas para:

1. `strip_prohibited_phrases` — limpar, do texto final do assistente, frases que a
   Valéria não deve emitir (ex.: "pra te direcionar da melhor forma" — jargão de
   call-center que não combina com a persona).
2. `detect_auto_producer` — detectar, na mensagem do LEAD, sinais explícitos de que
   ele mesmo PRODUZ café (torrefador/produtor/marca própria) — fora do ICP de compra.

Ambas seguem o mesmo padrão de normalização (NFD + lower, removendo diacríticos) já
usado em `app.agent.tools._normalize_text` e `app.agent.orchestrator._strip_diacritics`,
replicado aqui localmente para não criar acoplamento entre módulos.
"""

from __future__ import annotations

import re
import unicodedata


def _normalize(text: str | None) -> str:
    """Lowercase + remoção de diacríticos (NFD, filtra combining marks Mn).

    Espelha `_normalize_text` de tools.py — mesma técnica, sem importar de lá para
    manter este módulo independente (guarda de aderência é sua própria unidade).
    """
    nfd = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# 1. strip_prohibited_phrases
# ---------------------------------------------------------------------------
# Frases-alvo (e variações próximas) que a IA às vezes emite e que soam como
# jargão de call-center — não combinam com a voz da Valéria. Operamos sobre o
# texto NORMALIZADO para casar, mas removemos do texto ORIGINAL usando os spans
# encontrados na versão normalizada (normalização preserva o comprimento — NFD +
# filtro de Mn nunca muda o índice de um caractere não-combinante), então os
# offsets batem 1:1 entre normalizado e original.
#
# O regex cobre o núcleo comum "pra/para (eu) te direcionar" com um sufixo
# opcional "da melhor forma", incluindo possíveis variações de espaçamento.
_PROHIBITED_PHRASE_RE = re.compile(
    r"\b(?:pra|para)\s+(?:eu\s+)?te\s+direcionar(?:\s+da\s+melhor\s+forma)?\b"
)


def _collapse_whitespace_and_punctuation(text: str) -> str:
    """Normaliza espaços/pontuação duplicada deixados pela remoção de uma frase.

    - Colapsa espaços múltiplos em um único espaço.
    - Remove espaço antes de pontuação (", ", "  ,").
    - Colapsa pontuação duplicada resultante (",," "..", "  ").
    - Apara espaços nas bordas de cada linha e do texto todo.
    """
    # Colapsa espaços/tabs (não mexe em quebras de linha propositais)
    collapsed = re.sub(r"[ \t]{2,}", " ", text)
    # Remove espaço sobrando antes de vírgula/ponto/exclamação/interrogação
    collapsed = re.sub(r"[ \t]+([,.!?])", r"\1", collapsed)
    # Colapsa pontuação duplicada (",," "..." sobrando de junções, mas preserva "...")
    collapsed = re.sub(r",{2,}", ",", collapsed)
    collapsed = re.sub(r"([,.!?]) ,", r"\1", collapsed)
    # Remove vírgula/ponto isolado sobrando logo após outra pontuação
    collapsed = re.sub(r"([,.!?])\s*\1+", r"\1", collapsed)
    # Apara espaços em cada linha e remove linhas que ficaram vazias entre textos
    lines = [ln.strip() for ln in collapsed.split("\n")]
    collapsed = "\n".join(lines)
    # Colapsa 3+ quebras de linha resultantes em no máximo 2 (parágrafo)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def strip_prohibited_phrases(text: str) -> str:
    """Remove frases proibidas do texto final do assistente, preservando o resto.

    Robusto a acentos e caixa (casa sobre uma versão normalizada do texto, mas
    remove os trechos correspondentes do texto ORIGINAL — preservando acentos e
    maiúsculas do restante da mensagem). Limpa espaços/pontuação duplicada
    deixados pela remoção. Se nada casar, retorna o texto inalterado (idêntico,
    sem sequer passar pelo collapse).

    Função pura — sem I/O, sem logging, testável isoladamente.
    """
    if not text:
        return text

    normalized = _normalize(text)
    matches = list(_PROHIBITED_PHRASE_RE.finditer(normalized))
    if not matches:
        return text

    # Remove os spans casados (na ordem inversa, para não invalidar os índices
    # dos spans anteriores) diretamente do texto ORIGINAL — normalização NFD +
    # filtro de Mn nunca insere/remove caracteres não-combinantes, então os
    # índices batem entre `normalized` e `text`.
    result = text
    for m in reversed(matches):
        result = result[: m.start()] + result[m.end() :]

    return _collapse_whitespace_and_punctuation(result)


# ---------------------------------------------------------------------------
# 2. detect_auto_producer
# ---------------------------------------------------------------------------
# Sinais explícitos (e só explícitos) de que o LEAD é ele mesmo produtor/torrefador
# de café — fora do ICP de compra da Café Canastra. CONSERVADOR de propósito:
# frases elípticas/ambíguas ("sou eu mesma") NÃO devem casar — só entram sinais
# que mencionam produção/torra/marca/fazenda de café de forma inequívoca.
_AUTO_PRODUCER_SIGNALS = (
    "eu que produzo",
    "eu mesmo torro",
    "eu mesma torro",
    "sou produtor",
    "sou produtora",
    "produzo meu cafe",
    "produzo meu proprio cafe",
    "meu proprio cafe",
    "tenho minha marca de cafe",
    "tenho minha fazenda de cafe",
    "tenho minha propria marca de cafe",
)


def detect_auto_producer(text: str) -> bool:
    """True quando a mensagem do LEAD indica que ele mesmo PRODUZ café.

    Casa apenas sinais explícitos de produção/torra/marca/fazenda de café
    (lista `_AUTO_PRODUCER_SIGNALS`). Robusto a acentos e caixa via `_normalize`.
    Deliberadamente CONSERVADOR: NÃO casa com elípticas ambíguas como
    "sou eu mesma" isoladas, nem com menções neutras de consumo
    ("tomo café todo dia", "quero comprar café").

    Função pura — sem I/O, testável isoladamente.
    """
    if not text:
        return False
    normalized = _normalize(text)
    return any(signal in normalized for signal in _AUTO_PRODUCER_SIGNALS)


# ---------------------------------------------------------------------------
# 3. detect_autoresponder (auditoria 2026-07-08 — caso Letícia/Duo Gelatto)
# ---------------------------------------------------------------------------
# Resposta automática de empresa não é engajamento humano. Em 08/07 o auto-reply
# de uma gelateria (marcador U+200E + links de iFood + "agradece seu contato")
# passou como fala de pessoa, caiu no fallback de LLM-down e virou handoff pro
# João. Heurística por PONTUAÇÃO de sinais independentes (>= 2 pontos):
#   - caractere invisível LRM/RLM na abertura (marca de mensagem automática): 2 pts
#   - 2+ URLs: 1 pt
#   - frases típicas de bot comercial: 1 pt cada (teto 2)
#   - menu numerado (2+ linhas "1 -", "2 -"): 1 pt
# Conservador de propósito: um lead humano com UM link ou UMA frase não pontua 2.

_AUTORESPONDER_PHRASES = (
    re.compile(r"agradece\w*\s+(?:o\s+)?seu\s+contato"),
    re.compile(r"\bretornaremos\b"),
    re.compile(r"horario de funcionamento"),
    re.compile(r"mensagem automatica"),
    re.compile(r"atendimento automatico"),
    re.compile(r"escolha uma(?: das)? opc"),
    re.compile(r"digite o numero"),
    re.compile(r"nao e monitorad"),
    re.compile(r"para entrega acesse"),
    re.compile(r"para outros assuntos"),
    re.compile(r"bem[- ]vindo\w* ao atendimento"),
    re.compile(r"retornamos o mais breve"),
)
_URL_COUNT_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_MENU_LINE_RE = re.compile(r"^\s*\d+\s*[-–—.)]", re.MULTILINE)


def detect_autoresponder(text: str) -> bool:
    """True quando a mensagem tem cara de resposta automática de empresa.

    Função pura — sem I/O. Ver tabela de sinais no comentário acima.
    """
    if not text:
        return False
    score = 0
    if text[0] in ("‎", "‏"):
        score += 2
    if len(_URL_COUNT_RE.findall(text)) >= 2:
        score += 1
    normalized = _normalize(text)
    phrase_hits = sum(1 for pat in _AUTORESPONDER_PHRASES if pat.search(normalized))
    score += min(phrase_hits, 2)
    if len(_MENU_LINE_RE.findall(text)) >= 2:
        score += 1
    return score >= 2


# ---------------------------------------------------------------------------
# 4. normalize_orthography (auditoria 2026-07-08 — ortografia oscilante)
# ---------------------------------------------------------------------------
# A mesma bolha saiu com "é" acentuado e "torrefacao"/"xicara" crus — humano tem
# UMA digitação. O prompt já EXIGE acentos (base.py, MODELO DE ESCRITA); este
# normalizador transforma a exigência em garantia, num mapa de substituições
# INEQUÍVOCAS por fronteira de palavra. Ambíguas ficam de fora de propósito:
# "e"/"é" (conjunção × verbo), "esta"/"está", "ai"/"aí", "pais"/"país", "as"/"às".
# Tokens de URL nunca são tocados (cafecanastra.com/cafe fica intacto).
# `_URL_SPAN_RE` também reconhece e-mail completo (não só o domínio) — a
# seção 13 (normalize_proper_nouns) reaproveita este mesmo split para não
# maiusculizar "valeria" dentro de "valeria@cafecanastra.com".

_ORTHO_MAP = {
    "nao": "não", "voce": "você", "voces": "vocês", "cafe": "café", "cafes": "cafés",
    "ja": "já", "entao": "então", "tambem": "também", "xicara": "xícara",
    "xicaras": "xícaras", "torrefacao": "torrefação", "so": "só", "ta": "tá",
    "ne": "né", "propria": "própria", "proprio": "próprio", "minimo": "mínimo",
    "minima": "mínima", "preco": "preço", "precos": "preços", "numero": "número",
    "numeros": "números", "grao": "grão", "graos": "grãos", "sao": "são",
    "ate": "até", "atencao": "atenção", "opcao": "opção", "opcoes": "opções",
    "tres": "três", "apos": "após", "porem": "porém", "otimo": "ótimo",
    "otima": "ótima", "duvida": "dúvida", "duvidas": "dúvidas",
    "horario": "horário", "horarios": "horários", "disponivel": "disponível",
    "possivel": "possível", "rapido": "rápido", "rapida": "rápida", "alem": "além",
    "proximo": "próximo", "proxima": "próxima",
}
_URL_SPAN_RE = re.compile(
    r"(https?://\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|\b[\w.-]+\.(?:com|net|org|br)(?:/\S*)?)",
    re.IGNORECASE,
)
_ORTHO_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(_ORTHO_MAP, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _ortho_replace(match: "re.Match[str]") -> str:
    word = match.group(0)
    base = _ORTHO_MAP[word.lower()]
    if word.isupper() and len(word) > 1:
        return base.upper()
    if word[0].isupper():
        return base[0].upper() + base[1:]
    return base


def normalize_orthography(text: str) -> str:
    """Fixa a acentuação das palavras inequívocas do vocabulário da persona.

    Preserva URLs, caixa inicial e todo o resto do texto. Função pura.
    """
    if not text:
        return text
    parts = _URL_SPAN_RE.split(text)
    for i in range(0, len(parts), 2):  # índices pares = fora de URL
        parts[i] = _ORTHO_WORD_RE.sub(_ortho_replace, parts[i])
    return "".join(parts)


# ---------------------------------------------------------------------------
# 5. is_repeated_question (auditoria 2026-07-08 — caso Luciano)
# ---------------------------------------------------------------------------
# O lead recebeu a MESMA pergunta de qualificação 3x depois de já tê-la
# respondido. Detecta, no texto candidato, uma pergunta substancial (>= 6
# tokens) que já apareceu numa fala anterior do assistente — por igualdade
# normalizada ou por containment de tokens (>= 80% dos tokens do candidato
# presentes na pergunta anterior).

_QUESTION_MIN_TOKENS = 6
_QUESTION_OVERLAP_THRESHOLD = 0.8
_QUESTION_CHUNK_RE = re.compile(r"[^?!.\n]+\?")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _extract_questions(text: str) -> list[tuple[str, frozenset]]:
    normalized = _normalize(text or "")
    out: list[tuple[str, frozenset]] = []
    for chunk in _QUESTION_CHUNK_RE.findall(normalized):
        q = chunk.strip()
        tokens = frozenset(_TOKEN_RE.findall(q))
        if len(tokens) >= _QUESTION_MIN_TOKENS:
            out.append((q, tokens))
    return out


def is_repeated_question(text: str, prior_assistant_texts: list[str] | None) -> str | None:
    """Devolve a pergunta repetida (normalizada) ou None.

    Compara as perguntas do texto candidato com as das últimas falas do
    assistente. Perguntas curtas de cortesia ("tudo bem?") ficam abaixo do
    mínimo de tokens e nunca flagram. Função pura.
    """
    candidates = _extract_questions(text or "")
    if not candidates:
        return None
    prior: list[tuple[str, frozenset]] = []
    for prior_text in (prior_assistant_texts or [])[-10:]:
        prior.extend(_extract_questions(prior_text or ""))
    if not prior:
        return None
    for q, tokens in candidates:
        for prior_q, prior_tokens in prior:
            if q == prior_q:
                return q
            if len(tokens & prior_tokens) / len(tokens) >= _QUESTION_OVERLAP_THRESHOLD:
                return q
    return None


# ---------------------------------------------------------------------------
# 5b. strip_consecutive_vocative_name (auditoria 2026-07-10 — caso Marisete)
# ---------------------------------------------------------------------------
# A Valéria abriu 3 turnos consecutivos com o vocativo do lead ("boa, Marisete" →
# "que legal, Marisete" → "vale a pena conhecer, Marisete, ...") apesar da regra
# explícita do prompt ("nunca repita o nome em mensagens consecutivas — padrão de
# telemarketing") e do item 13 do checklist. Guarda determinística: se o nome já
# apareceu nas últimas falas do assistente, remove APENAS as ocorrências vocativas
# (", Nome" delimitado por pontuação/fim, ou "Nome, " abrindo linha) do texto novo.
# Usos semânticos ("o pedido da Marisete") não casam com os padrões e ficam intactos.

_VOCATIVE_PRIOR_WINDOW = 3  # bolhas anteriores do assistente que contam como "turno anterior"
_VOCATIVE_MIN_NAME_LEN = 3  # nomes de 1-2 letras colidem com palavras comuns


def strip_consecutive_vocative_name(
    text: str, lead_name: str | None, prior_assistant_texts: list[str] | None,
) -> str:
    """Remove o vocativo do nome quando o turno anterior do assistente já o usou.

    Mesma técnica de spans de strip_prohibited_phrases: casa na versão normalizada
    (minúsculas, sem diacríticos) e remove do texto ORIGINAL. Conservador: só padrões
    inequivocamente vocativos; se o resultado esvaziar, devolve o original (fail-open).
    Função pura — sem I/O, testável isoladamente.
    """
    if not text or not lead_name:
        return text
    parts = lead_name.strip().split()
    if not parts:
        return text
    first = parts[0]
    if len(first) < _VOCATIVE_MIN_NAME_LEN:
        return text

    name_norm = re.escape(_normalize(first))
    name_word_re = re.compile(r"\b" + name_norm + r"\b")
    recent = [t for t in (prior_assistant_texts or []) if t][-_VOCATIVE_PRIOR_WINDOW:]
    if not any(name_word_re.search(_normalize(t)) for t in recent):
        return text

    vocative_patterns = (
        # ", nome" seguido de pontuação, quebra de linha ou fim do texto
        re.compile(r",\s*" + name_norm + r"\b(?=\s*(?:[,.!?\n]|$))"),
        # "nome, " abrindo o texto ou uma linha/bolha
        re.compile(r"^" + name_norm + r"\b,\s*", re.MULTILINE),
    )
    result = text
    for pattern in vocative_patterns:
        for m in reversed(list(pattern.finditer(_normalize(result)))):
            result = result[: m.start()] + result[m.end():]
    result = _collapse_whitespace_and_punctuation(result)
    return result if result else text


# ---------------------------------------------------------------------------
# 6. find_verbatim_prompt_echo (auditoria 2026-07-08 — carimbo do exemplo)
# ---------------------------------------------------------------------------
# O "exemplo vencedor" do prompt foi copiado byte a byte para 5 leads no mesmo
# disparo. Detecta eco literal (janela normalizada >= min_len) de qualquer
# semente/exemplo registrado. Uso: telemetria de aderência (log), não bloqueio.

def find_verbatim_prompt_echo(
    text: str, snippets: tuple[str, ...] | list[str], min_len: int = 25,
) -> str | None:
    """Devolve a semente ecoada literalmente no texto, ou None. Função pura."""
    if not text or not snippets:
        return None
    text_norm = re.sub(r"\s+", " ", _normalize(text)).strip()
    for snippet in snippets:
        snippet_norm = re.sub(r"\s+", " ", _normalize(snippet or "")).strip()
        if len(snippet_norm) >= min_len and snippet_norm in text_norm:
            return snippet
    return None


# ---------------------------------------------------------------------------
# 7. price_without_cta (auditoria 2026-07-11 — Cat. 3, caso Sandro)
# ---------------------------------------------------------------------------
# O turno entregou preço (R$26,70/100un) e terminou SEM pergunta de fechamento —
# o lead ficou no vácuo. Detecta, no TEXTO COMPLETO do turno, presença de preço
# ("R$" + dígito) com a última bolha não terminando em "?". Multi-bolha com o
# preço numa bolha inicial e a pergunta na última NÃO dispara (o check é sobre o
# turno inteiro terminar em "?"). Separador de milhar (R$1.000) não confunde: a
# detecção é só "há preço?", e o veredito é sobre a última linha. Telemetria
# log-only — NUNCA muta a resposta.
_PRICE_RE = re.compile(r"R\$\s?\d")


def price_without_cta(text: str) -> bool:
    """True quando o texto entrega preço mas não termina com pergunta de fechamento.

    Preço = 'R$' (com espaço opcional) seguido de dígito. A "última bolha" é a
    última linha não-vazia do turno; se ela terminar com '?', há CTA. Função pura.
    """
    if not text or not _PRICE_RE.search(text):
        return False
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    return not lines[-1].endswith("?")


# ---------------------------------------------------------------------------
# 8. handoff_without_answer (auditoria 2026-07-11 — Cat. 2)
# ---------------------------------------------------------------------------
# O lead fez a pergunta mais quente da conversa (preço/lote mínimo/prazo) e
# recebeu o cartão do João no lugar da resposta. Heurística DELIBERADAMENTE simples
# e fail-open (sinal p/ QA, não métrica exata): a última msg do lead contém "?" E a
# mensagem_despedida não traz número nem "R$". Falso-negativo aceitável (pergunta
# não-numérica respondida em texto); falso-positivo aceitável (resposta sem número).
# Telemetria log-only — NUNCA bloqueia o handoff.
_DIGIT_RE = re.compile(r"\d")


def handoff_without_answer(last_lead_text: str | None, farewell_text: str | None) -> bool:
    """True quando o lead terminou com pergunta e a despedida não traz número/R$.

    Função pura — sem I/O. Ver heurística no comentário acima.
    """
    if not last_lead_text or "?" not in last_lead_text:
        return False
    farewell = farewell_text or ""
    if "R$" in farewell or _DIGIT_RE.search(farewell):
        return False
    return True


# ---------------------------------------------------------------------------
# 9. strip_kitchen_leak (auditoria 2026-07-14 — caso Thiago Romanini)
# ---------------------------------------------------------------------------
# A Valéria repassou LITERALMENTE, 2×, a saída interna de calcular_orcamento:
# "opa, o sistema não encontrou o 'Café Canastra 250g…' no catálogo de atacado…".
# O prompt de atacado (valeria_inbound/atacado.py) proíbe: "o cliente NUNCA vê a
# cozinha". Backstop determinístico: remove o TRECHO-vazamento (o span que expõe
# sistema/catálogo/erro), preservando o resto útil da frase — mesma técnica de
# spans de strip_prohibited_phrases (casa no texto normalizado, remove do ORIGINAL;
# NFD + filtro de Mn preserva os índices de caracteres não-combinantes).
#
# CONSERVADOR: só casa "sistema/catálogo/erro" no CONTEXTO de falha de máquina.
# Usos de venda legítimos ("sistema Nespresso", "nosso sistema de torra") ficam
# intactos porque exigem o verbo/estado de erro colado (encontrou/achou/travou/
# fora/deu erro), não a palavra "sistema" isolada.
_KITCHEN_LEAK_RES: tuple[re.Pattern, ...] = (
    # "o sistema (nao) encontrou/achou/... [o 'X'] no catalogo de Y" — o fim ancora
    # em "no catalogo[ de Y]" OU na fronteira da cláusula (o que vier primeiro, lazy),
    # preservando o trecho útil que costuma vir depois ("ele tem as opções de…").
    re.compile(
        r"\b(?:o\s+)?sistema\s+(?:nao\s+)?(?:encontrou|achou|acha|localizou|encontra|localiza)\b"
        r"[^.?!\n]*?(?:\bno\s+catalogo(?:\s+de\s+[a-z_]+)?[,.]?|(?=[,.?!\n]|$))\s*"
    ),
    # "(nao) encontrei/achei/localizei ... no catalogo ..."
    re.compile(
        r"\b(?:nao\s+)?(?:encontrei|achei|localizei|acho)\b[^.?!\n]*?"
        r"\bno\s+catalogo(?:\s+de\s+[a-z_]+)?[,.]?\s*"
    ),
    # "o sistema travou / esta fora / fora do ar / caiu / bugou"
    re.compile(
        r"\b(?:o\s+)?sistema\s+(?:travou|caiu|esta\s+fora|ta\s+fora|fora\s+do\s+ar|bugou)\b"
        r"[^,.?!\n]*[,.]?\s*"
    ),
    # "deu (um) erro (aqui/no sistema) ..." até a próxima vírgula/fim de cláusula
    re.compile(r"\bdeu\s+(?:um\s+)?erro\b[^,.?!\n]*[,.]?\s*"),
    re.compile(r"\berro\s+(?:no\s+sistema|aqui|interno|de\s+sistema)\b[^,.?!\n]*[,.]?\s*"),
)


def strip_kitchen_leak(text: str) -> str:
    """Remove trechos que expõem a 'cozinha' (sistema/catálogo/erro) ao cliente.

    Casa sobre a versão normalizada (minúsculas, sem diacríticos) e remove os spans
    do texto ORIGINAL, preservando acentos/caixa do restante. Fail-open: se a
    remoção esvaziar a mensagem, devolve o texto ORIGINAL (a rede primária é a
    reescrita do retorno interno da tool). Função pura — sem I/O, testável isolada.
    """
    if not text:
        return text

    normalized = _normalize(text)
    spans: list[tuple[int, int]] = []
    for pattern in _KITCHEN_LEAK_RES:
        for m in pattern.finditer(normalized):
            spans.append((m.start(), m.end()))
    if not spans:
        return text

    # Une spans sobrepostos e remove em ordem inversa (índices batem 1:1 entre
    # normalized e text — NFD+Mn nunca insere/remove não-combinante).
    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    result = text
    for s, e in reversed(merged):
        result = result[:s] + result[e:]

    result = _collapse_whitespace_and_punctuation(result)
    return result if result.strip() else text


# ---------------------------------------------------------------------------
# 10. media_result_is_no_send (auditoria 2026-07-14 — caso Marcelo Dummel)
# ---------------------------------------------------------------------------
# media_tool_used marca INTENÇÃO (tool chamada), não ENVIO. enviar_foto_produto/
# enviar_fotos retornam "nao encontrada"/"Nenhuma foto" SEM levantar exceção — a
# flag virava True, a guarda de fotos verbalizadas era pulada, e a promessa "to
# mandando as fotos" saía sem foto. Este detector distingue o retorno de NÃO-envio
# do de sucesso/idempotência ("enfileirada", "ja enviada" = fotos já existem).
_MEDIA_NO_SEND_SIGNALS = ("nao encontrada", "nao encontrado", "nenhuma foto")


def media_result_is_no_send(result: str | None) -> bool:
    """True quando o retorno de uma tool de mídia indica que NADA foi enviado.

    False para sucesso ("enfileirada(s)") e para no-op idempotente ("ja
    enviada/enfileirada" — fotos já presentes na conversa). Função pura.
    """
    n = _normalize(result or "")
    return any(sig in n for sig in _MEDIA_NO_SEND_SIGNALS)


# ---------------------------------------------------------------------------
# 11. contains_open_question (auditoria 2026-07-14 — caso Gilberto Medeiros)
# ---------------------------------------------------------------------------
# O lead perguntou "Tenho que investir?" e foi descartado (registrar_sem_interesse_
# atual) SEM resposta. Detecta uma pergunta GENUÍNA (interrogativo ou termo de
# negócio dentro de um trecho terminado em "?"), ignorando cortesia pura ("tudo
# bem?", "ok?", "né?"). Deliberadamente conservador do lado do lead: só bloqueia o
# descarte quando há sinal claro de pergunta — falso-positivo custa pouco (o modelo
# responde antes), falso-negativo mantém o comportamento atual.
_OPEN_QUESTION_MARKERS = (
    # interrogativos
    "qual", "quais", "quanto", "quanta", "quantos", "quantas", "como", "quando",
    "onde", "quem", "por que", "porque", "pq",
    # verbos/termos de negócio comuns em pergunta de compra
    "tem ", "teria", "posso", "poderia", "consigo", "da pra", "preciso", "precisa",
    "precisaria", "investir", "funciona", "custa", "vale", "possivel", "minimo",
    "valor", "preco", "quanto custa", "e possivel",
)


def contains_open_question(text: str | None) -> bool:
    """True quando o texto do LEAD contém uma pergunta genuína (não só cortesia).

    Exige um trecho terminado em "?" cujo conteúdo normalizado contenha um
    interrogativo ou termo de negócio de `_OPEN_QUESTION_MARKERS`. Cortesia curta
    ("tudo bem?", "ok?") não casa. Função pura — sem I/O.
    """
    if not text or "?" not in text:
        return False
    normalized = _normalize(text)
    for chunk in _QUESTION_CHUNK_RE.findall(normalized):
        if any(marker in chunk for marker in _OPEN_QUESTION_MARKERS):
            return True
    return False


# ---------------------------------------------------------------------------
# 12. strip_media_history_markers (auditoria 2026-07-14 — caso Noelson)
# ---------------------------------------------------------------------------
# render_history_content (app.conversations.service) envelopa a legenda de mídia p/
# o LLM: '[Foto enviada por você: "Modelo de embalagem standup"]' (role=assistant) /
# '[Foto recebida do lead: "..."]' (role=user). Isso é DELIBERADO e correto p/ o
# histórico do LLM (fix 13/07, evita o modelo inventar autoria). O bug: o modelo
# ECOOU esse marcador como texto da resposta e ele chegou ao WhatsApp do cliente
# (onde "você" lê como se o CLIENTE tivesse enviado — autoria aparentemente
# invertida). Backstop: remove QUALQUER marcador-envelope de mídia do texto de SAÍDA.
# O formato do histórico permanece intocado — só a fala final é higienizada.
#
# Casa os rótulos de _MEDIA_CAPTION_LABELS (Foto/Vídeo/Documento/Figurinha/
# Localização/Contato) + autoria (enviad_ por você | recebid_ do lead) + legenda
# entre aspas. Acento/caixa-insensitive (casa no normalizado, remove do original).
_MEDIA_MARKER_RE = re.compile(
    r"\[\s*(?:foto|video|documento|figurinha|localizacao|contato)\s+"
    r"(?:enviad[oa]\s+por\s+voce|recebid[oa]\s+do\s+lead)\s*:\s*"
    r'"[^"\]]*"\s*\]'
)


def strip_media_history_markers(text: str) -> str:
    """Remove marcadores-envelope de mídia do histórico que vazaram no texto de saída.

    Ex.: '[Foto enviada por você: "standup"]'. Preserva o resto da mensagem. Se a
    remoção esvaziar o texto (bolha era só marcador — ruído puro), devolve o
    resultado vazio de propósito (o pipeline trata saída vazia como silêncio/
    fallback). Função pura — sem I/O, testável isoladamente.
    """
    if not text:
        return text

    normalized = _normalize(text)
    matches = list(_MEDIA_MARKER_RE.finditer(normalized))
    if not matches:
        return text

    result = text
    for m in reversed(matches):
        result = result[: m.start()] + result[m.end():]

    return _collapse_whitespace_and_punctuation(result)


# ---------------------------------------------------------------------------
# 13. normalize_proper_nouns (auditoria 90 dias — 2026-09-17; revisão pós
#     mutation testing no mesmo dia — reordenação C->B->A, gate de "café/blend
#     + produto", NEVER com lookback, guards de URL/e-mail e de quebra de
#     linha, NFC de entrada)
# ---------------------------------------------------------------------------
# A persona da Valéria escreve tudo em minúsculas de propósito (humanização de
# WhatsApp), mas o LLM generaliza demais a regra e achata nomes próprios junto.
# Medido em produção (90 dias): 22% das auto-menções da Valéria saem "valeria"
# em vez de "Valéria", e 18,3% das menções ao nome do lead saem minúsculas. O
# caso de maior volume é a saudação de abertura, enviada 340x como
# "aqui é a valeria, do comercial da café canastra".
#
# Mesma técnica de spans de strip_prohibited_phrases / normalize_orthography:
# casa sobre o texto NORMALIZADO (NFD + lower, sem diacríticos) e substitui no
# texto ORIGINAL pelos mesmos índices — NFD + filtro de Mn nunca insere/remove
# caractere não-combinante, então os offsets batem 1:1. Esse invariante só
# vale para texto já em forma composta (NFC); por isso a função pública
# NFC-normaliza a entrada uma única vez antes de tudo — texto NFD (raro, mas
# possível vindo de certos clientes/SOs) quebraria os offsets e corromperia a
# saída em vez de falhar aberto.
#
# ORDEM DAS CAMADAS — C (nome do lead) roda PRIMEIRO, B (produtos) no meio, A
# (léxico fixo) por ÚLTIMO, de propósito: a Camada A é a única com forma
# canônica GARANTIDAMENTE correta (acento incluso); a Camada C deriva a forma
# dela do nome GRAVADO NO BANCO, que pode estar sem acento ("Valeria"). Se A
# rodasse primeiro, um lead chamado "Valeria" (nome comum no Brasil, 1000+
# leads na base) faria a Camada C reescrever "Valéria" — já corrigida por A —
# de volta para "Valeria" sem acento por último, apagando em silêncio o fix da
# saudação de abertura para esse lead específico. Com A por último, ela
# sempre tem a palavra final — reescreve de novo por cima do que C tiver
# feito, então o resultado final não depende da ordem em que os dois layers
# colidem no mesmo token.
#
# PROTEÇÃO DE URL/E-MAIL — reaproveita `_URL_SPAN_RE` (seção 4, o mesmo split
# que `normalize_orthography` já usa): o texto é dividido em trechos fora de
# URL/e-mail (índices pares, onde as 3 camadas rodam) e trechos de URL/e-mail
# (índices ímpares, sempre intocados). Sem isso, "valeria@cafecanastra.com"
# viraria "Valéria@cafecanastra.com" — endereço inválido.

# Camada C — nome do lead (dinâmico): title-case do PRIMEIRO e ÚLTIMO token de
# `lead_name`, mínimo 3 caracteres, casado como palavra isolada. Aplica mesmo
# quando o nome está gravado em minúsculas no banco ("vanda" -> "Vanda").
#
# DOIS casos de caixa (revisão 2026-09-17 pós mutation testing, dado real:
# export de 2771 leads nomeados em leads-bling-completo-2026-08-08-br (1).csv
# — 42,3% de TODOS os nomes, 19,0% dos nomes de pessoa, estão gravados TODO-
# MAIÚSCULO):
#   - token TODO-MAIÚSCULO ("VANDA", "ELIATAN") -> Title Case ("Vanda",
#     "Eliatan") via .capitalize(). Sem isso a persona — cujo ponto inteiro é
#     escrever em minúsculas calmas — GRITA o nome de 1 em cada 5 leads
#     nomeados.
#   - qualquer outro token só tem a PRIMEIRA letra forçada; o resto fica
#     EXATAMENTE como está gravado (não força .lower()) — "Jose-Maria"
#     continua "Jose-Maria" (o "M" de Maria já é maiúsculo, legítimo), não
#     vira "Jose-maria". Essa forma (mista, não TODO-MAIÚSCULO) é só 0,5%
#     dos nomes de pessoa no mesmo export — e a maioria das ocorrências ali
#     é ruído de empresa ("PedidoOK", "Global Nove SpA"), não gente.
# Consequência de ambos os casos: esta camada NÃO restaura acento a partir do
# nome gravado (só a Camada A faz isso, e só para os nomes que conhece — por
# isso ela roda por último, ver acima).
# Efeito colateral ACEITO de propósito: um nome de lead que colide com uma
# palavra comum (ex.: lead_name="Rosa" + texto "a rosa dos ventos") também é
# capitalizado — falso-positivo raro e de baixo custo (pior caso: uma palavra
# comum maiusculizada), não vale a complexidade de desambiguar nome vs.
# palavra.
_LEAD_NAME_MIN_LEN = 3


def _title_case_lead_name(text: str, lead_name: str | None) -> str:
    if not lead_name:
        return text
    parts = lead_name.strip().split()
    if not parts:
        return text
    tokens: list[str] = []
    for token in (parts[0], parts[-1]):
        if token not in tokens and len(token) >= _LEAD_NAME_MIN_LEN:
            tokens.append(token)
    if not tokens:
        return text

    normalized = _normalize(text)
    spans: list[tuple[int, int, str]] = []
    for token in tokens:
        token_re = re.compile(r"\b" + re.escape(_normalize(token)) + r"\b")
        canon = token.capitalize() if token.isupper() else token[0].upper() + token[1:]
        for m in token_re.finditer(normalized):
            spans.append((m.start(), m.end(), canon))
    if not spans:
        return text
    spans.sort()
    result = text
    for s, e, repl in reversed(spans):
        result = result[:s] + repl + result[e:]
    return result


# Camada B — produtos com porta de contexto. Medido em produção (45 dias de
# mensagens do agente): capitalização cega seria muito errada — "canela" é
# produto em 191 casos e especiaria/ingrediente em 214 (quase empate; "suave"
# é 360 produto/15 adjetivo, "clássico" é 568/5). Só capitaliza quando:
#   - precedido (ADJACENTE) por determinante MASCULINO (o/do/no/ao/um/pelo/
#     nosso — sinal linguístico que separa "o Canela" produto de "a canela"
#     especiaria; por isso "da"/"de"/"com" ficam de fora de propósito); OU
#   - seguido (adjacente) de token de formato/preço (moído/em grãos/250g/
#     500g/1kg); OU
#   - precedido por "determinante + café/blend", com o produto logo em
#     seguida (ex.: "o nosso café suave") — medido em produção (45 dias,
#     1857 mensagens com nome de produto): esse padrão aparece 68x e não era
#     coberto pelo gate adjacente puro (que exige o determinante colado no
#     produto, sem "café"/"blend" no meio). Cuidado: 341 casos do gate de
#     formato/preço acima e 835 do gate de determinante adjacente já cobrem a
#     maior parte — este bridge é o complemento dos dois, não substituto.
#
# NEVER tem precedência sobre as três regras acima, mas é DUAS listas com
# janelas DIFERENTES (revisão 2026-09-17 pós mutation testing — uma janela
# única de 3 palavras pra tudo bloqueava a MAIORIA das menções genuínas de
# produto, porque objeção de preço é o caminho dominante do funil: "mais
# barato? o suave 250g" tinha 10 de 13 casos reais de "deveria capitalizar"
# bloqueados por um "mais"/"bem"/"bastante" 2-3 palavras atrás):
#   - NOUNS (substantivo de qualidade: torra/sabor/notas/nota/aroma/toque/
#     perfil) — janela de 3 palavras, MEDIDA em produção (90 dias de
#     mensagens do agente, distância substantivo->produto): distância 1
#     ("torra suave") = 0 ocorrências; distância 2 ("notas de canela") = 22;
#     distância 3 ("toque natural de canela") = 26 — a forma MAIS comum.
#     Estreitar pra 2 quebraria "toque especial de canela", "toque natural
#     de canela", "torra escura com canela", "toque cítrico bem suave",
#     "toque diferente tipo canela". Se o bridge "determinante + café/blend"
#     casou, a janela de NOUNS é aplicada ao texto ANTES do início do bridge
#     (não ao texto entre o bridge e o produto) — senão "a torra do nosso
#     café suave" escaparia: com o bridge no meio, "torra" fica a 4 palavras
#     do produto, fora de uma janela de 3 aplicada ingenuamente.
#     A janela NUNCA atravessa quebra de bolha/frase (`\n`, `.`, `?`, `!`) —
#     achado de mutation testing: dos 6 matches distintos de distância-3 em
#     produção, 1 era falso bloqueio ("torra especial\n\no microlote" —
#     "torra" fica na bolha ANTERIOR, sem relação com "microlote" na bolha
#     seguinte que tem determinante colado). Um substantivo de qualidade na
#     bolha/frase anterior não diz nada sobre esta. Isso também dá a "mais
#     barato? o suave 250g" um segundo motivo (independente do split
#     ADJACENT abaixo) pra capitalizar — o "?" reseta a janela.
#   - ADJACENT (intensificador/advérbio: final/estilo/jeito/mais/bem/super/
#     bastante) — só fazem sentido colados ("mais suave" = comparativo); a
#     2-3 palavras de distância eles disparam em cima de fraseio de venda
#     comum (objeção de preço: "mais barato? o suave 250g") e bloqueiam
#     produto de verdade. Só bloqueiam quando são a palavra IMEDIATAMENTE
#     anterior ao produto — por construção, nunca atravessam bolha/frase.
# NÃO cobre fraseio de lista/escolha ("temos clássico, suave e canela",
# "prefere suave ou clássico?" — 131 ocorrências em 45 dias): ambíguo para
# gate determinístico o suficiente para valer a pena; fica a cargo do prompt.
_PRODUCT_MAP = {
    "suave": "Suave",
    "classico": "Clássico",
    "canela": "Canela",
    "microlote": "Microlote",
}
# Ordenado por tamanho decrescente por precaução futura (mesmo motivo do
# sort da Camada A, ver comentário lá embaixo): hoje é um no-op comportamental
# — nenhuma chave de _PRODUCT_MAP é prefixo de outra — mas evita a armadilha
# no dia em que uma for.
_PRODUCT_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(_PRODUCT_MAP, key=len, reverse=True)) + r")\b"
)
_PRODUCT_DETERMINERS = {"o", "do", "no", "ao", "um", "pelo", "nosso"}
_PRODUCT_NEVER_NOUNS = {"torra", "sabor", "notas", "nota", "aroma", "toque", "perfil"}
_PRODUCT_NEVER_ADJACENT = {"final", "estilo", "jeito", "mais", "bem", "super", "bastante"}
_PRODUCT_NEVER_NOUN_LOOKBACK_WORDS = 3  # "notas de canela" = notas(2 atrás) de(1 atrás)
_PRODUCT_WORD_TOKEN_RE = re.compile(r"[a-z]+")
# Reset da janela de NOUNS em quebra de bolha/frase — ver comentário acima.
_PRODUCT_NOUN_BOUNDARY_RE = re.compile(r"[\n.?!]")
_PRODUCT_FORMAT_FOLLOW_RE = re.compile(r"^\s*(?:moido|em\s+graos|250g|500g|1kg)\b")
# "determinante + cafe/blend" imediatamente antes do produto (ver comentário
# acima). Construído a partir de `_PRODUCT_DETERMINERS` (não duplicado à mão)
# para não desalinhar se a lista de determinantes mudar.
_PRODUCT_CAFE_BRIDGE_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_PRODUCT_DETERMINERS, key=len, reverse=True))
    + r")[ \t]+(?:cafe|blend)[ \t]*$"
)


def _noun_scope_since_boundary(span: str) -> list[str]:
    """Palavras de `span` que vêm DEPOIS da última quebra de bolha/frase.

    Corta em `\n` (bolha nova do WhatsApp) e em `.`/`?`/`!` (frase nova) —
    NÃO em vírgula (fraseio comum como "bastante procurado, o microlote"
    não deve perder o "bastante" como sinal, só a distância dele já resolve
    isso via ADJACENT). Sem cortar aqui, "torra especial\n\no microlote"
    bloqueava "microlote" com um "torra" que pertence à bolha anterior.
    """
    boundary_end = 0
    for m in _PRODUCT_NOUN_BOUNDARY_RE.finditer(span):
        boundary_end = m.end()
    return _PRODUCT_WORD_TOKEN_RE.findall(span[boundary_end:])


def _capitalize_products(text: str) -> str:
    normalized = _normalize(text)
    spans: list[tuple[int, int, str]] = []
    for m in _PRODUCT_WORD_RE.finditer(normalized):
        before = normalized[: m.start()]
        after = normalized[m.end() :]
        prev_words = _PRODUCT_WORD_TOKEN_RE.findall(before)
        nearest = prev_words[-1] if prev_words else ""

        if nearest in _PRODUCT_NEVER_ADJACENT:
            continue

        bridge_m = _PRODUCT_CAFE_BRIDGE_RE.search(before)
        # Se o bridge casou, a janela de NOUNS olha o texto ANTES do bridge
        # (não entre o bridge e o produto) — ver comentário acima. Em ambos
        # os casos, corta em quebra de bolha/frase primeiro.
        noun_scope_text = before[: bridge_m.start()] if bridge_m else before
        noun_scope_words = _noun_scope_since_boundary(noun_scope_text)
        if any(
            w in _PRODUCT_NEVER_NOUNS
            for w in noun_scope_words[-_PRODUCT_NEVER_NOUN_LOOKBACK_WORDS:]
        ):
            continue

        capitalize = (
            nearest in _PRODUCT_DETERMINERS
            or bool(_PRODUCT_FORMAT_FOLLOW_RE.match(after))
            or bool(bridge_m)
        )
        if capitalize:
            spans.append((m.start(), m.end(), _PRODUCT_MAP[m.group(1)]))
    if not spans:
        return text
    result = text
    for s, e, repl in reversed(spans):
        result = result[:s] + repl + result[e:]
    return result


# Camada A — léxico inequívoco: nomes próprios com forma canônica FIXA,
# independente da caixa/acento de entrada (inclui restauração de acento, ex.:
# "cafe canastra" sem acento -> "Café Canastra"). Roda por ÚLTIMO (ver ordem
# das camadas acima) — é a autoridade final.
# Alternativas ordenadas por comprimento decrescente (mesmo truque de
# `_ORTHO_WORD_RE`): isso NÃO é o que impede "canastra" de casar sozinha
# dentro de "serra da canastra" hoje — "canastra" é SUFIXO de "serra da
# canastra", então o scan não-sobreposto da esquerda para a direita do
# `finditer` já consome a frase inteira antes de chegar lá, em QUALQUER ordem
# de alternativas (o finditer nunca reabre uma posição já consumida por um
# match anterior). A ordenação por tamanho importa para o caso ainda
# inexistente de entradas que COMPARTILHAM O INÍCIO (ex.: se um dia existir
# "cafe" solto ao lado de "cafe especial", a alternativa curta tentada
# primeiro venceria e a mais longa nunca seria tentada) — mantida por
# precaução futura, não porque resolve o caso "canastra"/"serra da canastra"
# de hoje.
# Usa `[ \t]+` (não `\s+`) entre as palavras de uma frase de duas ou mais
# palavras: a persona quebra bolhas do WhatsApp propositalmente em `\n`;
# `\s+` casaria "cafe" numa bolha com "canastra" na bolha seguinte e apagaria
# a quebra ao substituir pela forma canônica de uma linha só.
_PROPER_NOUN_MAP = {
    "serra da canastra": "Serra da Canastra",
    "cafe canastra": "Café Canastra",
    "joao bras": "João Brás",
    "canastra": "Canastra",
    "valeria": "Valéria",
    "nespresso": "Nespresso",
    "sca": "SCA",
    "uberlandia": "Uberlândia",
    "pratinha": "Pratinha",
}
_PROPER_NOUN_RE = re.compile(
    r"\b("
    + "|".join(
        key.replace(" ", r"[ \t]+")
        for key in sorted(_PROPER_NOUN_MAP, key=len, reverse=True)
    )
    + r")\b"
)


def _apply_proper_noun_lexicon(text: str) -> str:
    normalized = _normalize(text)
    matches = list(_PROPER_NOUN_RE.finditer(normalized))
    if not matches:
        return text
    result = text
    for m in reversed(matches):
        key = re.sub(r"[ \t]+", " ", m.group(0))
        result = result[: m.start()] + _PROPER_NOUN_MAP[key] + result[m.end() :]
    return result


def normalize_proper_nouns(text: str, lead_name: str | None = None) -> str:
    """Restaura maiúscula (e acento) em nomes próprios achatados pelo LLM.

    Roda em 3 camadas, na ordem C -> B -> A (a Camada A tem a PALAVRA FINAL —
    ver o comentário no topo da seção 13 para o caso real que motivou essa
    ordem: um lead chamado "Valeria" sem acento no banco):

    Camada C: nome do lead — title-case do primeiro/último token de
    `lead_name` quando aparece como palavra isolada no texto. Token
    TODO-MAIÚSCULO ("VANDA") vira Title Case ("Vanda" — a persona nunca
    grita); qualquer outro token só tem a PRIMEIRA letra forçada, o resto
    fica como está gravado (acento não é restaurado a partir do nome).
    Camada B: produtos (Clássico/Suave/Canela/Microlote) — só capitaliza com
    porta de contexto (determinante masculino adjacente, "determinante +
    café/blend" adjacente, ou token de formato/preço adjacente depois; a
    lista NEVER tem precedência — substantivo de qualidade olha até 3
    palavras para trás, intensificador/advérbio só bloqueia se adjacente).
    Camada A: léxico inequívoco (Valéria, João Brás, Café Canastra, Canastra
    isolado, Nespresso, SCA, Uberlândia, Pratinha, Serra da Canastra) —
    capitaliza sempre, fronteira de palavra, restaurando acento quando a
    entrada vier sem ele.

    URLs e e-mails (`_URL_SPAN_RE`, seção 4) nunca são tocados por nenhuma
    das 3 camadas.

    NÃO cobre cidades genéricas (ex.: "goiás", "copacabana") — não são
    deterministicamente enumeráveis. NÃO cobre fraseio de lista/escolha da
    Camada B (ex.: "temos clássico, suave e canela") — ambíguo demais para
    um gate determinístico. NÃO reconecta nome/frase partido entre bolhas
    por `\n` (ex.: "serra da\ncanastra" vira "serra da\nCanastra" só na
    segunda linha, "joao\nbras" fica como está) — a quebra proposital da
    persona é preservada (ver `[ \t]+` na Camada A), o fix fica parcial
    nesses casos raros de propósito. Os três ficam a cargo do prompt.

    Função pura — sem I/O, sem logging. Fail-open: qualquer exceção (incl.
    `text` não ser string) devolve o texto original inalterado.
    """
    if not text:
        return text
    try:
        text = unicodedata.normalize("NFC", text)
        parts = _URL_SPAN_RE.split(text)
        for i in range(0, len(parts), 2):  # índices pares = fora de URL/e-mail
            chunk = _title_case_lead_name(parts[i], lead_name)
            chunk = _capitalize_products(chunk)
            chunk = _apply_proper_noun_lexicon(chunk)
            parts[i] = chunk
        return "".join(parts)
    except Exception:
        return text
