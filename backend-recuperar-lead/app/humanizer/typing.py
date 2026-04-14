import random


def calculate_typing_delay(text: str) -> float:
    """Calculate a human-like typing delay in seconds for a message.

    Formula: (character_count * typing_speed) + thinking_pause
    - typing_speed: 25-80ms per character (randomized)
    - thinking_pause: 300-800ms before typing starts
    """
    char_count = len(text)
    typing_speed_ms = random.randint(25, 80)
    thinking_pause_ms = random.randint(300, 800)

    total_ms = (char_count * typing_speed_ms) + thinking_pause_ms

    # Cap at 12 seconds per bubble to avoid excessive waits
    total_ms = min(total_ms, 12000)

    return total_ms / 1000.0
