"""O clique tem que chegar ao bot como CLIQUE, não como texto.

Até aqui o parser transformava clique em texto puro e jogava fora o identificador
(meta_parser.py:138-151). Sem esse identificador não dá para distinguir um lead
que TOCOU no botão de um que DIGITOU a mesma frase — e é justamente essa
diferença que torna o bot determinístico.
"""
from app.webhook.meta_parser import parse_meta_webhook_payload
from app.webhook.parser import IncomingMessage


def _payload(mensagem: dict) -> dict:
    # `messaging_product` é obrigatório: o parser descarta o change sem ele.
    return {"entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "123"},
        "contacts": [{"wa_id": "5511999999999", "profile": {"name": "Fulano"}}],
        "messages": [{"from": "5511999999999", "id": "wamid.1",
                      "timestamp": "1700000000", **mensagem}],
    }}]}]}


def test_quick_reply_de_template_vira_clique_com_payload():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "button",
        "button": {"payload": "Quero comprar agora", "text": "Quero comprar agora"},
    }))
    assert len(msgs) == 1
    assert msgs[0].type == "button"
    assert msgs[0].text == "Quero comprar agora"
    assert msgs[0].metadata == {"payload": "Quero comprar agora", "title": "Quero comprar agora"}


def test_button_reply_interativo_vira_clique_com_id():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "button_reply",
                        "button_reply": {"id": "prazo_3m", "title": "Daqui a 3 meses"}},
    }))
    assert msgs[0].type == "button"
    assert msgs[0].metadata == {"payload": "prazo_3m", "title": "Daqui a 3 meses"}


def test_template_sem_payload_cai_no_texto_do_botao():
    """Defensivo: se a Meta omitir `payload`, o texto do botão serve de identidade."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "button", "button": {"text": "Não quero mais receber"},
    }))
    assert msgs[0].metadata["payload"] == "Não quero mais receber"


def test_list_reply_continua_texto():
    """Listas estão fora do escopo do bot — comportamento atual preservado."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "list_reply",
                        "list_reply": {"id": "x", "title": "Opção A"}},
    }))
    assert msgs[0].type == "text"
    assert msgs[0].text == "Opção A"


def test_texto_digitado_igual_ao_rotulo_nao_vira_clique():
    """A distinção que sustenta todo o determinismo do bot."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "text", "text": {"body": "Quero comprar agora"},
    }))
    assert msgs[0].type == "text"
    assert msgs[0].metadata is None


import base64
import json

from app.buffer.processor import _resolve_media


async def test_clique_atravessa_o_buffer_preservando_o_payload():
    """O buffer achata mensagens em TEXTO; metadados só sobrevivem via meta_b64.

    Mesmo mecanismo já usado por location/contact/reaction. Sem isto, o payload
    do botão morre entre o webhook e o processor.
    """
    meta = {"payload": "prazo_6m", "title": "Daqui a 6 meses"}
    b64 = base64.b64encode(json.dumps(meta).encode()).decode()

    # Assinatura real: _resolve_media(text, provider, lead_id=None, stage="")
    # → (resolved_text, media_url, message_type, document_name, metadata)
    texto, _url, tipo, _doc, metadata = await _resolve_media(
        f"[button: meta_b64={b64}]", None,
    )

    assert tipo == "button"
    assert metadata == meta
    # O texto visível no CRM é o título do botão — o vendedor precisa enxergar
    # no histórico o que o lead clicou.
    assert texto.strip() == "Daqui a 6 meses"


import logging
from unittest.mock import AsyncMock, patch

from app.buffer.manager import push_to_buffer


async def test_clique_sobrevive_a_midia_na_mesma_janela():
    """Foto + clique na mesma janela: a mídia não pode engolir o clique.

    Os laços de mídia rodam ANTES do laço de metadados e o de áudio reivindica
    `message_type` sem guarda. Se o clique dependesse de `message_type` estar livre,
    ele sumiria do texto E do metadata sem log nenhum — falha silenciosa justamente
    no sinal que sustenta o determinismo do bot. Por isso quem prova o clique é o
    `payload` no metadata; `message_type` fica com a mídia, que precisa dele (e da
    storage_url) para ser renderizada no CRM.
    """
    meta = {"payload": "prazo_6m", "title": "Daqui a 6 meses"}
    b64 = base64.b64encode(json.dumps(meta).encode()).decode()

    texto, url, tipo, _doc, metadata = await _resolve_media(
        f"[image: media_url=media-abc]\n[button: meta_b64={b64}]", None,
    )

    assert metadata == meta, "o clique tem que sobreviver à mídia da mesma janela"
    assert "Daqui a 6 meses" in texto
    assert tipo == "image", "a mídia mantém o próprio message_type"
    assert url == "media-abc", "e a própria storage_url"


async def test_clique_sem_titulo_nao_vira_mensagem_em_branco():
    """Sem título, o clique renderiza "[botão]" — nunca conteúdo vazio.

    Mensagem salva em branco vira "mensagem fantasma" no CRM: o vendedor vê uma
    linha sem nada e não sabe o que houve (mesma falha que a reação já trata).
    """
    b64 = base64.b64encode(json.dumps({"payload": "x"}).encode()).decode()

    texto, _url, tipo, _doc, metadata = await _resolve_media(f"[button: meta_b64={b64}]", None)

    assert texto.strip() == "[botão]"
    assert tipo == "button"
    assert metadata == {"payload": "x"}


async def test_segundo_clique_na_mesma_janela_e_descartado_com_log(caplog):
    """Dois cliques numa janela: o primeiro vence e o segundo deixa rastro no log.

    Só há um slot de metadata por turno. O descarte é aceitável; o descarte MUDO
    não é — sem log o suporte não consegue explicar o clique que o lead jura ter dado.
    """
    b1 = base64.b64encode(json.dumps({"payload": "prazo_1m", "title": "1 mês"}).encode()).decode()
    b2 = base64.b64encode(json.dumps({"payload": "prazo_3m", "title": "3 meses"}).encode()).decode()

    with caplog.at_level(logging.INFO, logger="app.buffer.processor"):
        texto, _url, tipo, _doc, metadata = await _resolve_media(
            f"[button: meta_b64={b1}]\n[button: meta_b64={b2}]", None,
        )

    assert metadata == {"payload": "prazo_1m", "title": "1 mês"}, "o primeiro clique vence"
    assert tipo == "button"
    assert "3 meses" not in texto
    logs = [r.getMessage() for r in caplog.records]
    assert any("2º marcador button" in m and "resolvido como button" in m for m in logs),         f"o descarte tem que deixar rastro no log; logs={logs}"


async def test_push_to_buffer_produz_o_marcador_que_o_processor_consome(fake_redis):
    """Fecha o contrato produtor→consumidor do clique (ponta a ponta).

    O teste acima monta o marcador na mão, então sozinho ele não cobre o produtor:
    tirar "button" de `_META_TYPES` no manager não quebrava nada, e o clique iria
    para o buffer como texto puro (sem payload). Aqui a string vem do próprio
    `push_to_buffer` e é devolvida ao `_resolve_media`.
    """
    msg = IncomingMessage(
        from_number="5511999999999",
        remote_jid="5511999999999@s.whatsapp.net",
        message_id="wamid.btn",
        timestamp="1700000000",
        type="button",
        text="Daqui a 6 meses",
        metadata={"payload": "prazo_6m", "title": "Daqui a 6 meses"},
        channel_id="chan-uuid",
    )
    await fake_redis.set("config:buffer_enabled", "1")

    with patch("app.buffer.manager.asyncio.create_task"), \
         patch.object(fake_redis, "exists", AsyncMock(return_value=0)):
        await push_to_buffer(fake_redis, msg)

    itens = await fake_redis.lrange("buffer:5511999999999:chan-uuid", 0, -1)
    esperado = base64.b64encode(
        json.dumps({"payload": "prazo_6m", "title": "Daqui a 6 meses"}).encode()
    ).decode()
    assert itens == [f"[button: meta_b64={esperado}]"], \
        "o clique precisa ir ao buffer como marcador meta_b64, não como texto puro"

    texto, _url, tipo, _doc, metadata = await _resolve_media(itens[0], None)
    assert tipo == "button"
    assert metadata == {"payload": "prazo_6m", "title": "Daqui a 6 meses"}
    assert texto.strip() == "Daqui a 6 meses"
