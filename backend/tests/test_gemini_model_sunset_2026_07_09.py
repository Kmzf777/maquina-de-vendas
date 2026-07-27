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
    # MITIGAÇÃO 27/07: DEFAULT_MODEL saiu do flash para o -lite. Medido em produção
    # após o estouro do teto mensal: lite 32/32 chamadas OK, flash 1/~20 — o flash
    # ficou com cota restrita para os ~36K tokens do turno da Valéria. Reverter com
    # AGENT_DEFAULT_MODEL=gemini-2.5-flash quando o tier do projeto subir.
    assert DEFAULT_MODEL == "gemini-2.5-flash-lite"
    assert SCH._FOLLOWUP_MODEL == "gemini-2.5-flash"
    assert settings.memory_model == "gemini-2.5-flash-lite"
    assert settings.transcription_model == "gemini-2.5-flash-lite"
    # A família continua sendo a 2.5 até a migração planejada (sunset real 16/10/2026).
    assert DEFAULT_MODEL.startswith("gemini-2.5-")


def test_default_model_e_configuravel_por_env(monkeypatch):
    """A troca de modelo tem que ser possível SEM deploy — o incidente de 27/07 mostrou
    que depender de deploy para trocar de modelo custa horas de silêncio.

    Exercita resolve_default_model() diretamente: NUNCA usar importlib.reload aqui —
    recarregar o orchestrator recria LLMUnavailableError e filhas, e todo teste que já
    importou essas classes passa a falhar (visto na suíte em 27/07).
    """
    from app.agent.orchestrator import resolve_default_model

    monkeypatch.setenv("AGENT_DEFAULT_MODEL", "gemini-2.5-flash")
    assert resolve_default_model() == "gemini-2.5-flash"

    monkeypatch.setenv("AGENT_DEFAULT_MODEL", "   ")  # vazio/branco cai no fallback
    assert resolve_default_model() == "gemini-2.5-flash-lite"

    monkeypatch.delenv("AGENT_DEFAULT_MODEL", raising=False)
    assert resolve_default_model() == "gemini-2.5-flash-lite"


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
