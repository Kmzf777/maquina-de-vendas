import re


def test_media_placeholder_format():
    """Verify media placeholder format matches what processor expects."""
    placeholder = "[audio: media_id=abc123]"
    pattern = r"\[audio: media_id=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "abc123"


def test_image_placeholder_format():
    placeholder = "[image: media_id=img456]"
    pattern = r"\[image: media_id=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "img456"
