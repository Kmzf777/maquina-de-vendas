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
