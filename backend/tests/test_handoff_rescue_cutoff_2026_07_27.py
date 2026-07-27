"""Janela de checagem do handoff_rescue: "desde o handoff", não "últimos 15 min" (27/07/2026).

`_process_handoff_rescue` pulava o envio quando o lead já tinha procurado o João — mas
olhava só os últimos 15 minutos (`cutoff = now - 15min`). Isso só equivale a "desde o
handoff" no caso feliz, em que o job dispara 15 min depois dele.

Quebra em dois casos reais:

  * `_clamp_to_rescue_window`: handoff às 21h de sexta agenda o resgate para segunda 09h.
    A checagem cobre segunda 08:45-09:00 — um lead que escreveu ao João no sábado recebe
    o template mesmo assim.
  * Reagendamento em lote (recovery de 27/07, 178 jobs para 28/07 09:00): a checagem cobre
    08:45-09:00 e ignora dias inteiros de conversa com o João.

Referência correta: `metadata.original_handoff_at` quando existir (gravado pelo script de
recovery), senão `job.created_at` — que no fluxo normal é o próprio instante do handoff.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.follow_up import scheduler as S


_NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)  # 28/07 09:00 BRT


def _job(**over) -> dict:
    job = {
        "id": "job-1",
        "job_type": "handoff_rescue",
        "lead_id": "lead-1",
        "conversation_id": "conv-val",
        "created_at": "2026-07-23T15:00:00+00:00",   # handoff 5 dias antes do fire
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Ana"},
        "metadata": {"lead_phone": "5511999999999", "lead_name": "Ana"},
    }
    job.update(over)
    return job


def test_cutoff_usa_original_handoff_at_quando_presente():
    job = _job(metadata={"lead_phone": "5511", "original_handoff_at": "2026-07-23T15:00:00+00:00"})
    assert S._rescue_contact_cutoff(job, _NOW) == "2026-07-23T15:00:00+00:00"


def test_cutoff_cai_para_created_at():
    assert S._rescue_contact_cutoff(_job(), _NOW) == "2026-07-23T15:00:00+00:00"


def test_cutoff_ultimo_recurso_15min():
    """Sem nenhuma referência (job legado/malformado), mantém o comportamento antigo."""
    job = _job(created_at=None)
    assert S._rescue_contact_cutoff(job, _NOW) == (_NOW - timedelta(minutes=15)).isoformat()


def test_cutoff_ignora_referencia_futura():
    """Referência posterior ao `now` tornaria a janela vazia e o guard inútil."""
    job = _job(created_at="2026-07-29T00:00:00+00:00")
    assert S._rescue_contact_cutoff(job, _NOW) == (_NOW - timedelta(minutes=15)).isoformat()


def test_cutoff_referencia_invalida_nao_quebra():
    job = _job(created_at="nao-e-uma-data")
    assert S._rescue_contact_cutoff(job, _NOW) == (_NOW - timedelta(minutes=15)).isoformat()


def _run_rescue(job, inbound_rows):
    """Executa _process_handoff_rescue com o supabase mockado; devolve (cutoff_usado, enviou)."""
    captured = {}

    def _fake_sb():
        sb = MagicMock()

        def table(name):
            t = MagicMock()
            if name == "conversations":
                t.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[{"id": "conv-joao"}])
            elif name == "messages":
                chain = t.select.return_value.in_.return_value.eq.return_value

                def gte(_field, value):
                    captured["cutoff"] = value
                    return MagicMock(limit=lambda n: MagicMock(
                        execute=lambda: MagicMock(data=inbound_rows)))
                chain.gte = gte
            return t

        sb.table.side_effect = table
        return sb

    provider = MagicMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid"}]})

    with patch.object(S, "get_supabase", _fake_sb), \
         patch.object(S, "get_channel_by_provider_config",
                      return_value={"id": "ch-joao", "provider_config": {}}), \
         patch.object(S, "MetaCloudClient", return_value=provider), \
         patch.object(S, "_mark_sent"), patch.object(S, "_cancel_job"), \
         patch.object(S, "resolve_send_target", return_value="5511999999999"), \
         patch.object(S, "_build_joao_handoff_components", return_value=[]):
        import asyncio
        asyncio.run(S._process_handoff_rescue(job, _NOW))

    return captured.get("cutoff"), provider.send_template.await_count == 1


def test_lote_reagendado_enxerga_conversa_de_dias_atras():
    """Caso do recovery de 27/07: lead falou com o João em 25/07; o resgate de 28/07 09:00
    NÃO pode disparar. Com a janela antiga (08:45-09:00) ele disparava."""
    job = _job(metadata={"lead_phone": "5511", "original_handoff_at": "2026-07-23T15:00:00+00:00"})
    cutoff, enviou = _run_rescue(job, inbound_rows=[{"id": "msg-de-25-07"}])
    assert cutoff == "2026-07-23T15:00:00+00:00"
    assert enviou is False


def test_sem_contato_desde_o_handoff_dispara():
    job = _job(metadata={"lead_phone": "5511", "original_handoff_at": "2026-07-23T15:00:00+00:00"})
    cutoff, enviou = _run_rescue(job, inbound_rows=[])
    assert cutoff == "2026-07-23T15:00:00+00:00"
    assert enviou is True
