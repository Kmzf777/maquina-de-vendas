"""Hotfix 09/07 ~15:15 BRT: Google desligou a geração dos gemini-2.5-flash e
gemini-2.5-flash-lite (404 "no longer available") NO MEIO de um run de disparo.

Smoke tests reais na chave de produção validaram os sucessores:
  - gemini-3.5-flash: texto + function calling + reasoning_effort="none" OK
  - gemini-3.1-flash-lite: JSON mode + reasoning_effort="none" OK

Estes testes pinam (a) os defaults novos e (b) o gate de thinking-off cobrindo a
família 3.x — sem isso o 3.5-flash pensa por padrão e queima o budget de saída
(mesma assinatura do bug da Carla: resposta vazia com finish_reason=length).
"""
from app.agent.orchestrator import DEFAULT_MODEL, _gemini_thinking_off
from app.agent import memory_manager as MM
from app.follow_up import scheduler as SCH
from app.config import settings


def test_default_models_sao_da_familia_viva():
    assert DEFAULT_MODEL == "gemini-3.5-flash"
    assert SCH._FOLLOWUP_MODEL == "gemini-3.5-flash"
    assert settings.memory_model == "gemini-3.1-flash-lite"
    assert settings.transcription_model == "gemini-3.1-flash-lite"


def test_thinking_off_cobre_familia_3x():
    # flash/lite (2.5 legado e 3.x atuais) → thinking OFF
    for m in ("gemini-2.5-flash", "gemini-2.5-flash-lite",
              "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview"):
        assert _gemini_thinking_off(m) == {"reasoning_effort": "none"}, m
        assert MM._gemini_thinking_off(m) == {"reasoning_effort": "none"}, m
    # pro pensa (não desligar)
    for m in ("gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-pro-latest"):
        assert _gemini_thinking_off(m) == {}, m
        assert MM._gemini_thinking_off(m) == {}, m
    # não-Gemini intocado
    assert _gemini_thinking_off("gpt-4o") == {}
