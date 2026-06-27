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
_QUESTION_STARTERS = (
    "qual", "quais", "o que", "o quê", "que ", "como", "quando", "onde", "quanto",
    "quantos", "quantas", "quem", "por que", "por quê", "quer", "prefere", "poderia",
    "consegue", "seria", "te interessa", "faz sentido",
)


def _ensure_question_mark(bubble: str) -> str:
    """Rede de segurança: re-adiciona '?' em bolha inequivocamente interrogativa sem pontuação final.

    O modelo às vezes derruba o '?' por over-aplicar o 'sem ponto final' (falha real lead
    5531999844461). Só agimos quando a bolha ABRE com uma palavra interrogativa clara e NÃO termina
    em pontuação (., ?, !, …) — conservador para nunca transformar uma declarativa em pergunta.
    """
    b = bubble.rstrip()
    if not b or b[-1] in ".?!…":
        return bubble
    low = b.lower()
    if low.startswith(_QUESTION_STARTERS):
        return b + "?"
    return bubble
