"""Resolvedores de wamid devem enxergar mídia (item 5 do plano 11/07).

Antes: resolve_message_text_by_wamid / resolve_message_texts_by_wamids liam só
`content`. Um reply a uma imagem sem legenda (content="") resolvia para vazio e o
marcador do prompt degradava para o genérico "[Em resposta a uma mensagem anterior]".
Agora: os resolvedores também buscam `message_type` e aplicam
describe_media_placeholder — o marcador vira '[Em resposta a: "[imagem]"]'.
"""
from unittest.mock import patch


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Fake encadeável do postgrest: registra o select e devolve rows fixas."""

    def __init__(self, rows):
        self._rows = rows
        self.select_arg = None

    def select(self, arg, *a, **k):
        self.select_arg = arg
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.query = None

    def table(self, name):
        self.query = _Query(self._rows)
        return self.query


# ---------------------------------------------------------------------------
# resolve_message_text_by_wamid
# ---------------------------------------------------------------------------

def test_single_resolver_image_without_caption_returns_placeholder():
    from app.conversations.service import resolve_message_text_by_wamid

    sb = _FakeSupabase([{"content": "", "message_type": "image"}])
    with patch("app.conversations.service.get_supabase", return_value=sb):
        assert resolve_message_text_by_wamid("wamid.IMG") == "[imagem]"


def test_single_resolver_text_row_unchanged():
    from app.conversations.service import resolve_message_text_by_wamid

    sb = _FakeSupabase([{"content": "quanto custa?", "message_type": "text"}])
    with patch("app.conversations.service.get_supabase", return_value=sb):
        assert resolve_message_text_by_wamid("wamid.TXT") == "quanto custa?"


def test_single_resolver_selects_message_type_column():
    from app.conversations.service import resolve_message_text_by_wamid

    sb = _FakeSupabase([{"content": "x", "message_type": "text"}])
    with patch("app.conversations.service.get_supabase", return_value=sb):
        resolve_message_text_by_wamid("wamid.X")
    assert "message_type" in sb.query.select_arg


def test_single_resolver_image_with_caption_keeps_caption():
    from app.conversations.service import resolve_message_text_by_wamid

    sb = _FakeSupabase([{"content": "Classico — torra media", "message_type": "image"}])
    with patch("app.conversations.service.get_supabase", return_value=sb):
        assert resolve_message_text_by_wamid("wamid.CAP") == "Classico — torra media"


def test_single_resolver_missing_row_returns_none():
    from app.conversations.service import resolve_message_text_by_wamid

    sb = _FakeSupabase([])
    with patch("app.conversations.service.get_supabase", return_value=sb):
        assert resolve_message_text_by_wamid("wamid.GONE") is None


# ---------------------------------------------------------------------------
# resolve_message_texts_by_wamids (batch)
# ---------------------------------------------------------------------------

def test_batch_resolver_applies_placeholder_and_passthrough():
    from app.conversations.service import resolve_message_texts_by_wamids

    rows = [
        {"wamid": "wamid.IMG", "content": "", "message_type": "image"},
        {"wamid": "wamid.AUD", "content": None, "message_type": "audio"},
        {"wamid": "wamid.TXT", "content": "bom dia", "message_type": "text"},
    ]
    sb = _FakeSupabase(rows)
    with patch("app.conversations.service.get_supabase", return_value=sb):
        out = resolve_message_texts_by_wamids(["wamid.IMG", "wamid.AUD", "wamid.TXT"])

    assert out["wamid.IMG"] == "[imagem]"
    assert out["wamid.AUD"] == "[áudio]"
    assert out["wamid.TXT"] == "bom dia"


def test_batch_resolver_selects_message_type_column():
    from app.conversations.service import resolve_message_texts_by_wamids

    sb = _FakeSupabase([])
    with patch("app.conversations.service.get_supabase", return_value=sb):
        resolve_message_texts_by_wamids(["wamid.A"])
    assert "message_type" in sb.query.select_arg
