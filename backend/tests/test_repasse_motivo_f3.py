"""F3 (06/11/2026): motivo estruturado do repasse e a flag (desligada) que tira o
repasse por tempo/preço/amostra/automático do evento `qualificado` do CRM."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.leads import qualificado, repasse


@pytest.mark.parametrize("texto,codigo", [
    ("lead qualificado — atacado", "circuit_breaker"),            # circuit breaker antigo
    ("circuit breaker — atacado (6 turnos)", "circuit_breaker"),  # texto novo da F3
    ("private label — handoff por tempo", "circuit_breaker"),
    ("objecao de preco — handoff", "objecao_preco"),
    ("negociacao de preco/condicao — atacado", "objecao_preco"),
    ("private label — pediu amostra/degustacao", "kit_amostra"),
    ('clicou "Quero o kit"', "kit_amostra"),
    ("automático — parado há 5h em QA1", "automatico"),
    ("tabela indisponível (catálogo sem preço) — repasse automático", "automatico"),
    ("sem resposta a botões (2 mensagens não entendidas)", "ruido"),
    ("PERGUNTA: vocês emitem nota?", "pediu_vendedor"),
    ("VENDEDOR: quero falar com alguém", "pediu_vendedor"),
    ('clicou "Cafeteria"', "fim_dos_botoes"),
    ('escreveu "uns 300 pacotes"', "fim_dos_botoes"),
    ("lead com intencao de compra — atacado", "ia_qualificado"),
    ("handoff proativo — âncoras: finalidade=revenda / volume=50kg", "ia_qualificado"),
    ("private label qualificado", "ia_qualificado"),
    ("valeria_botoes_v2: lead pediu atendimento do vendedor", "outro"),
    ("", "outro"),
    (None, "outro"),
])
def test_classificar_motivo(texto, codigo):
    assert repasse.classificar_motivo(texto) == codigo


def _sb():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    return sb


@pytest.fixture
def gravar(monkeypatch):
    sb = _sb()
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    qualif = MagicMock(return_value=True)
    monkeypatch.setattr(qualificado, "registrar_qualificado", qualif)

    def _g(motivo, **kw):
        repasse.registrar_repasse(lead_id="L1", conversation_id="C1", message_id="M1",
                                  occurred_at=None, source=kw.pop("source", "ia"),
                                  motivo=motivo, **kw)
        return sb.table.return_value.insert.call_args.args[0]["metadata"], qualif
    return _g


def test_flag_desligada_tudo_continua_qualificando(gravar, monkeypatch):
    monkeypatch.delenv(repasse.FLAG_SO_REPASSE_QUALIFICADO, raising=False)
    meta, qualif = gravar("objecao de preco — handoff")
    assert meta["motivo_codigo"] == "objecao_preco"
    qualif.assert_called_once()


@pytest.mark.parametrize("motivo", ["objecao de preco — handoff", "circuit breaker — atacado",
                                    "automático — parado há 3h em VK"])
def test_flag_ligada_nao_qualifica_tempo_preco_amostra(gravar, monkeypatch, motivo):
    monkeypatch.setenv(repasse.FLAG_SO_REPASSE_QUALIFICADO, "on")
    meta, qualif = gravar(motivo)
    assert meta["motivo_codigo"] in repasse.MOTIVOS_NAO_QUALIFICADOS
    qualif.assert_not_called()


def test_flag_ligada_repasse_qualificado_continua(gravar, monkeypatch):
    monkeypatch.setenv(repasse.FLAG_SO_REPASSE_QUALIFICADO, "on")
    _, qualif = gravar('clicou "Cafeteria"')
    qualif.assert_called_once()


def test_codigo_do_runner_vence_o_texto_generico_dos_botoes(gravar):
    """effects.py manda sempre o mesmo texto; o runner põe o código no contexto."""
    with repasse.motivo_do_repasse("kit_amostra"):
        meta, _ = gravar("valeria_botoes_v2: lead pediu atendimento do vendedor",
                         source="button_flow")
    assert meta["motivo_codigo"] == "kit_amostra"
    meta, _ = gravar("valeria_botoes_v2: lead pediu atendimento do vendedor",
                     source="button_flow")
    assert meta["motivo_codigo"] == "outro", "fora do bloco o contexto volta ao normal"


def test_contexto_atravessa_to_thread(gravar):
    async def _turno():
        with repasse.motivo_do_repasse("automatico"):
            return await asyncio.to_thread(gravar, "texto qualquer", source="button_flow")
    meta, _ = asyncio.run(_turno())
    assert meta["motivo_codigo"] == "automatico"


def test_codigo_desconhecido_no_contexto_e_ignorado(gravar):
    with repasse.motivo_do_repasse("inventado"):
        meta, _ = gravar("objecao de preco — handoff")
    assert meta["motivo_codigo"] == "objecao_preco"


def test_registrar_desqualificado(monkeypatch):
    sb = _sb()
    monkeypatch.setattr(qualificado, "get_supabase", lambda: sb)
    assert qualificado.registrar_desqualificado(
        lead_id="L1", motivo="sem_cnpj", no="QA_CNPJ", source="button_flow",
        conversation_id="C1", ramo="atacado") is True
    ev = sb.table.return_value.insert.call_args.args[0]
    assert ev["event_type"] == "desqualificado" and ev["new_value"] == "sem_cnpj"
    assert ev["metadata"] == {"motivo": "sem_cnpj", "no": "QA_CNPJ", "ramo": "atacado",
                              "conversation_id": "C1"}
    assert ev["dedupe_key"] == "desqualificado:L1:sem_cnpj:QA_CNPJ"


def test_desqualificado_motivo_fora_do_vocabulario_nao_grava(monkeypatch):
    sb = _sb()
    monkeypatch.setattr(qualificado, "get_supabase", lambda: sb)
    assert qualificado.registrar_desqualificado(lead_id="L1", motivo="preguiça", no="X",
                                                source="t") is False
    sb.table.assert_not_called()
