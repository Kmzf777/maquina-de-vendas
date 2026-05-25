# backend/app/automation/test_runner.py
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _format_error(e: Exception) -> str:
    """Extract a human-readable error message, particularly for Meta API HTTP errors.

    Meta returns errors as JSON like:
      {"error": {"message": "...", "code": 132001, "error_data": {"details": "..."}}}
    We surface the most actionable string for the user.
    """
    # httpx.HTTPStatusError carries .response with the failing payload
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            data = resp.json()
        except Exception:
            data = None
        if isinstance(data, dict):
            err = data.get("error") if isinstance(data.get("error"), dict) else None
            if err:
                msg = err.get("message") or ""
                details = (err.get("error_data") or {}).get("details") if isinstance(err.get("error_data"), dict) else ""
                code = err.get("code")
                parts = [p for p in (msg, details) if p]
                base = " — ".join(parts) if parts else json.dumps(err, ensure_ascii=False)
                return f"Meta API erro {code}: {base}" if code else base
        try:
            return f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception:
            pass
    text = str(e) or e.__class__.__name__
    return text[:500]


def _build_node_sequence(nodes: list[dict]) -> list[dict]:
    """Return nodes in execution order, skipping the trigger node."""
    by_id = {n["id"]: n for n in nodes}
    trigger = next((n for n in nodes if n["type"] == "trigger"), None)
    if not trigger or not trigger.get("next_node_id"):
        return []
    sequence = []
    seen = set()
    current_id = trigger["next_node_id"]
    while current_id and current_id not in seen:
        seen.add(current_id)
        node = by_id.get(current_id)
        if not node:
            break
        sequence.append(node)
        current_id = node.get("next_node_id")
    return sequence


def _get_or_create_test_lead(phone: str) -> tuple[dict, bool]:
    """Return (lead, was_created). Creates a temporary lead if not found.

    The phone is normalized via leads.service.normalize_phone (BR 12→13 digit fix),
    matching the rest of the codebase. This avoids creating a phantom test lead
    with a phone Meta will reject (e.g. 12-digit BR number missing the 9th digit).
    """
    sb = get_supabase()
    from app.automation.engine import _get_env_tag
    from app.leads.service import normalize_phone
    env_tag = _get_env_tag()
    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError("Telefone vazio ou inválido")
    rows = sb.table("leads").select("*").eq("phone", normalized).limit(1).execute().data
    if rows:
        return rows[0], False
    inserted = sb.table("leads").insert({
        "name": "Teste",
        "phone": normalized,
        "env_tag": env_tag,
        "ai_enabled": False,
        "stage": "Novo",
    }).execute().data
    if not inserted:
        raise RuntimeError("Falha ao criar lead de teste")
    return inserted[0], True


def _delete_test_lead(lead_id: str) -> None:
    sb = get_supabase()
    sb.table("leads").delete().eq("id", lead_id).execute()


async def run_test_campaign(
    campaign_id: str,
    phone: str,
    skip_delays: bool = True,
) -> AsyncGenerator[str, None]:
    """SSE generator: executes campaign nodes for a test phone number."""
    sb = get_supabase()

    # Load campaign + nodes
    camp_data = (
        sb.table("campaigns")
        .select("*, campaign_nodes(*)")
        .eq("id", campaign_id)
        .single()
        .execute()
        .data
    )
    if not camp_data:
        yield _format_sse({"node_id": None, "status": "failed", "log": "Campanha não encontrada"})
        yield _format_sse({"node_id": None, "status": "finished"})
        return

    campaign = camp_data
    nodes: list[dict] = camp_data.get("campaign_nodes") or []
    sequence = _build_node_sequence(nodes)

    if not sequence:
        yield _format_sse({
            "node_id": None,
            "status": "failed",
            "log": "Nenhum nó executável encontrado (adicione nós após o gatilho)",
        })
        yield _format_sse({"node_id": None, "status": "finished"})
        return

    lead, was_created = _get_or_create_test_lead(phone)
    now = datetime.now(timezone.utc)
    fake_enrollment = {"lead_id": lead["id"], "campaign_id": campaign_id}

    try:
        next_node_id: str | None = sequence[0]["id"]
        nodes_by_id = {n["id"]: n for n in nodes}

        while next_node_id:
            node = nodes_by_id.get(next_node_id)
            if not node:
                break
            if node["type"] == "trigger":
                next_node_id = node.get("next_node_id")
                continue

            node_id = node["id"]
            yield _format_sse({"node_id": node_id, "status": "running"})
            t_start = asyncio.get_event_loop().time()

            try:
                result_log, branch = await _execute_test_node(
                    node, lead, fake_enrollment, campaign, now, skip_delays
                )
                duration_ms = int((asyncio.get_event_loop().time() - t_start) * 1000)
                yield _format_sse({
                    "node_id": node_id,
                    "status": "done",
                    "log": result_log,
                    "duration_ms": duration_ms,
                })

                if branch == "yes":
                    next_node_id = node.get("yes_node_id")
                elif branch == "no":
                    next_node_id = node.get("no_node_id")
                else:
                    next_node_id = node.get("next_node_id")

                if node["type"] == "end":
                    break

            except Exception as e:
                duration_ms = int((asyncio.get_event_loop().time() - t_start) * 1000)
                yield _format_sse({
                    "node_id": node_id,
                    "status": "failed",
                    "log": _format_error(e),
                    "duration_ms": duration_ms,
                })
                break

    finally:
        if was_created:
            _delete_test_lead(lead["id"])

    yield _format_sse({"node_id": None, "status": "finished"})


async def _execute_test_node(
    node: dict,
    lead: dict,
    enrollment: dict,
    campaign: dict,
    now: datetime,
    skip_delays: bool,
) -> tuple[str, str | None]:
    """Execute a single node. Returns (log_message, branch) where branch is 'yes'|'no'|None."""
    from app.automation.engine import _resolve_channel
    node_type = node["type"]
    cfg = node.get("config") or {}

    if node_type == "send":
        from app.whatsapp.registry import get_provider
        from app.broadcast.worker import _build_template_components
        template_name = (cfg.get("template_name") or "").strip()
        if not template_name:
            raise ValueError("Nó 'Enviar template' sem template selecionado. Abra o Inspector e escolha um template.")
        channel = _resolve_channel(cfg, campaign)
        provider = get_provider(channel)
        components = _build_template_components(cfg.get("template_variables", {}), lead)
        await provider.send_template(
            to=lead["phone"],
            template_name=template_name,
            components=components,
            language_code=cfg.get("template_language", "pt_BR"),
        )
        return f"Template '{template_name}' enviado via {channel.get('name', channel.get('id'))}", None

    if node_type == "send_text":
        from app.whatsapp.registry import get_provider
        from app.automation.variables import substitute_variables
        message = substitute_variables(cfg.get("message_text", ""), lead, enrollment)
        if not message.strip():
            raise ValueError("Nó 'Enviar texto' sem mensagem configurada. Abra o Inspector e preencha o texto.")
        channel = _resolve_channel(cfg, campaign)
        provider = get_provider(channel)
        await provider.send_text(lead["phone"], message)
        return f"Texto enviado: \"{message[:60]}{'...' if len(message) > 60 else ''}\"", None

    if node_type == "wait":
        days = cfg.get("days", 1)
        if skip_delays:
            await asyncio.sleep(0.8)
            return f"Aguardar {days} dia(s) — pulado no teste", None
        await asyncio.sleep(days * 86400)
        return f"Aguardou {days} dia(s)", None

    if node_type == "condition":
        cond_type = cfg.get("condition_type", "replied_recently")
        branch = _eval_condition(cfg, lead, enrollment, now)
        return f"Condição '{cond_type}' → {'SIM' if branch == 'yes' else 'NÃO'}", branch

    if node_type == "action":
        action_type = cfg.get("action_type", "")
        action_labels = {
            "move_stage": "Mover estágio do lead",
            "mark_deal_won": "Marcar deal como ganho",
            "mark_deal_lost": "Marcar deal como perdido",
            "move_deal_stage": "Mover deal de estágio",
            "activate_agent": "Ativar agente AI",
            "deactivate_agent": "Desativar agente AI",
            "add_tag": "Adicionar tag",
            "remove_tag": "Remover tag",
            "create_deal": "Criar deal",
            "assign_to": "Atribuir vendedor",
            "assign_round_robin": "Atribuir via round-robin",
            "add_note": "Adicionar nota",
        }
        label = action_labels.get(action_type, action_type or "ação")
        return f"[Simulado] {label} — sem efeito real no modo teste", None

    if node_type == "end":
        return "Fluxo encerrado", None

    return f"Nó tipo '{node_type}' processado", None


def _eval_condition(cfg: dict, lead: dict, enrollment: dict, now: datetime) -> str:
    """Evaluate condition and return 'yes' or 'no'."""
    from datetime import timedelta
    sb = get_supabase()
    cond = cfg.get("condition_type", "replied_recently")

    if cond == "replied_recently":
        cutoff = (now - timedelta(days=cfg.get("days", 5))).isoformat()
        msgs = (
            sb.table("messages")
            .select("id")
            .eq("lead_id", enrollment["lead_id"])
            .eq("role", "user")
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        return "yes" if msgs.data else "no"

    if cond == "in_stage":
        return "yes" if lead.get("stage") == cfg.get("stage") else "no"

    if cond == "has_deal":
        rows = sb.table("deals").select("id").eq("lead_id", enrollment["lead_id"]).limit(1).execute()
        return "yes" if rows.data else "no"

    if cond == "has_tag":
        tag_name = cfg.get("tag_name", "")
        tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
        if tag_row:
            lt = (
                sb.table("lead_tags")
                .select("id")
                .eq("lead_id", enrollment["lead_id"])
                .eq("tag_id", tag_row[0]["id"])
                .limit(1)
                .execute()
            )
            return "yes" if lt.data else "no"
        return "no"

    from app.automation.engine import _compare
    op = cfg.get("operator", "gte")
    target = cfg.get("value", 0)

    if cond == "sale_count":
        res = sb.table("sales").select("id", count="exact").eq("lead_id", enrollment["lead_id"]).execute()
        return "yes" if _compare(res.count or 0, op, target) else "no"

    if cond == "total_spend":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).execute().data or []
        total = sum(float(r["value"]) for r in rows)
        return "yes" if _compare(total, op, target) else "no"

    if cond == "last_sale_value":
        rows = (
            sb.table("sales")
            .select("value")
            .eq("lead_id", enrollment["lead_id"])
            .order("sold_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        val = float(rows[0]["value"]) if rows else 0
        return "yes" if _compare(val, op, target) else "no"

    if cond == "repurchase_days":
        rows = (
            sb.table("sales")
            .select("sold_at")
            .eq("lead_id", enrollment["lead_id"])
            .order("sold_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            from dateutil.parser import parse
            sold_at = parse(rows[0]["sold_at"]) if isinstance(rows[0]["sold_at"], str) else rows[0]["sold_at"]
            days_since = (now - sold_at).days
            return "yes" if _compare(days_since, op, target) else "no"
        return "no"

    return "yes"  # unknown conditions pass by default
