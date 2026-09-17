"""Fiação da guarda `normalize_proper_nouns` nos caminhos de saída (2026-09-17).

Arquivo IRMÃO de test_proper_nouns_2026_09_17.py (que já tem 465 linhas e cobre
só a função PURA): aqui o alvo é outro — os pontos de ENTREGA onde a guarda foi
ligada. São dois caminhos independentes:

1. `orchestrator._sanitize_assistant_text` — o funil por onde passa TODA a saída
   textual do run_agent (7 call sites). A guarda entra como ÚLTIMO passo, depois
   de `normalize_orthography`.
2. `tools.py` — a despedida do handoff/descarte NÃO passa pelo funil acima: as
   tools mandam o texto do LLM direto pro cliente. Dois pontos:
   `_send_despedida_descarte` e o executor de `encaminhar_humano`.

O caso de produção que motivou o ponto 2: "perfeito, eliatan, o joao bras que te
ajuda" — a despedida é justamente a mensagem que FECHA a conversa e NOMEIA o
vendedor, e saía com os dois nomes achatados.
"""
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from app.agent import tools as T
from app.agent.orchestrator import _sanitize_assistant_text


# ---------------------------------------------------------------------------
# 1. orchestrator._sanitize_assistant_text
# ---------------------------------------------------------------------------

def test_sanitize_capitaliza_lexico():
    """A saudação de abertura (340x em 90 dias) sai corrigida pelo funil."""
    out = _sanitize_assistant_text(
        "aqui é a valeria, do comercial da café canastra",
        "conv-1", "secretaria", source="initial",
    )
    assert out == "aqui é a Valéria, do comercial da Café Canastra"


def test_sanitize_com_lead_name_capitaliza_o_nome_do_lead():
    """Camada C só age quando o funil REPASSA o nome do lead."""
    out = _sanitize_assistant_text(
        "boa tarde, eliatan\n\nvou te passar pro joao bras",
        "conv-1", "atacado", source="initial", lead_name="Eliatan",
    )
    assert out == "boa tarde, Eliatan\n\nvou te passar pro João Brás"


def test_sanitize_sem_lead_name_nao_quebra_e_deixa_o_nome_intacto():
    """Os call sites que não passam `lead_name` seguem funcionando (default None).

    O nome do lead não é do léxico, então sem `lead_name` ele fica como veio —
    é o discriminador de que o parâmetro está sendo REALMENTE usado no teste
    acima, e não um acaso do léxico fixo.
    """
    out = _sanitize_assistant_text(
        "boa tarde, eliatan\n\nvou te passar pro joao bras",
        "conv-1", "atacado", source="initial",
    )
    assert out == "boa tarde, eliatan\n\nvou te passar pro João Brás"


def test_sanitize_nao_desfaz_a_acentuacao_da_ortografia():
    """Ordem: a guarda entra DEPOIS de `normalize_orthography`, não no lugar dela.

    "cafe" -> "café" e "graos" -> "grãos" são da ortografia; "suave" -> "Suave"
    (Camada B, porta de contexto "determinante + café" + formato adjacente) é da
    guarda nova. As DUAS correções têm que sobreviver na saída final — se o passo
    novo rodasse por cima apagando a acentuação (ou se a ortografia fosse
    derrubada), este assert quebra.
    """
    out = _sanitize_assistant_text(
        "o cafe suave em graos", "conv-1", "consumo", source="initial",
    )
    assert out == "o café Suave em grãos"


# ---------------------------------------------------------------------------
# 2. tools.py — a despedida não passa pelo funil do orchestrator
# ---------------------------------------------------------------------------

def _channel():
    return {
        "id": "ch-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    }


def _capturing_provider(sent: list[str]):
    async def _send(to, body):
        sent.append(body)
        return {"messages": [{"id": "wamid.BYE1"}]}

    provider = AsyncMock()
    provider.send_text = AsyncMock(side_effect=_send)
    return provider


# "vanda" NÃO está no léxico fixo — só a Camada C (nome do lead) capitaliza. Serve
# de discriminador de que o `lead_name` está sendo repassado nos dois sites.
_DESPEDIDA_CRUA = "tranquilo, vanda\n\nqualquer coisa é só chamar a valeria da cafe canastra"
_DESPEDIDA_ESPERADA = (
    "tranquilo, Vanda\n\nqualquer coisa é só chamar a Valéria da Café Canastra"
)


@pytest.mark.asyncio
async def test_despedida_do_descarte_sai_com_nomes_proprios_corrigidos():
    """_send_despedida_descarte (tools.py) normaliza antes de enviar e de persistir."""
    sent: list[str] = []
    provider = _capturing_provider(sent)
    patches = [
        patch.object(T, "update_lead", return_value={}),
        patch.object(
            T, "get_lead",
            return_value={"id": "lead-1", "name": "Vanda", "phone": "+551199", "metadata": {}},
        ),
        patch.object(T, "lead_has_active_relationship", return_value=False),
        patch.object(T, "move_lead_deals_to_perdido"),
        patch.object(T, "cancel_followups_by_phone"),
        patch.object(T, "append_lead_observation"),
        patch.object(T, "get_channel_for_lead", return_value=_channel()),
        patch.object(T, "get_provider", return_value=provider),
        patch.object(T, "resolve_send_target", side_effect=lambda lead, phone: phone),
        patch.object(T, "_despedida_ja_enviada", return_value=False),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        mock_save = stack.enter_context(patch.object(T, "save_message"))
        await T.execute_tool(
            "registrar_sem_interesse_atual",
            {
                "motivo": "lead reafirmou que nao tem interesse, achou caro",
                "mensagem_despedida": _DESPEDIDA_CRUA,
            },
            "lead-1", "+551199", "conv-1",
        )

    assert sent == [_DESPEDIDA_ESPERADA]
    # A bolha persistida é a MESMA que o cliente recebeu (senão o histórico e o
    # dedup do próximo turno divergem do que foi enviado).
    assistant_saves = [c for c in mock_save.call_args_list if c.args[1] == "assistant"]
    assert [c.args[2] for c in assistant_saves] == [_DESPEDIDA_ESPERADA]


@pytest.mark.asyncio
async def test_despedida_do_handoff_sai_com_nomes_proprios_corrigidos(monkeypatch):
    """encaminhar_humano (tools.py): o caso real "perfeito, eliatan, o joao bras"."""
    sent: list[str] = []
    provider = _capturing_provider(sent)

    monkeypatch.setattr(
        "app.agent.tools.get_lead",
        lambda lead_id: {"id": "lead-1", "name": "Eliatan", "stage": "atacado"},
    )
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "d-1"})
    monkeypatch.setattr("app.agent.tools.move_deal_to_vendor_pipeline", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.tools.move_open_deal_for_handoff", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: _channel())
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)
    monkeypatch.setattr("app.agent.tools._despedida_ja_enviada", lambda *a, **k: False)

    with patch.object(T, "save_message") as mock_save:
        await T.execute_tool(
            "encaminhar_humano",
            {
                "vendedor": "João Brás",
                "motivo": "qualificado",
                "mensagem_despedida": "eliatan, o joao bras assume daqui — ele é da cafe canastra",
            },
            lead_id="lead-1", phone="5511999999999", conversation_id="conv-1",
        )

    esperada = "Eliatan, o João Brás assume daqui — ele é da Café Canastra"
    assert sent == [esperada]
    assistant_saves = [c for c in mock_save.call_args_list if c.args[1] == "assistant"]
    assert [c.args[2] for c in assistant_saves] == [esperada]
