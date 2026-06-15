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

    return bubbles
