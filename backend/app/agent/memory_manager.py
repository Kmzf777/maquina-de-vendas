"""Camada de Memória de Longo Prazo (Lead Memory Layer) — "Dossiê do Lead".

Resumo rolante (rolling summary) por LEAD (cross-canal): consolida o que a Valéria sabe do
cliente — perfil, preferências, objeções, estágio do negócio, próximo passo — para injetar no
prompt a cada turno, independente de canal ou do tamanho da janela de contexto.

Ver docs/superpowers/specs/2026-06-26-lead-memory-layer-design.md

Pontos de arquitetura:
  - D4 Delta-only: o LLM recebe SÓ o `prior_summary` + as mensagens novas
    (`created_at > rolling_summary_updated_at`), nunca o transcript inteiro.
  - D5 Lock no banco (`leads.rolling_summary_processing_at`): claim atômico + TTL; release no
    finally. Resolve worker-overlap (B2) e a corrida Gatilho A×B (B3) — o segundo claim falha.
  - D6 Structured output (JSON) renderizado para markdown determinístico — sem "conversinha".
  - Fail-soft em toda parte: nunca levanta para o chamador; em erro preserva o dossiê anterior.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.leads.service import get_history, get_lead, update_lead

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

# Janela debounce/seleção do worker e parâmetros do lock.
INACTIVITY_GAP = timedelta(minutes=10)   # silêncio mínimo p/ considerar a "sessão encerrada"
RECENCY_WINDOW = timedelta(hours=24)     # só sessões recém-encerradas (evita backfill da base fria)
LOCK_TTL = timedelta(minutes=5)          # lock mais velho que isto é considerado órfão (worker crashou)
BATCH_LIMIT = 20                         # leads processados por tick do worker

MAX_OUTPUT_TOKENS = 1024

# Campos do dossiê (chave JSON → rótulo no markdown). Ordem preservada no render.
_DOSSIER_FIELDS: tuple[tuple[str, str], ...] = (
    ("perfil_empresa", "Perfil / Empresa"),
    ("interesse_preferencias", "Interesse e preferências de produto"),
    ("objecoes", "Objeções levantadas"),
    ("estagio_negocio", "Estágio do negócio"),
    ("proximo_passo", "Próximo passo sugerido"),
)

_PLACEHOLDER = "Não informado"

_SYSTEM_PROMPT = """Você é o memorialista comercial da Café Canastra. Sua função é manter um \
DOSSIÊ consolidado de cada lead para a vendedora Valéria.

Você recebe o DOSSIÊ ANTERIOR (já consolidado) e SÓ as mensagens NOVAS da conversa. Produza o \
DOSSIÊ ATUALIZADO unindo as duas fontes.

REGRAS:
- NUNCA descarte um fato já conhecido do dossiê anterior, a menos que as mensagens novas o \
contradigam explicitamente. Em caso de conflito, o dado mais recente vence.
- Nunca invente. Se um campo não tem informação, escreva exatamente "Não informado".
- Seja conciso e objetivo (1-3 frases por campo).

Responda EXCLUSIVAMENTE com um objeto JSON com estas chaves (strings):
- "perfil_empresa": quem é o lead, segmento, porte, região.
- "interesse_preferencias": o que quer, variações de produto, volumes citados.
- "objecoes": objeções levantadas (preço, frete, prazo, confiança) e se foram resolvidas.
- "estagio_negocio": onde está no funil e sinais de aquecimento.
- "proximo_passo": a melhor próxima ação comercial.

Não escreva nada fora do JSON."""


def render_dossier(fields: dict) -> str:
    """Renderiza os campos (dict) no markdown fixo do dossiê. Campos ausentes → placeholder."""
    lines = ["## DOSSIÊ DO LEAD"]
    for key, label in _DOSSIER_FIELDS:
        value = (fields.get(key) or "").strip() if isinstance(fields.get(key), str) else fields.get(key)
        lines.append(f"* **{label}:** {value or _PLACEHOLDER}")
    return "\n".join(lines)


def _render_delta(delta: list[dict]) -> str:
    lines = []
    for m in delta:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            label = "Lead" if role == "user" else "Valéria"
            lines.append(f"[{label}]: {content}")
    return "\n".join(lines)


def build_memory_messages(prior_summary: str, delta: list[dict]) -> list[dict]:
    """Monta system+user para o LLM. O user carrega o prior_summary e SÓ o delta (D4)."""
    user = (
        "DOSSIÊ ANTERIOR:\n"
        f"{prior_summary or '(ainda não há dossiê — esta é a primeira consolidação)'}\n\n"
        "MENSAGENS NOVAS (desde o último dossiê):\n"
        f"{_render_delta(delta)}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _gemini_thinking_off(model: str) -> dict:
    """Desliga o thinking do gemini-2.5 (exceto pro), que senão queima o budget e devolve vazio."""
    if model.startswith("gemini-2.5-") and not model.startswith("gemini-2.5-pro"):
        return {"reasoning_effort": "none"}
    return {}


async def generate_rolling_summary(
    prior_summary: str, delta: list[dict], client, model: str,
) -> str:
    """Gera o dossiê atualizado (structured JSON → markdown). Fail-soft: erro/JSON inválido/
    delta vazio → devolve o `prior_summary` intacto (nunca perde memória nem degrada formato)."""
    if not delta:
        return prior_summary
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=build_memory_messages(prior_summary, delta),
            response_format={"type": "json_object"},
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
            **_gemini_thinking_off(model),
        )
        if not response.choices:
            return prior_summary
        content = response.choices[0].message.content or ""
        fields = json.loads(content)
        if not isinstance(fields, dict):
            return prior_summary
        return render_dossier(fields)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("generate_rolling_summary: saída não-JSON do modelo — preservando prior: %s", exc)
        return prior_summary
    except Exception as exc:
        logger.error("generate_rolling_summary: falha na chamada LLM: %s", exc, exc_info=True)
        return prior_summary


def _claim_lock(sb, lead_id: str, now: datetime) -> bool:
    """Claim atômico do lock. UPDATE ... WHERE id=? AND (processing_at IS NULL OR < now-TTL).
    O Postgres serializa a linha → de dois claims concorrentes só um casa o WHERE."""
    lock_cutoff = (now - LOCK_TTL).isoformat()
    res = (
        sb.table("leads")
        .update({"rolling_summary_processing_at": now.isoformat()})
        .eq("id", lead_id)
        .or_(f"rolling_summary_processing_at.is.null,rolling_summary_processing_at.lt.{lock_cutoff}")
        .execute()
    )
    return bool(res.data)


def _release_lock(sb, lead_id: str) -> None:
    try:
        sb.table("leads").update({"rolling_summary_processing_at": None}).eq("id", lead_id).execute()
    except Exception as exc:
        logger.error("memory_manager: falha ao liberar lock do lead %s: %s", lead_id, exc)


async def refresh_lead_memory(lead_id: str, client=None, model: str = DEFAULT_MODEL) -> bool:
    """Regenera o dossiê do lead (cross-canal), com lock de concorrência. Fail-soft: nunca
    levanta. Retorna True só quando gravou um dossiê novo."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    if not _claim_lock(sb, lead_id, now):
        # Outro gatilho/worker já está processando este lead (B2/B3) → no-op silencioso.
        return False
    try:
        lead = get_lead(lead_id) or {}
        prior = lead.get("rolling_summary") or ""
        since = lead.get("rolling_summary_updated_at")
        delta = get_history(lead_id, since=since)
        if not delta:
            return False
        if client is None:
            from app.agent.orchestrator import get_ai_client
            client = get_ai_client(model)
        new_summary = await generate_rolling_summary(prior, delta, client, model)
        if not new_summary or new_summary == prior:
            return False
        update_lead(
            lead_id,
            rolling_summary=new_summary,
            rolling_summary_updated_at=now.isoformat(),
        )
        logger.info("refresh_lead_memory: dossiê atualizado para lead %s", lead_id)
        return True
    except Exception as exc:
        logger.error("refresh_lead_memory: falha para lead %s: %s", lead_id, exc, exc_info=True)
        return False
    finally:
        _release_lock(sb, lead_id)


async def process_stale_lead_memories(now: datetime | None = None) -> int:
    """Worker debounced (Gatilho A): consolida a memória de leads cuja sessão acabou de
    encerrar. Seleção bounded pela janela de recência (evita varrer a base histórica).
    Fail-soft: nunca levanta. Retorna quantos dossiês foram efetivamente atualizados."""
    now = now or datetime.now(timezone.utc)
    try:
        sb = get_supabase()
        recency_cutoff = (now - RECENCY_WINDOW).isoformat()
        inactivity_cutoff = (now - INACTIVITY_GAP).isoformat()
        lock_cutoff = (now - LOCK_TTL).isoformat()
        rows = (
            sb.table("leads")
            .select("id")
            .gte("last_customer_message_at", recency_cutoff)
            .lt("last_customer_message_at", inactivity_cutoff)
            .or_(f"rolling_summary_processing_at.is.null,rolling_summary_processing_at.lt.{lock_cutoff}")
            .order("last_customer_message_at", desc=False)
            .limit(BATCH_LIMIT)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("process_stale_lead_memories: falha ao selecionar candidatos: %s", exc, exc_info=True)
        return 0

    count = 0
    for row in rows:
        lead_id = row.get("id")
        if not lead_id:
            continue
        if await refresh_lead_memory(lead_id):
            count += 1
    return count
