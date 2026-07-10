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
import re
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.supabase import get_supabase
from app.leads.service import get_history, get_lead, update_lead

logger = logging.getLogger(__name__)

# Modelo default resolvido em runtime via settings.memory_model (env MEMORY_MODEL) —
# consolidar dossiê é merge mecânico de JSON: flash-lite por default (FinOps 08/07),
# revertível por env sem deploy. Callers que passam `model` explícito seguem mandando.

# Janela debounce/seleção do worker e parâmetros do lock.
INACTIVITY_GAP = timedelta(minutes=10)   # silêncio mínimo p/ considerar a "sessão encerrada"
RECENCY_WINDOW = timedelta(hours=24)     # só sessões recém-encerradas (evita backfill da base fria)
LOCK_TTL = timedelta(minutes=5)          # lock mais velho que isto é considerado órfão (worker crashou)
BATCH_LIMIT = 20                         # leads processados por tick do worker
# Cap do caminho "sem dossiê prévio" (histórico completo): mantém o prompt bounded
# mesmo p/ leads com centenas de mensagens — só as últimas N entram na 1ª consolidação.
MEMORY_BACKFILL_MAX_MSGS = 200

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
    """Desliga o thinking dos Gemini flash/lite (exceto pro), que senão queimam o budget e
    devolvem vazio. Família 3.x aceita reasoning_effort="none" (validado 09/07 no sunset)."""
    if model.startswith("gemini-") and "pro" not in model and ("flash" in model or "lite" in model):
        return {"reasoning_effort": "none"}
    return {}


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json_object(content: str) -> dict:
    """Extrai o objeto JSON da saída do modelo, tolerando cerca markdown e prosa em volta.

    Auditoria 08/07: o Gemini devolvia o dossiê embrulhado (```json ... ``` ou texto ao
    redor) e o `json.loads` cru rejeitava 100% das 1.366 gerações do dia — nenhum
    dossiê persistiu e, no código pré-53bcdf2, a marca d'água parada realimentava o loop.
    Levanta ValueError/JSONDecodeError quando não há objeto JSON válido.
    """
    text = (content or "").strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{") or not text.endswith("}"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("nenhum objeto JSON na saída do modelo")
        text = text[start:end + 1]
    fields = json.loads(text)
    if not isinstance(fields, dict):
        raise ValueError("saída JSON não é um objeto")
    return fields


def _fire_memory_parse_alert() -> None:
    """Alerta memory_parse_fail (dedup: 1 não-resolvido por 24h). Fail-soft.

    Um subsistema que falha em 100% das chamadas não pode voltar a ser invisível
    (08/07: US$1,01 queimados em gerações que nunca persistiram nada).
    """
    try:
        sb = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        existing = (
            sb.table("system_alerts").select("id")
            .eq("type", "memory_parse_fail").eq("resolved", False)
            .gte("created_at", cutoff).limit(1).execute()
        )
        if existing.data:
            return
        from app.alerts.service import create_system_alert
        create_system_alert(
            "memory_parse_fail",
            "Dossiê do lead não está sendo persistido",
            "generate_rolling_summary está recebendo saída não-JSON do modelo e preservando o "
            "dossiê anterior. Verifique o formato de resposta do MEMORY_MODEL — sem isso a "
            "memória de longo prazo da Valéria fica em branco.",
            severity="warning",
        )
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("memory_manager: falha ao gravar alerta memory_parse_fail: %s", exc)


def _track_memory_usage(response, lead_id: str | None, stage: str, model: str) -> None:
    """Contabiliza o custo do refresh de dossiê em token_usage. Fail-soft: nunca levanta —
    era off-book (rodava a cada sessão encerrada de cada lead sem gravar nada)."""
    try:
        usage = getattr(response, "usage", None)
        if not usage or not lead_id:
            return
        from app.agent.token_tracker import track_token_usage
        track_token_usage(
            lead_id=lead_id,
            stage=stage or "",
            model=model,
            call_type="rolling_summary",
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            cached_tokens=getattr(usage, "cached_tokens", 0) or 0,
            reasoning_tokens=getattr(usage, "reasoning_tokens", 0) or 0,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("memory_manager: falha ao registrar token_usage (ignorado): %s", exc)


async def generate_rolling_summary(
    prior_summary: str, delta: list[dict], client, model: str,
    lead_id: str | None = None, stage: str = "",
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
        _track_memory_usage(response, lead_id, stage, model)
        if not response.choices:
            return prior_summary
        content = response.choices[0].message.content or ""
        try:
            fields = _extract_json_object(content)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "generate_rolling_summary: saída não-JSON do modelo (lead=%s): %.200s — %s",
                lead_id, content, exc,
            )
            _fire_memory_parse_alert()
            return prior_summary
        return render_dossier(fields)
    except Exception as exc:
        logger.error("generate_rolling_summary: falha na chamada LLM: %s", exc, exc_info=True)
        return prior_summary


def _parse_ts(value: str) -> datetime:
    """Parse tolerante de timestamp ISO do PostgREST (aceita sufixo 'Z')."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _summary_is_current(rolling_summary_updated_at, last_customer_message_at) -> bool:
    """True se o dossiê já cobre a última mensagem do cliente (nada novo p/ resumir).
    Usado p/ NÃO reselecionar o mesmo lead a cada tick só p/ achar delta vazio (lock churn +
    egress). Fail-open: em dúvida (campos ausentes/formato estranho) devolve False → processa."""
    if not rolling_summary_updated_at or not last_customer_message_at:
        return False
    try:
        return _parse_ts(rolling_summary_updated_at) >= _parse_ts(last_customer_message_at)
    except Exception:
        return False


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


async def refresh_lead_memory(lead_id: str, client=None, model: str | None = None) -> bool:
    """Regenera o dossiê do lead (cross-canal), com lock de concorrência. Fail-soft: nunca
    levanta. Retorna True só quando gravou um dossiê novo."""
    model = model or settings.memory_model
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    if not _claim_lock(sb, lead_id, now):
        # Outro gatilho/worker já está processando este lead (B2/B3) → no-op silencioso.
        return False
    try:
        lead = get_lead(lead_id) or {}
        prior = lead.get("rolling_summary") or ""
        # Sem dossiê prévio, a marca d'água NÃO vale nada: as gerações que falharam no
        # parse (burn 08/07: 1.366 chamadas, zero persistência) avançaram o watermark
        # sem gravar dossiê — honrá-lo perderia a história anterior para sempre.
        # Primeira consolidação lê o histórico completo (capado); com dossiê, delta
        # incremental como sempre. Este caminho também é o motor do backfill
        # (scripts/backfill_dossies.py).
        since = lead.get("rolling_summary_updated_at") if prior else None
        if prior:
            delta = get_history(lead_id, since=since)
        else:
            # Histórico completo REAL: janela das MEMORY_BACKFILL_MAX_MSGS mensagens
            # mais recentes (latest=True). O default limit=30 asc do get_history
            # devolvia as 30 mais ANTIGAS e o cap de 200 nunca agia.
            delta = get_history(
                lead_id, since=None, limit=MEMORY_BACKFILL_MAX_MSGS, latest=True
            )
        if not delta:
            return False
        if client is None:
            from app.agent.orchestrator import get_ai_client
            client = get_ai_client(model)
        new_summary = await generate_rolling_summary(
            prior, delta, client, model, lead_id=lead_id, stage=lead.get("stage") or "",
        )
        # Marca d'água: avança rolling_summary_updated_at até a ÚLTIMA mensagem já consumida
        # neste delta — MESMO quando o dossiê sai idêntico ao anterior. Sem isso, um dossiê
        # estável (lead quieto, delta sem novidade relevante) reprocessa o MESMO delta a cada
        # tick do worker, num loop que queimou ~78 refreshes/lead/dia (1117 chamadas LLM p/ 15
        # leads em 08/07). Usa o created_at da última msg do delta (não now()) p/ não "pular"
        # mensagens que chegaram durante o processamento — elas entram no próximo ciclo.
        watermark = (delta[-1].get("created_at") if delta else None) or now.isoformat()
        if not new_summary or new_summary == prior:
            # nada novo p/ gravar no texto, mas consumimos o delta → só avança a marca d'água
            update_lead(lead_id, rolling_summary_updated_at=watermark)
            return False
        update_lead(
            lead_id,
            rolling_summary=new_summary,
            rolling_summary_updated_at=watermark,
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
            .select("id, last_customer_message_at, rolling_summary_updated_at, rolling_summary")
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
        # Se o dossiê já cobre a última msg do cliente, não há delta novo: pular ANTES de pegar
        # o lock evita o churn de claim/release + SELECT vazio a cada tick (visto no loop 08/07).
        # SÓ vale com dossiê gravado: rolling_summary NULL com watermark avançado é vítima do
        # burn (gerações que falharam no parse avançaram a marca) — precisa reprocessar, senão
        # o lead nunca ganha dossiê pela via de produção.
        if row.get("rolling_summary") and _summary_is_current(
            row.get("rolling_summary_updated_at"), row.get("last_customer_message_at")
        ):
            continue
        if await refresh_lead_memory(lead_id):
            count += 1
    return count
