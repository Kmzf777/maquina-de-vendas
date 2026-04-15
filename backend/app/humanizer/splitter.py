import re


def split_into_bubbles(text: str) -> list[str]:
    """Split AI response into WhatsApp-style message bubbles.

    The AI is instructed to use \\n\\n as bubble separators,
    but often produces single \\n instead. We split on any
    newline so every line becomes its own WhatsApp bubble.
    """
    bubbles = [b.strip() for b in text.split("\n") if b.strip()]
    # Safety net: ensure R$ is always uppercase
    bubbles = [re.sub(r'r\$', 'R$', b) for b in bubbles]
    return bubbles
