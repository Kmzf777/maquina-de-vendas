"""Legenda de mídia no histórico precisa carregar TIPO e AUTORIA.

Falha real 13/07 — lead 5564999289099 (private_label): a Valéria enviou 4 fotos com legenda
(enviar_fotos). No histórico lido pelo LLM, as legendas viraram texto nu no turno do MODEL
("Embalagem personalizada com sua marca", "Modelo de embalagem standup", ...). O lead voltou
34h depois só com "Oi" e o Gemini fechou a lacuna narrativa inventando autoria:
"recebi suas fotos aqui". O mesmo texto nu contaminou o rolling_summary, que passou a afirmar
que o lead "busca embalagem standup com silk de logo" — ele só tinha dito "Lançar do zero".

render_history_content é o ponto único: os DOIS get_history (conversations e leads) o aplicam,
então consertar aqui conserta o payload do orchestrator E o dossiê. describe_media_placeholder
segue CRU (sem envelope) porque o resolver de citação e a UI dependem da legenda literal.
"""
import pytest

from app.conversations.service import describe_media_placeholder, render_history_content


# --- (a) texto puro: intocado ------------------------------------------------

def test_texto_puro_passa_intacto():
    row = {"role": "assistant", "content": "boa noite", "message_type": None}
    assert render_history_content(row) == "boa noite"


def test_texto_puro_com_message_type_text_passa_intacto():
    row = {"role": "user", "content": "Lançar do zero", "message_type": "text"}
    assert render_history_content(row) == "Lançar do zero"


# --- (b) mídia SEM legenda: placeholder (comportamento atual preservado) ------

@pytest.mark.parametrize("mtype,esperado", [
    ("image", "[imagem]"),
    ("audio", "[áudio]"),
    ("video", "[vídeo]"),
    ("document", "[documento]"),
    ("sticker", "[figurinha]"),
])
def test_midia_sem_legenda_vira_placeholder(mtype, esperado):
    row = {"role": "user", "content": "", "message_type": mtype}
    assert render_history_content(row) == esperado
    assert describe_media_placeholder(row) == esperado  # contrato antigo preservado


def test_midia_sem_legenda_content_none():
    row = {"role": "assistant", "content": None, "message_type": "image"}
    assert render_history_content(row) == "[imagem]"


# --- (c) mídia COM legenda: envelope com tipo + autoria -----------------------

def test_foto_da_ia_com_legenda_vira_envelope_de_envio():
    """O caso exato do bug: legenda de foto enviada pela Valéria."""
    row = {"role": "assistant", "content": "Modelo de embalagem standup", "message_type": "image"}
    assert render_history_content(row) == '[Foto enviada por você: "Modelo de embalagem standup"]'


def test_foto_do_lead_com_legenda_vira_envelope_de_recebimento():
    row = {"role": "user", "content": "essa é a logo da minha marca", "message_type": "image"}
    assert render_history_content(row) == '[Foto recebida do lead: "essa é a logo da minha marca"]'


@pytest.mark.parametrize("mtype,rotulo", [
    ("image", "Foto"),
    ("video", "Vídeo"),
    ("document", "Documento"),
    ("sticker", "Figurinha"),
])
def test_rotulo_por_tipo_de_midia(mtype, rotulo):
    row = {"role": "assistant", "content": "x", "message_type": mtype}
    assert render_history_content(row).startswith(f"[{rotulo} enviad")


def test_audio_com_texto_e_transcricao_nao_legenda():
    """O content de áudio é a FALA transcrita — envelopar viraria metadado (regressão 10/07)."""
    row = {"role": "user", "content": "oi tudo bem", "message_type": "audio"}
    assert render_history_content(row) == "oi tudo bem"


def test_documento_do_lead_usa_o_nome_do_arquivo():
    row = {"role": "user", "content": "contrato.pdf", "message_type": "document"}
    assert render_history_content(row) == '[Documento recebido do lead: "contrato.pdf"]'


def test_role_desconhecido_nao_inventa_autoria():
    row = {"role": "system", "content": "Embalagem personalizada", "message_type": "image"}
    assert render_history_content(row) == '[Foto: "Embalagem personalizada"]'


# --- idempotência: marcadores já existentes não podem ser re-envelopados ------

def test_marcador_de_inbound_nao_e_reenvelopado():
    """_apply_media_signal (processor) já grava '[imagem]' quando o lead manda foto sem legenda."""
    row = {"role": "user", "content": "[imagem]", "message_type": "image"}
    assert render_history_content(row) == "[imagem]"


def test_audio_transcrito_preserva_o_marcador_do_pipeline():
    """O marcador [audio transcrito: ...] tem caso próprio no prompt (Caso 0) — não pode ser embrulhado."""
    row = {"role": "user", "content": "[audio transcrito: quero saber o preço]", "message_type": "audio"}
    assert render_history_content(row) == "[audio transcrito: quero saber o preço]"


def test_envelope_ja_aplicado_nao_duplica():
    row = {"role": "assistant", "content": '[Foto enviada por você: "x"]', "message_type": "image"}
    assert render_history_content(row) == '[Foto enviada por você: "x"]'


# --- integração: o payload do orchestrator herda o envelope -------------------

def test_render_history_content_do_orchestrator_herda_o_envelope():
    """_render_history_content lê o content JÁ renderizado pelo get_history — só confirma o passthrough."""
    from app.agent.orchestrator import _render_history_content

    row = {
        "role": "assistant",
        "content": '[Foto enviada por você: "Modelo de embalagem standup"]',
        "message_type": "image",
    }
    assert _render_history_content(row) == '[Foto enviada por você: "Modelo de embalagem standup"]'


def test_resolver_de_citacao_continua_lendo_a_legenda_crua():
    """describe_media_placeholder NAO envelopa: o marcador [Em resposta a: "..."] usa texto cru."""
    row = {"role": "assistant", "content": "Classico — torra media", "message_type": "image"}
    assert describe_media_placeholder(row) == "Classico — torra media"
