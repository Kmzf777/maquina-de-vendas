"""
Tests for split_into_bubbles — new paragraph-based splitting with 3-bubble clamp.

Spec (Task 2.1):
- Bubble boundary = paragraph break (\n\n or equivalent). Single \n = same bubble.
- Literal \\n\\n (model artifact) = paragraph break; literal \\n = soft break (same bubble).
- Hard clamp: max 3 bubbles; overflow paragraphs 3+ are merged into bubble 3 with '\n\n'.
- R$ uppercase safety net preserved.
- Empty / whitespace-only input → [].
"""

import pytest
from app.humanizer.splitter import split_into_bubbles, MAX_BUBBLES


# ---------------------------------------------------------------------------
# Basic paragraph splitting
# ---------------------------------------------------------------------------

def test_two_paragraphs():
    """Two paragraphs separated by \\n\\n → 2 bubbles."""
    text = "oi, tudo bem?\n\naqui e a valeria, da cafe canastra"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 2
    assert bubbles[0] == "oi, tudo bem?"
    assert bubbles[1] == "aqui e a valeria, da cafe canastra"


def test_three_paragraphs():
    """Three paragraphs → 3 bubbles (basic split, no clamp needed)."""
    text = "oi, tudo bem?\n\naqui e a valeria, da cafe canastra\n\nvoce trabalha com revenda?"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3
    assert bubbles[0] == "oi, tudo bem?"
    assert bubbles[2] == "voce trabalha com revenda?"


# ---------------------------------------------------------------------------
# Single \n inside a paragraph → same bubble (not split)
# ---------------------------------------------------------------------------

def test_single_newline_same_bubble():
    """Six lines joined by single \\n collapse into ONE bubble."""
    text = "linha1\nlinha2\nlinha3\nlinha4\nlinha5\nlinha6"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 1, f"Expected 1 bubble, got {len(bubbles)}: {bubbles}"


def test_single_newline_joins_as_space():
    """Single \\n within a paragraph should produce one bubble containing all content."""
    text = "parte A\nparte B"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 1
    # Content must be preserved (both parts present)
    assert "parte A" in bubbles[0]
    assert "parte B" in bubbles[0]


def test_mixed_single_and_double_newlines():
    """Paragraph 1 has a soft break; paragraphs split at \\n\\n."""
    text = "linha1\nlinha2\n\nparágrafo2"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 2
    # First bubble must contain both lines
    assert "linha1" in bubbles[0]
    assert "linha2" in bubbles[0]
    assert bubbles[1] == "parágrafo2"


# ---------------------------------------------------------------------------
# Overflow clamp (max 3 bubbles)
# ---------------------------------------------------------------------------

def test_five_paragraphs_clamp_to_three():
    """5 paragraphs → exactly 3 bubbles; all content preserved."""
    parts = ["p1", "p2", "p3", "p4", "p5"]
    text = "\n\n".join(parts)
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3, f"Expected 3 bubbles, got {len(bubbles)}: {bubbles}"
    # Bubbles 1 and 2 are the first two paragraphs
    assert bubbles[0] == "p1"
    assert bubbles[1] == "p2"
    # Bubble 3 must contain paragraphs 3, 4, and 5 — no content dropped
    for part in ("p3", "p4", "p5"):
        assert part in bubbles[2], f"'{part}' missing from overflow bubble: {bubbles[2]}"


def test_four_paragraphs_clamp_to_three():
    """4 paragraphs → exactly 3 bubbles; paragraph 4 merged into bubble 3."""
    text = "alpha\n\nbeta\n\ngamma\n\ndelta"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3
    assert bubbles[0] == "alpha"
    assert bubbles[1] == "beta"
    assert "gamma" in bubbles[2]
    assert "delta" in bubbles[2]


def test_max_bubbles_constant():
    """MAX_BUBBLES module constant must equal 3."""
    assert MAX_BUBBLES == 3


# ---------------------------------------------------------------------------
# Literal backslash-n normalization (model artifact)
# ---------------------------------------------------------------------------

def test_literal_backslash_n_n_is_paragraph_break():
    """Literal \\\\n\\\\n (4-char model artifact) behaves like real paragraph break."""
    # Python string: "p1\\n\\np2" → the actual characters: p1\n\np2
    text = "p1\\n\\np2"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 2
    assert bubbles[0] == "p1"
    assert bubbles[1] == "p2"


def test_literal_backslash_n_is_soft_break():
    """Literal \\\\n (2-char model artifact) is a soft break → same bubble."""
    # Python string: "parte A\\nparte B" → actual chars: parte A\nparte B
    text = "parte A\\nparte B"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 1
    assert "parte A" in bubbles[0]
    assert "parte B" in bubbles[0]


def test_literal_backslash_n_then_paragraph_clamp():
    """Mixed literal and real separators with 5 paragraphs → clamp to 3."""
    # Build: p1\\n\\np2\\n\\np3\\n\\np4\\n\\np5 (literal separators)
    text = "p1\\n\\np2\\n\\np3\\n\\np4\\n\\np5"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3
    for part in ("p1", "p2", "p3", "p4", "p5"):
        combined = " ".join(bubbles)
        assert part in combined, f"'{part}' missing from output: {bubbles}"


# ---------------------------------------------------------------------------
# R$ safety net
# ---------------------------------------------------------------------------

def test_lowercase_r_dollar_corrected():
    """r$23,90 → R$23,90."""
    bubbles = split_into_bubbles("o 250g sai r$23,90 a unidade")
    assert bubbles[0] == "o 250g sai R$23,90 a unidade"


def test_uppercase_r_dollar_preserved():
    """R$44,90 remains R$44,90."""
    bubbles = split_into_bubbles("o valor e R$44,90")
    assert bubbles[0] == "o valor e R$44,90"


def test_r_dollar_in_overflow_bubble():
    """R$ fix applied even in the merged overflow bubble."""
    parts = ["p1", "p2", "preco r$10,00", "extra r$5,00", "final"]
    text = "\n\n".join(parts)
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3
    assert "R$10,00" in bubbles[2]
    assert "R$5,00" in bubbles[2]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string():
    assert split_into_bubbles("") == []


def test_whitespace_only():
    assert split_into_bubbles("   ") == []
    assert split_into_bubbles("\n\n\n\n") == []
    assert split_into_bubbles("  \n\n  \n\n  ") == []


def test_single_message_no_newlines():
    assert split_into_bubbles("uma mensagem so") == ["uma mensagem so"]


def test_strips_whitespace_per_bubble():
    text = "  msg1  \n\n  msg2  \n\n"
    bubbles = split_into_bubbles(text)
    assert bubbles == ["msg1", "msg2"]


def test_tolerates_blank_line_with_spaces():
    """\\n  \\n (blank line with spaces) should also split paragraphs."""
    text = "para1\n  \npara2"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 2
    assert bubbles[0] == "para1"
    assert bubbles[1] == "para2"
