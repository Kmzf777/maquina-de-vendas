"""Incidente Google 09/07 (15:15-17:40 BRT): o v1beta devolveu 404 "no longer
available" para gemini-2.5-flash(-lite) com mensagem ENGANOSA de sunset, no meio de
um run de disparo. O sunset REAL é 16/10/2026 (docs/deprecations). Após a
recuperação, revertido ao 2.5 por custo (3.5-flash é 5x input / 3.6x output).

Ficam validados na chave de produção, para a migração planejada ANTES de 16/10:
  - gemini-3.5-flash e gemini-3-flash-preview: texto + function calling + none OK
  - gemini-3.1-flash-lite: JSON mode + reasoning_effort="none" OK

Estes testes pinam (a) os defaults atuais (2.5 até a migração planejada) e (b) o
gate de thinking-off cobrindo TAMBÉM a família 3.x — sem isso, na migração, o 3.5
pensa por padrão e queima o budget de saída (assinatura do bug da Carla).
"""
from app.agent.orchestrator import DEFAULT_MODEL, _thinking_off_for
from app.follow_up import scheduler as SCH
from app.config import settings


def test_default_models_atuais_2_5_ate_migracao_planejada():
    assert DEFAULT_MODEL == "gemini-2.5-flash"
    assert SCH._FOLLOWUP_MODEL == "gemini-2.5-flash"
    assert settings.memory_model == "gemini-2.5-flash-lite"
    assert settings.transcription_model == "gemini-2.5-flash-lite"


def test_thinking_off_cobre_familia_3x():
    # flash/lite (2.5 legado e 3.x atuais) → thinking OFF (thinking_budget=0 no núcleo)
    for m in ("gemini-2.5-flash", "gemini-2.5-flash-lite",
              "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview"):
        assert _thinking_off_for(m) is True, m
    # pro pensa (não desligar)
    for m in ("gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-pro-latest"):
        assert _thinking_off_for(m) is False, m
    # não-Gemini intocado
    assert _thinking_off_for("gpt-4o") is False
