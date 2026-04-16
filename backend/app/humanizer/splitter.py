import re

_SENTENCE_END = re.compile(r'[.!?…)\]"\'»]$')


def split_into_bubbles(text: str) -> list[str]:
    """Split AI response into WhatsApp-style message bubbles.

    The AI uses \\n\\n as bubble separators. The model sometimes emits
    the literal two-character sequence backslash-n (the string r'\\n')
    instead of a real newline. Normalise both forms before splitting.
    """
    # Replace literal \n\n and \n (backslash-n as text) with real newlines
    text = text.replace("\\n\\n", "\n").replace("\\n", "\n")
    bubbles = [b.strip() for b in text.split("\n") if b.strip()]
    # Safety net: ensure R$ is always uppercase
    bubbles = [re.sub(r'r\$', 'R$', b) for b in bubbles]
    # Drop truncated trailing bubble: very short AND no sentence-ending punctuation
    if len(bubbles) > 1:
        last = bubbles[-1]
        if len(last) < 30 and not _SENTENCE_END.search(last):
            bubbles = bubbles[:-1]
    return bubbles
