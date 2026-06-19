"""Tests for the dispatch observation (OBS) recorded on CRM cards.

Feature: ao disparar um template (broadcast/campanha/outbound) o sistema anexa
uma observação no card de CRM no formato fixo:
    "[DATA] - Disparo feito usando o template {nome_do_template}"
"""

import re
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.leads.service import (
    DISPATCH_NOTE_AUTHOR,
    format_dispatch_note,
    record_dispatch_note,
)

_TZ_BR = timezone(timedelta(hours=-3))


# ── format_dispatch_note (puro) ─────────────────────────────────────────────

class TestFormatDispatchNote:
    def test_exact_format_with_fixed_timestamp(self):
        when = datetime(2026, 6, 18, 9, 30, tzinfo=_TZ_BR)
        note = format_dispatch_note("reativacao_atacado", when=when)
        assert note == "[18/06/2026 09:30] - Disparo feito usando o template reativacao_atacado"

    def test_template_name_is_embedded_verbatim(self):
        when = datetime(2026, 1, 5, 14, 0, tzinfo=_TZ_BR)
        note = format_dispatch_note("oferta_natal", when=when)
        assert "Disparo feito usando o template oferta_natal" in note

    def test_timestamp_rendered_in_brt(self):
        # 12:00 UTC → 09:00 BRT
        when_utc = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        note = format_dispatch_note("qualquer", when=when_utc)
        assert note.startswith("[18/06/2026 09:00]")

    def test_matches_strict_pattern_when_using_now(self):
        note = format_dispatch_note("meu_template")
        assert re.match(
            r"^\[\d{2}/\d{2}/\d{4} \d{2}:\d{2}\] - Disparo feito usando o template meu_template$",
            note,
        )


# ── record_dispatch_note (DB, fail-soft) ────────────────────────────────────

class TestRecordDispatchNote:
    def test_inserts_into_lead_notes_with_correct_payload(self):
        sb = MagicMock()
        when = datetime(2026, 6, 18, 9, 30, tzinfo=_TZ_BR)
        with patch("app.leads.service.get_supabase", return_value=sb):
            record_dispatch_note("lead-1", "reativacao_atacado", when=when)

        sb.table.assert_called_once_with("lead_notes")
        payload = sb.table.return_value.insert.call_args[0][0]
        assert payload["lead_id"] == "lead-1"
        assert payload["author"] == DISPATCH_NOTE_AUTHOR
        assert payload["content"] == (
            "[18/06/2026 09:30] - Disparo feito usando o template reativacao_atacado"
        )
        sb.table.return_value.insert.return_value.execute.assert_called_once()

    def test_noop_when_lead_id_missing(self):
        sb = MagicMock()
        with patch("app.leads.service.get_supabase", return_value=sb):
            record_dispatch_note("", "algum_template")
        sb.table.assert_not_called()

    def test_noop_when_template_name_missing(self):
        sb = MagicMock()
        with patch("app.leads.service.get_supabase", return_value=sb):
            record_dispatch_note("lead-1", "")
        sb.table.assert_not_called()

    def test_fail_soft_never_raises_on_db_error(self):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("boom")
        with patch("app.leads.service.get_supabase", return_value=sb):
            # Não deve levantar — perder a OBS não pode derrubar o disparo.
            record_dispatch_note("lead-1", "algum_template")


# ── integração: cada caminho de disparo chama record_dispatch_note ──────────

class TestDispatchSitesRecordNote:
    @pytest.mark.asyncio
    async def test_outbound_records_note_after_send(self):
        import app.outbound.dispatcher as dispatcher

        provider = MagicMock()

        async def _send_text(phone, text):
            return {"messages": [{"id": "wamid.x"}]}

        provider.send_text = _send_text

        with patch.object(dispatcher, "get_channel_by_id", return_value={"id": "ch1"}), \
             patch.object(dispatcher, "get_provider", return_value=provider), \
             patch.object(dispatcher, "get_or_create_lead", return_value={"id": "lead-1"}), \
             patch.object(dispatcher, "update_lead"), \
             patch.object(dispatcher, "get_or_create_conversation", return_value={"id": "conv1"}), \
             patch.object(dispatcher, "update_conversation"), \
             patch.object(dispatcher, "save_message"), \
             patch.object(dispatcher, "record_dispatch_note") as mock_record:
            await dispatcher.dispatch_to_lead("+5511999999999", {"channel_id": "ch1"})

        mock_record.assert_called_once_with("lead-1", dispatcher.OUTBOUND_TEMPLATE_NAME)
