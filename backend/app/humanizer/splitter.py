import re

# Hard cap: never send more than this many WhatsApp bubbles per AI reply.
# Paragraphs beyond MAX_BUBBLES are merged into the last bubble (no content dropped).
MAX_BUBBLES = 3


def split_into_bubbles(text: str) -> list[str]:
    """Split an AI response into WhatsApp-style message bubbles.

    Bubble boundary rules
    ----------------------
    - A **paragraph break** (blank line, i.e. ``\\n\\n``) creates a new bubble.
    - A **single newline** (``\\n``) is a soft break inside a paragraph: it does
      NOT create a new bubble; it is collapsed into a single space so the
      paragraph remains one bubble.
    - The model sometimes emits the *literal two-character sequence* ``\\n``
      (backslash + n) instead of a real newline.  Normalise both forms:
      literal ``\\n\\n`` → real ``\\n\\n`` (paragraph break);
      literal ``\\n``    → real ``\\n``    (soft break, stays in same bubble).
      **Important:** replace the four-character literal first so we don't
      accidentally destroy paragraph boundaries when replacing the two-char form.

    Overflow / clamp
    ----------------
    If splitting yields more than ``MAX_BUBBLES`` paragraphs, the excess
    paragraphs are joined with ``\\n\\n`` into the last allowed bubble so that
    no content is ever silently dropped.

    Other guarantees
    ----------------
    - Each bubble is stripped of leading/trailing whitespace.
    - Empty bubbles (after stripping) are discarded.
    - ``r$`` is corrected to ``R$`` in every bubble (legacy safety net).
    - Empty / whitespace-only input returns ``[]``.
    """
    if not text or not text.strip():
        return []

    # --- Step 1: normalise literal backslash-n sequences emitted by the model ---
    # Must do \\n\\n (4 chars) before \\n (2 chars) to avoid double-converting.
    text = text.replace("\\n\\n", "\n\n").replace("\\n", "\n")

    # --- Step 2: split into paragraphs on blank-line boundaries (\n\n) ---
    # re.split(r'\n\s*\n') also tolerates lines that contain only spaces/tabs.
    paragraphs = re.split(r'\n\s*\n', text)

    # --- Step 3: within each paragraph, collapse single \n to a space ---
    bubbles = []
    for para in paragraphs:
        # Replace internal single newlines with a space and strip outer whitespace
        collapsed = re.sub(r'\n', ' ', para).strip()
        # Normalise any run of spaces produced by collapsing
        collapsed = re.sub(r' {2,}', ' ', collapsed)
        if collapsed:
            bubbles.append(collapsed)

    # --- Step 3.5: saudação colada em run-on (auditoria 12/07, caso humbertocarvao) ---
    # Quando o modelo separa saudação/pitch/pergunta com \n SIMPLES, o Step 3 cola tudo
    # numa bolha corrida sem pontuação ("bom dia marca própria e o que..."). Descolamos
    # a saudação para a própria bolha — ANTES do clamp, para o teto de bolhas continuar
    # valendo. Resto curto (vocativo, "pra você também") fica junto: só age em run-on real.
    expanded: list[str] = []
    for b in bubbles:
        expanded.extend(_split_leading_greeting(b))
    bubbles = expanded

    # --- Step 3.6: pergunta roteirizada colada no meio da bolha (varredura 12/07) ---
    # A pergunta de descoberta do funil ("voce ja tem uma marca criada...") é roteirizada
    # verbatim nos prompts de estagio, e o modelo às vezes a cola no fim do pitch com \n
    # simples (colapsado em espaço pelo Step 3). Seam determinística: se ela aparece no
    # MEIO de uma bolha, vira bolha própria. Também pré-clamp.
    expanded = []
    for b in bubbles:
        expanded.extend(_split_scripted_question(b))
    bubbles = expanded

    # --- Step 4: clamp to MAX_BUBBLES (merge overflow into last bucket) ---
    if len(bubbles) > MAX_BUBBLES:
        # Keep the first (MAX_BUBBLES - 1) bubbles intact, merge the rest.
        overflow = bubbles[MAX_BUBBLES - 1:]
        bubbles = bubbles[: MAX_BUBBLES - 1]
        bubbles.append("\n\n".join(overflow))

    # --- Step 5: R$ uppercase safety net ---
    bubbles = [re.sub(r'r\$', 'R$', b) for b in bubbles]

    # --- Step 6: "sem ponto final" — strip a single terminal sentence period ---
    # A pessoa real no WhatsApp não fecha bolha com ponto; ela quebra a bolha.
    # Removemos APENAS um '.' no fim da bolha. Preservamos:
    #   - reticências "..." (pausa estilística, não é ponto final)
    #   - pontos internos de URLs (cafecanastra.com) e números (R$1.000),
    #     que nunca ficam no fim da bolha.
    bubbles = [_strip_terminal_period(b) for b in bubbles]

    # Rede de segurança do "?" — vem DEPOIS do strip do ponto final (que nunca toca em "?").
    bubbles = [_ensure_question_mark(b) for b in bubbles]

    return bubbles


# Saudações que abrem bolha. O resto precisa ser LONGO (run-on de verdade) para o
# split agir — "bom dia pra você também" e "boa tarde Ana" ficam intactas.
_GREETING_SPLIT_RE = re.compile(
    r"^(oi|ol[aá]|bom dia|boa tarde|boa noite)[,!]?\s+(?=\S)",
    re.IGNORECASE,
)
_GREETING_MIN_REST = 40


def _split_leading_greeting(bubble: str) -> list[str]:
    """Descola a saudação inicial quando ela abre uma bolha corrida longa.

    Retorna [saudação, resto] apenas quando o resto tem >= _GREETING_MIN_REST
    caracteres (run-on real); em qualquer outro caso devolve a bolha intacta.
    Função pura — sem I/O.
    """
    m = _GREETING_SPLIT_RE.match(bubble)
    if not m:
        return [bubble]
    rest = bubble[m.end():].strip()
    if len(rest) < _GREETING_MIN_REST:
        return [bubble]
    return [m.group(1), rest]


# Perguntas roteirizadas dos prompts de estágio que o modelo cola no fim do pitch.
# O seam corta ANTES da pergunta quando ela aparece no meio da bolha (>= _SEAM_MIN_PREFIX
# chars antes dela); no início da bolha não há nada a fazer.
_SCRIPTED_QUESTION_SEAM_RE = re.compile(
    r"\s(?=voc[eê] j[aá] tem uma marca)",
    re.IGNORECASE,
)
_SEAM_MIN_PREFIX = 20


def _split_scripted_question(bubble: str) -> list[str]:
    """Descola a pergunta roteirizada do funil quando colada no meio da bolha.

    Retorna [prefixo, pergunta] quando o seam existe após >= _SEAM_MIN_PREFIX chars;
    caso contrário devolve a bolha intacta. Função pura — sem I/O.
    """
    m = _SCRIPTED_QUESTION_SEAM_RE.search(bubble)
    if not m or m.start() < _SEAM_MIN_PREFIX:
        return [bubble]
    prefix = bubble[:m.start()].rstrip()
    question = bubble[m.end():].strip()
    if not prefix or not question:
        return [bubble]
    return [prefix, question]


def _strip_terminal_period(bubble: str) -> str:
    """Remove um único ponto final de frase no fim da bolha.

    Mantém reticências (termina em '..') e qualquer ponto interno (URLs/números),
    pois esses não são o último caractere da bolha.
    """
    b = bubble.rstrip()
    if b.endswith(".") and not b.endswith(".."):
        b = b[:-1].rstrip()
    return b


# Palavras/aberturas inequívocas de pergunta (PT-BR informal). Conservador de propósito:
# só re-adicionamos "?" quando a bolha ABRE com um destes — evita falso-positivo em declarativas.
# Nota: "que " foi removido — bare "que" é ambíguo ("que bonito!", "que saudade") e a fronteira
# de palavra não resolve isso; "o que" e "o quê" cobrem o caso interrogativo relevante.
_QUESTION_STARTERS = (
    "qual", "quais", "o que", "o quê", "como", "quando", "onde", "quanto",
    "quantos", "quantas", "quem", "por que", "por quê", "quer", "prefere", "poderia",
    "consegue", "seria", "te interessa", "faz sentido",
)

# Regex compilada com fronteira de palavra (\b) para evitar falso-positivo em prefixos:
# "qualquer" NÃO deve bater em "qual"; "queria" NÃO deve bater em "quer".
_QUESTION_RE = re.compile(
    r'^(?:' + '|'.join(re.escape(s) for s in _QUESTION_STARTERS) + r')\b',
    re.IGNORECASE,
)


def _ensure_question_mark(bubble: str) -> str:
    """Rede de segurança: re-adiciona '?' em bolha inequivocamente interrogativa sem pontuação final.

    O modelo às vezes derruba o '?' por over-aplicar o 'sem ponto final' (falha real lead
    5531999844461). Só agimos quando a bolha ABRE com uma palavra interrogativa clara e NÃO termina
    em pontuação (., ?, !, …) — conservador para nunca transformar uma declarativa em pergunta.

    O matching usa fronteira de palavra (\b) para que "qualquer" não bata em "qual" e
    "queria" não bata em "quer".

    Duas guardas de NÃO-ação (lead 5561999119005, 11/07): a bolha "o que está incluso é..."
    foi fundida pelo clamp de overflow com o parágrafo seguinte e ganhou "?" indevido —
    o starter do 1º parágrafo não descreve o fim do último parágrafo fundido.
    """
    # Guarda 1: bolha fundida pelo clamp de overflow (tem "\n\n" interno) — o início e o
    # fim são parágrafos diferentes, o starter do início não fala sobre o fim.
    if "\n\n" in bubble:
        return bubble
    # Guarda 2: bolha longa — a classe de falha que a rede corrige é uma pergunta curta que
    # perdeu o "?" (caso 5531999844461); declarativas clivadas longas ficam de fora.
    if len(bubble) > 120:
        return bubble
    b = bubble.rstrip()
    if not b or b[-1] in ".?!…":
        return bubble
    low = b.lower()
    if _QUESTION_RE.match(low):
        return b + "?"
    return bubble
