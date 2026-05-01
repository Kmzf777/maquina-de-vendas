import re


def test_media_placeholder_format():
    """Verify media placeholder format matches what processor expects."""
    placeholder = "[audio: media_url=https://evo.com/audio/123]"
    pattern = r"\[audio: media_url=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "https://evo.com/audio/123"


def test_image_placeholder_format():
    placeholder = "[image: media_url=https://evo.com/img/456]"
    pattern = r"\[image: media_url=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "https://evo.com/img/456"


def test_pure_audio_meta_media_url_extracted():
    """Pure audio combined_text (buffer format) yields a media value match."""
    combined = "[audio: media_url=9876543210]"
    pattern = r"^\s*\[audio: media_url=(\S+)\]\s*$"
    m = re.fullmatch(pattern, combined)
    assert m is not None
    assert m.group(1) == "9876543210"


def test_mixed_text_audio_not_pure_audio():
    """Text + audio buffer is NOT treated as pure audio (no media extracted)."""
    combined = "oi tudo bem\n[audio: media_url=9876543210]"
    pattern = r"^\s*\[audio: media_url=(\S+)\]\s*$"
    m = re.fullmatch(pattern, combined)
    assert m is None
