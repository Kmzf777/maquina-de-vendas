"""Transcrição de áudio: config de geração + contabilidade (FinOps 08/07/2026).

A transcrição era o único caminho LLM sem NENHUM generationConfig: thinking dinâmico
LIGADO por default (raciocínio pago para uma tarefa mecânica) e usageMetadata descartado
(gasto invisível ao token_usage/budget_guard). Desde a migração 09/07 (Gemini 100%
nativo), a chamada sai do REST httpx manual e passa pelo núcleo
`app.agent.gemini_client.transcribe_audio`. Cobre:

  1. A chamada nativa manda thinking_budget=0 e max_output_tokens (thinking off, saída
     limitada) — end-to-end por processor._transcribe_audio, com mime normalizado
     (";codecs=opus" removido).
  2. usage_metadata da resposta vira linha em token_usage (call_type=media_transcription),
     com lead_id encanado desde process_buffered_messages.
  3. Modelo default de transcrição roteado para gemini-2.5-flash-lite (mecânico e barato;
     revertível por env TRANSCRIPTION_MODEL sem deploy).
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.gemini_fakes import fake_usage


def _fake_sdk_resp(text="transcrição ok", prompt=250, candidates=40, thoughts=0, cached=0):
    """Resposta crua do SDK google-genai (shape mínimo p/ parse_result)."""
    return NS(
        candidates=[NS(finish_reason=NS(name="STOP"), content=NS(parts=[NS(text=text, function_call=None)]))],
        usage_metadata=NS(
            prompt_token_count=prompt,
            candidates_token_count=candidates,
            thoughts_token_count=thoughts,
            cached_content_token_count=cached,
        ),
    )


def _capture_genai_client(resp):
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_payload_desliga_thinking_e_limita_saida(monkeypatch):
    """A chamada nativa de transcrição DEVE ir com thinking off e teto de saída."""
    from app.buffer import processor
    from app.agent import gemini_client as GC
    from app.agent import token_tracker

    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: None)
    client = _capture_genai_client(_fake_sdk_resp())
    monkeypatch.setattr(GC, "get_genai_client", lambda v=None: client)

    out = await processor._transcribe_audio(b"OGGDATA", "audio/ogg; codecs=opus")
    assert out == "transcrição ok"

    kwargs = client.aio.models.generate_content.await_args.kwargs
    cfg = kwargs["config"]
    assert cfg.thinking_config is not None, "transcrição sem thinking_config — thinking dinâmico ligado"
    assert cfg.thinking_config.thinking_budget == 0
    assert (cfg.max_output_tokens or 0) > 0
    # mime normalizado: o parâmetro ";codecs=opus" do WhatsApp quebra o Gemini
    audio_part = kwargs["contents"][0].parts[1]
    assert audio_part.inline_data.mime_type == "audio/ogg"


@pytest.mark.asyncio
async def test_transcricao_rastreia_token_usage(monkeypatch):
    from app.buffer import processor
    from app.agent import token_tracker

    seen = {}
    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: seen.update(k))
    monkeypatch.setattr(
        processor, "transcribe_audio",
        AsyncMock(return_value=("transcrição ok", fake_usage(prompt=300, out=55, thoughts=7))),
    )

    await processor._transcribe_audio(b"OGGDATA", "audio/ogg", lead_id="L1", stage="secretaria")

    assert seen["call_type"] == "media_transcription"
    assert seen["lead_id"] == "L1"
    assert seen["stage"] == "secretaria"
    assert seen["prompt_tokens"] == 300
    # thinking é COBRADO como output → completion = visível + thoughts
    assert seen["completion_tokens"] == 62
    assert seen["reasoning_tokens"] == 7


@pytest.mark.asyncio
async def test_transcricao_sem_lead_nao_quebra_e_ainda_rastreia(monkeypatch):
    """Fail-soft: sem lead_id (caminho antigo/testes), transcreve normal e loga com lead nulo."""
    from app.buffer import processor
    from app.agent import token_tracker

    seen = {}
    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: seen.update(k))
    monkeypatch.setattr(
        processor, "transcribe_audio",
        AsyncMock(return_value=("transcrição ok", fake_usage())),
    )

    out = await processor._transcribe_audio(b"OGGDATA", "audio/ogg")
    assert out == "transcrição ok"
    assert seen["lead_id"] is None


def test_transcription_model_default_flash_lite():
    """Tarefa mecânica → flash-lite por default (3x mais barato no input, 6x no output).
    Override por env TRANSCRIPTION_MODEL continua valendo (sem deploy p/ reverter)."""
    from app.config import Settings
    field = Settings.model_fields["transcription_model"]
    assert field.default == "gemini-2.5-flash-lite"
