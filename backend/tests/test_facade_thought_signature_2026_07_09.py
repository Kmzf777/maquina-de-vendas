"""Incidente 09/07 16:00-17:50 BRT (era gemini-3.5-flash do falso-sunset): TODA
conversa com tool quebrava na 2ª chamada com 400 INVALID_ARGUMENT "Function call is
missing a thought_signature in functionCall parts" — repro determinístico no
container de produção (2.5 passa, 3.5 falha). O retry re-executava a tool a cada
tentativa (4x mudar_stage no caso Tiago) e esgotava em handoff cego.

Causa: a família Gemini 3 EXIGE o eco do thought_signature devolvido junto com o
function_call; a fachada perdia a assinatura no round-trip
_parse_response → model_dump → _convert_messages.

Correção: passthrough — captura a assinatura do part nativo, serializa em base64 no
dict do tool_call e a re-anexa ao types.Part na reconstrução. Sem assinatura
(família 2.5), nada muda.
"""
import base64
from types import SimpleNamespace as NS

from app.agent.gemini_native import _parse_response, _convert_messages


def _fake_resp(with_sig: bool):
    fc = NS(name="salvar_nome", args={"nome": "Carlos"})
    part = NS(text=None, function_call=fc,
              thought_signature=(b"assinatura-opaca" if with_sig else None))
    cand = NS(finish_reason=NS(name="STOP"), content=NS(parts=[part]))
    return NS(candidates=[cand], usage_metadata=None)


def test_parse_captura_thought_signature_em_base64():
    resp = _parse_response(_fake_resp(with_sig=True))
    tc = resp.choices[0].message.tool_calls[0]
    assert tc.thought_signature == base64.b64encode(b"assinatura-opaca").decode()


def test_model_dump_carrega_assinatura_no_tool_call():
    msg = _parse_response(_fake_resp(with_sig=True)).choices[0].message
    dumped = msg.model_dump(exclude_none=True)
    assert dumped["tool_calls"][0]["thought_signature"] == \
        base64.b64encode(b"assinatura-opaca").decode()


def test_convert_reanexa_assinatura_no_part_nativo():
    msg = _parse_response(_fake_resp(with_sig=True)).choices[0].message
    history = [
        {"role": "user", "content": "meu nome é Carlos"},
        msg.model_dump(exclude_none=True),
        {"role": "tool", "tool_call_id": msg.tool_calls[0].id, "content": "Nome salvo."},
    ]
    _system, contents = _convert_messages(history)
    model_turn = next(c for c in contents if c.role == "model")
    fc_part = next(p for p in model_turn.parts if getattr(p, "function_call", None))
    assert fc_part.thought_signature == b"assinatura-opaca"


def test_sem_assinatura_round_trip_inalterado():
    """Família 2.5 (sem signature): dump sem a chave, part sem assinatura."""
    msg = _parse_response(_fake_resp(with_sig=False)).choices[0].message
    dumped = msg.model_dump(exclude_none=True)
    assert "thought_signature" not in dumped["tool_calls"][0]
    history = [{"role": "user", "content": "oi"}, dumped,
               {"role": "tool", "tool_call_id": msg.tool_calls[0].id, "content": "ok"}]
    _s, contents = _convert_messages(history)
    model_turn = next(c for c in contents if c.role == "model")
    fc_part = next(p for p in model_turn.parts if getattr(p, "function_call", None))
    assert not getattr(fc_part, "thought_signature", None)
