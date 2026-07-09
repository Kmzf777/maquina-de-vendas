"""Gemini wrapper — plays lead archetypes (flash-lite) and judges conversations (2.5 pro).

Lazy imports of google.generativeai so tests don't require the package to be
installed to run (they monkeypatch _get_model).
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

ACTOR_MODEL_NAME = "gemini-3.1-flash-lite"
JUDGE_MODEL_NAME = "gemini-2.5-pro"
MODEL_NAME = JUDGE_MODEL_NAME  # backward-compat for rehearsal_runner.py run.json
MAX_RETRIES = 3

# Chave Gemini DEDICADA de desenvolvimento. O rehearsal consome cota; usar a mesma chave
# da produção drena o saldo de produção (incidente 1-6/jul/2026: R$149 de output off-book
# gerado por simulações na chave compartilhada). O harness EXIGE esta chave, isolada da prod.
DEV_API_KEY_ENV = "GEMINI_API_KEY_DEV"


class GeminiFailure(Exception):
    """Raised when Gemini calls fail after max retries."""


def require_isolated_gemini_key() -> None:
    """Aborta o harness se não houver uma chave Gemini de DEV isolada da produção.

    Regras: `GEMINI_API_KEY_DEV` precisa estar definida e ser DIFERENTE de `GEMINI_API_KEY`
    (a de produção). Override consciente e explícito: `REHEARSAL_ALLOW_PROD=1`. Chamado no
    startup dos runners (runtime, não no import — para não quebrar a coleta de testes)."""
    if os.environ.get("REHEARSAL_ALLOW_PROD") == "1":
        return
    dev = os.environ.get(DEV_API_KEY_ENV)
    prod = os.environ.get("GEMINI_API_KEY")
    if not dev:
        raise SystemExit(
            f"[GUARD] {DEV_API_KEY_ENV} não definido — o rehearsal exige uma chave Gemini "
            f"ISOLADA de dev (nunca a de produção). Crie uma chave separada no Google AI "
            f"Studio e exporte {DEV_API_KEY_ENV} no .env.local. "
            f"Override consciente: REHEARSAL_ALLOW_PROD=1."
        )
    if prod and dev == prod:
        raise SystemExit(
            f"[GUARD] {DEV_API_KEY_ENV} é IGUAL a GEMINI_API_KEY (produção) — use uma chave "
            f"DISTINTA para não drenar a cota de produção. "
            f"Override consciente: REHEARSAL_ALLOW_PROD=1."
        )


def _get_model(model_name: str = JUDGE_MODEL_NAME):
    """Lazy-build the Gemini model. Overridable in tests via monkeypatch.

    Usa a chave de DEV (GEMINI_API_KEY_DEV) por padrão; só cai na GEMINI_API_KEY quando a de
    dev está ausente — o que, fora de REHEARSAL_ALLOW_PROD=1, é barrado por
    require_isolated_gemini_key() no startup do runner."""
    import google.generativeai as genai
    api_key = os.environ.get(DEV_API_KEY_ENV) or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiFailure(f"{DEV_API_KEY_ENV} not set in environment")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def _with_retry(call, *args, **kwargs):
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return call(*args, **kwargs)
        except Exception as e:
            last_err = e
            backoff = 2 ** attempt
            logger.warning(f"Gemini call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {backoff}s")
            time.sleep(backoff)
    raise GeminiFailure(f"Gemini call failed after {MAX_RETRIES} retries: {last_err}")


def _format_history(conversation_history: list[dict]) -> str:
    lines = []
    for msg in conversation_history:
        role = msg.get("role", "?")
        content = msg.get("content", "").strip()
        label = {"assistant": "Atendente", "user": "Lead", "system": "[sistema]"}.get(role, role)
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def generate_next_lead_message(
    persona_prompt: str,
    conversation_history: list[dict],
    last_assistant_message: str,
) -> str:
    """Ask Gemini to produce the lead's next message in character."""
    history_text = _format_history(conversation_history) or "(conversa ainda nao comecou)"
    prompt = f"""{persona_prompt}

=== Historico da conversa ate agora ===
{history_text}

=== Ultima mensagem da Atendente ===
{last_assistant_message.strip() or "(nao enviou nada ainda)"}

=== Sua proxima mensagem como Lead ===
"""

    def _call():
        model = _get_model(ACTOR_MODEL_NAME)
        response = model.generate_content(prompt, request_options={"timeout": 120})
        return response.text.strip() if response.text else ""

    text = _with_retry(_call)
    return text.strip()


def judge_conversation(transcript: str, archetype_id: str, criteria_description: str) -> dict:
    """Ask Gemini to judge a completed rehearsal conversation."""
    prompt = f"""Voce eh um avaliador de qualidade de um agente de vendas por WhatsApp chamado Valeria.

Arquetipo de lead testado: {archetype_id}
Criterios esperados: {criteria_description}

=== Transcricao da conversa ===
{transcript}

=== Avalie em JSON puro ===
Responda APENAS com um JSON valido (sem explicacao adicional) neste formato:
{{
  "bot_score_1_10": <inteiro 1-10, 10=soa totalmente humano>,
  "linhas_robotizadas": [<strings literais das frases da Valeria que pareceram roboticas>],
  "resposta_incorreta_ou_inventada": <string descrevendo ou null>,
  "veredito_curto": <string em 1 frase: resumo do desempenho>
}}"""

    def _call():
        model = _get_model()
        response = model.generate_content(prompt, request_options={"timeout": 120})
        return response.text or ""

    try:
        raw = _with_retry(_call)
    except GeminiFailure as e:
        return {"error": str(e), "bot_score_1_10": None}

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"error": "no_json_found", "raw": raw[:500], "bot_score_1_10": None}

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"invalid_json: {e}", "raw": raw[:500], "bot_score_1_10": None}
