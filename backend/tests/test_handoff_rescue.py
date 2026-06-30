"""Tests for handoff rescue: schedule_handoff_rescue and _process_handoff_rescue."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from zoneinfo import ZoneInfo
import pytest

SP_TZ = ZoneInfo("America/Sao_Paulo")


# ─── _clamp_to_business_window ──────────────────────────────────────────────

def test_clamp_to_business_window_keeps_target_inside_window_on_weekday():
    """Segunda-feira 12:00 local (dentro de [09:00,16:00)) -> inalterado."""
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 5, 25, 12, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    result = _clamp_to_business_window(target)

    assert result == target


def test_clamp_to_business_window_moves_to_same_day_09h_when_before_window():
    """Segunda-feira 07:30 local (antes de 09:00) -> mesmo dia 09:00 local."""
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 5, 25, 7, 30, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 5, 25, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    result = _clamp_to_business_window(target)

    assert result == expected


def test_clamp_to_business_window_moves_to_next_day_09h_when_after_window():
    """Segunda-feira 17:00 local (>= 16:00) -> dia seguinte (terca) 09:00 local."""
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 5, 25, 17, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 5, 26, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    result = _clamp_to_business_window(target)

    assert result == expected
    assert result.astimezone(SP_TZ).weekday() == 1  # terca-feira (dia util)


def test_clamp_to_business_window_friday_after_16h_moves_to_monday_09h():
    """Sexta-feira 18:00 local (>= 16:00) -> segunda-feira seguinte 09:00 local."""
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 5, 22, 18, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 5, 25, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    result = _clamp_to_business_window(target)

    assert result == expected
    assert result.astimezone(SP_TZ).weekday() == 0  # segunda-feira


def test_clamp_to_business_window_saturday_moves_to_monday_09h():
    """Sabado 10:00 local (fim de semana) -> segunda-feira seguinte 09:00 local."""
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 5, 23, 10, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 5, 25, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    result = _clamp_to_business_window(target)

    assert result == expected
    assert result.astimezone(SP_TZ).weekday() == 0  # segunda-feira


# ─── _build_joao_handoff_components (params NOMEADOS do template aprovado) ───

def test_build_joao_handoff_components_uses_two_named_params():
    """O template automacao_valeria_to_joao usa 2 params NOMEADOS na Meta
    (nome_do_lead, nome_do_vendedor). O builder deve emitir exatamente esses,
    com o primeiro nome do lead e o vendedor (default João)."""
    from app.follow_up.scheduler import _build_joao_handoff_components

    components = _build_joao_handoff_components("Elisangele Accordi")

    assert components == [{
        "type": "body",
        "parameters": [
            {"type": "text", "parameter_name": "nome_do_lead", "text": "Elisangele"},
            {"type": "text", "parameter_name": "nome_do_vendedor", "text": "João"},
        ],
    }]


def test_build_joao_handoff_components_accepts_custom_vendedor():
    from app.follow_up.scheduler import _build_joao_handoff_components
    components = _build_joao_handoff_components("Maria Silva", vendedor="Arthur")
    params = components[0]["parameters"]
    assert params[0] == {"type": "text", "parameter_name": "nome_do_lead", "text": "Maria"}
    assert params[1] == {"type": "text", "parameter_name": "nome_do_vendedor", "text": "Arthur"}


# ─── _render_joao_handoff_text (texto do template para persistir no histórico) ─

def test_render_joao_handoff_text_fills_named_params():
    from app.follow_up.scheduler import _render_joao_handoff_text
    txt = _render_joao_handoff_text("Elisangele Accordi")
    assert txt.startswith("Olá, Elisangele!")
    assert "Sou o João" in txt
    # Sem placeholders não-resolvidos
    assert "{{" not in txt and "{nome" not in txt


# ─── _process_handoff_rescue PERSISTE a mensagem do template ─────────────────

@pytest.mark.asyncio
async def test_handoff_rescue_persists_template_message_in_joao_conversation():
    """Após enviar o template, a mensagem DEVE ser salva na conversa do canal do João
    (com wamid), senão o histórico no frontend mostra só a resposta do lead."""
    job = _make_rescue_job()  # lead "Pedro Souza"
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.789"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler.get_or_create_conversation", return_value={"id": "conv-joao-1"}) as mock_goc, \
         patch("app.follow_up.scheduler.save_message_conv") as mock_save, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    # Conversa do canal do João é criada/reaproveitada para o lead
    mock_goc.assert_called_once_with("lead-1", "ch-joao-1")
    # Mensagem do template persistida na conversa do João via conversations.service
    # (save_message_conv), que atualiza last_msg_at e zera unread_count automaticamente.
    assert mock_save.call_count == 1
    _, kwargs = mock_save.call_args
    assert kwargs["conversation_id"] == "conv-joao-1"
    assert kwargs["wamid"] == "wamid.789"
    assert kwargs["role"] == "assistant"
    assert kwargs["content"].startswith("Olá, Pedro!")
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


# ─── schedule_handoff_rescue ────────────────────────────────────────────────

def test_schedule_handoff_rescue_inserts_job_with_correct_fields():
    """Insere job com job_type='handoff_rescue', sequence=1, fire_at=now+15min.

    now = 2026-05-25 15:00 UTC = segunda-feira 12:00 America/Sao_Paulo,
    dentro da janela comercial [09:00,16:00) — fire_at (+15min) permanece
    dentro da janela e nao e clampado (ver _clamp_to_business_window).
    """
    from app.follow_up.service import schedule_handoff_rescue

    inserted = []
    mock_insert = MagicMock()
    mock_insert.return_value.execute.side_effect = lambda: inserted.append(
        mock_insert.call_args[0][0]
    ) or MagicMock()

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now = datetime(2026, 5, 25, 15, 0, 0, tzinfo=timezone.utc)

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        schedule_handoff_rescue(
            lead_id="lead-1",
            lead_phone="5511999999999",
            conversation_id="conv-1",
            channel_id="ch-1",
        )

    assert len(inserted) == 1
    job = inserted[0]
    assert job["job_type"] == "handoff_rescue"
    assert job["sequence"] == 1
    assert job["status"] == "pending"
    assert job["lead_id"] == "lead-1"
    assert job["conversation_id"] == "conv-1"
    assert job["channel_id"] == "ch-1"
    assert job["metadata"]["lead_phone"] == "5511999999999"
    assert job["metadata"]["joao_phone_number_id"] == "1049315514934778"
    assert job["metadata"]["template_name"] == "automacao_valeria_to_joao"

    fire_at = datetime.fromisoformat(job["fire_at"])
    expected = now + timedelta(minutes=15)
    assert abs((fire_at - expected).total_seconds()) < 2


def test_schedule_handoff_rescue_uses_approved_en_locale():
    """Bug raiz do 404 #132001: metadata.language_code deve ser o locale APROVADO.

    Auditoria 2026-06-16 (message_templates): 'automacao_valeria_to_joao' existe SÓ em
    `en` (corpo é PT, locale Meta é `en`). pt_BR não existe → 404. Logo, o locale correto
    é `en`.
    """
    from app.follow_up.service import schedule_handoff_rescue

    inserted = []
    mock_insert = MagicMock()
    mock_insert.return_value.execute.side_effect = lambda: inserted.append(
        mock_insert.call_args[0][0]
    ) or MagicMock()

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now = datetime(2026, 5, 25, 15, 0, 0, tzinfo=timezone.utc)

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        schedule_handoff_rescue(
            lead_id="lead-1",
            lead_phone="5511999999999",
            conversation_id="conv-1",
            channel_id="ch-1",
        )

    assert len(inserted) == 1
    job = inserted[0]
    assert job["metadata"]["language_code"] == "en"


def test_schedule_handoff_rescue_raises_on_db_error():
    """Erro no insert é propagado como RuntimeError."""
    from app.follow_up.service import schedule_handoff_rescue

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception("db down")

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb):
        with pytest.raises(RuntimeError, match="Falha ao agendar"):
            schedule_handoff_rescue(
                lead_id="lead-1",
                lead_phone="5511999999999",
                conversation_id="conv-1",
                channel_id="ch-1",
            )


# ─── _process_handoff_rescue (via process_due_followups) ────────────────────

def _make_rescue_job():
    return {
        "id": "job-rescue-1",
        "conversation_id": "conv-ai-1",
        "lead_id": "lead-1",
        "channel_id": "ch-ai-1",
        "sequence": 1,
        "job_type": "handoff_rescue",
        "leads": {
            "id": "lead-1",
            "phone": "5511999999999",
            "name": "Pedro Souza",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-ai-1",
            "name": "Canal IA",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "111", "access_token": "tok"},
            "mode": "ai",
        },
        "conversations": {"id": "conv-ai-1", "stage": "atacado", "followup_enabled": True},
        "metadata": {
            "lead_phone": "5511999999999",
            "joao_phone_number_id": "1049315514934778",
            "template_name": "rabubens",
        },
    }


@pytest.mark.asyncio
async def test_handoff_rescue_sends_template_when_lead_has_not_contacted_joao():
    """Lead sem nenhuma conversa com canal do João → dispara template rabubens."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    # No conversations between lead and João's channel
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.456"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler.get_or_create_conversation", return_value={"id": "conv-joao-1"}), \
         patch("app.follow_up.scheduler.save_message_conv"), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    # Locale aprovado é `en` (automacao_valeria_to_joao só existe em `en`; pt_BR → 404).
    # Componentes usam os 2 params NOMEADOS do template aprovado (nome_do_lead/nome_do_vendedor).
    mock_meta.send_template.assert_called_once_with(
        "5511999999999", "rabubens",
        components=[{
            "type": "body",
            "parameters": [
                {"type": "text", "parameter_name": "nome_do_lead", "text": "Pedro"},
                {"type": "text", "parameter_name": "nome_do_vendedor", "text": "João"},
            ],
        }],
        language_code="en",
    )
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_skips_template_when_lead_already_replied_to_joao():
    """Lead que já enviou msg para João nos últimos 15 min → sem template, job marcado sent."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    conv_result = MagicMock()
    conv_result.data = [{"id": "conv-joao-1"}]
    msg_result = MagicMock()
    msg_result.data = [{"id": "msg-user-1"}]

    def _table(name):
        tbl = MagicMock()
        if name == "conversations":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = conv_result
        elif name == "messages":
            tbl.select.return_value.in_.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = msg_result
        return tbl

    mock_sb.table.side_effect = _table
    mock_meta = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_meta.send_template.assert_not_called()
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_cancels_when_joao_channel_not_found():
    """Canal do João inexistente → job cancelado com razão joao_channel_not_found."""
    job = _make_rescue_job()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=None), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_cancel.assert_called_once_with("job-rescue-1", "joao_channel_not_found")
    mock_sent.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_does_not_mark_sent_if_template_send_fails():
    """Falha no send_template → job NÃO é marcado sent (será retentado no próximo tick)."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(side_effect=RuntimeError("Meta API error"))

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_sent.assert_not_called()
    mock_cancel.assert_not_called()


def test_schedule_handoff_rescue_skipped_in_rehearsal_mode(monkeypatch):
    """REHEARSAL_MODE=true deve impedir que o rescue job seja inserido."""
    from app.follow_up.service import schedule_handoff_rescue

    monkeypatch.setenv("REHEARSAL_MODE", "true")
    mock_sb = MagicMock()

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb):
        schedule_handoff_rescue(
            lead_id="lead-r",
            lead_phone="5511000000001",
            conversation_id="conv-r",
            channel_id="chan-r",
        )

    mock_sb.table.return_value.insert.assert_not_called()


@pytest.mark.asyncio
async def test_standard_jobs_not_affected_by_handoff_rescue_routing():
    """Jobs job_type='standard' continuam sendo processados pelo caminho existente."""
    standard_job = {
        "id": "job-std-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "job_type": "standard",
        "leads": {
            "id": "lead-1",
            "phone": "5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-1",
            "mode": "ai",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "111", "access_token": "tok"},
        },
        "conversations": {
            "id": "conv-1",
            "stage": "atacado",
            "followup_enabled": True,
            # Janela por canal: guard de 24h lê a conversa, não o lead global.
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "metadata": {},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[standard_job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.get_provider", return_value=mock_provider), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value=("Oi, tudo bem?", "stop")), \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_provider.send_text.assert_called_once()
    mock_sent.assert_called_once_with("job-std-1")
    mock_cancel.assert_not_called()
