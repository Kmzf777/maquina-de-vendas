"""Recuperação de disparos perdidos do canal do João (queda de WhatsApp de 03/07).

Reenvia disparos OUTBOUND do canal do João que falharam / não confirmaram entrega
desde a sexta-feira da queda, protegido pelas DUAS REGRAS DE OURO (não-negociáveis):

  R1. Só reenviar a leads que NÃO responderam (nenhum inbound) DEPOIS do disparo que
      falhou — quem já respondeu não pode ser re-spammado.
  R2. Só reenviar se a janela de sessão de 24h do WhatsApp ainda estiver ABERTA
      (última inbound do lead < 24h atrás). Fora da janela, a Meta exige TEMPLATE —
      um reenvio free-form seria rejeitado, então NÃO é elegível aqui.

Modo padrão = DRY-RUN (somente leitura): conta e lista os elegíveis, não escreve nada
nem chama a API do WhatsApp. Só com `--execute --yes` o reenvio real acontece, e ainda
assim apenas sobre o conjunto que passou por R1∩R2, com teto de segurança.

Uso (dentro do container/venv do backend, com SUPABASE_URL + SUPABASE_SERVICE_KEY no env):
    python -m scripts.recover_joao_disparos                 # dry-run (conta)
    python -m scripts.recover_joao_disparos --execute --yes # reenvio real (só R1∩R2)
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone

from supabase import create_client

# Canal do João em produção (channels.name = 'NUMERO JOÃO', mode=human).
JOAO_CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd"

# Sexta-feira da queda dos números. Ajustável por flag.
DEFAULT_FAILURE_START = "2026-07-03T00:00:00Z"

# delivery_status que contam como "falhou / não entregue / travado na fila".
# Tudo que NÃO é confirmação de entrega ao aparelho do lead.
UNCONFIRMED_STATUSES = ("failed", "undelivered", "accepted", "sent")

# Janela de sessão do WhatsApp.
SESSION_WINDOW_HOURS = 24

# Teto duro anti-spam: se o conjunto elegível passar disto, aborta e pede revisão manual.
MAX_RESEND = 200


def _sb():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def compute_eligible(sb, failure_start: str, window_hours: int) -> list[dict]:
    """Aplica R1∩R2 e devolve a lista de disparos elegíveis para reenvio.

    Espelha exatamente a SQL de auditoria: disparo assistant não-confirmado desde a
    queda, SEM inbound posterior (R1), cujo lead tem última inbound < janela (R2).
    """
    now = datetime.now(timezone.utc)
    window_cutoff = now - timedelta(hours=window_hours)

    # Conversas do canal do João.
    convs = sb.table("conversations").select("id").eq("channel_id", JOAO_CHANNEL_ID).execute().data
    conv_ids = [c["id"] for c in convs]
    if not conv_ids:
        return []

    # Disparos outbound não-confirmados desde a queda (paginado por conversa em lotes).
    failed: list[dict] = []
    CHUNK = 100
    for i in range(0, len(conv_ids), CHUNK):
        slice_ids = conv_ids[i : i + CHUNK]
        rows = (
            sb.table("messages")
            .select("id, lead_id, conversation_id, content, created_at, delivery_status, message_type")
            .in_("conversation_id", slice_ids)
            .eq("role", "assistant")
            .gte("created_at", failure_start)
            .in_("delivery_status", list(UNCONFIRMED_STATUSES))
            .execute()
            .data
        )
        failed.extend(rows)

    eligible: list[dict] = []
    for m in failed:
        lead_id = m.get("lead_id")
        if not lead_id:
            continue
        # Todas as inbound (role=user) do lead — barato: poucas por lead.
        inbound = (
            sb.table("messages")
            .select("created_at")
            .eq("lead_id", lead_id)
            .eq("role", "user")
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
            .data
        )
        if not inbound:
            # Sem NENHUMA inbound => janela nunca abriu => R2 falha (precisaria de template).
            continue
        last_inbound = _parse(inbound[0]["created_at"])
        # R1: nenhuma inbound depois do disparo que falhou.
        if last_inbound > _parse(m["created_at"]):
            continue
        # R2: janela de 24h ainda aberta.
        if last_inbound < window_cutoff:
            continue
        m["last_inbound_at"] = last_inbound
        m["hours_since_last_inbound"] = round((now - last_inbound).total_seconds() / 3600, 1)
        eligible.append(m)

    return eligible


def print_dry_run(sb, failure_start: str, window_hours: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    eligible = compute_eligible(sb, failure_start, window_hours)

    # Diagnóstico agregado (mesmos números da auditoria SQL).
    convs = sb.table("conversations").select("id").eq("channel_id", JOAO_CHANNEL_ID).execute().data
    conv_ids = [c["id"] for c in convs]
    total_unconf = 0
    CHUNK = 100
    for i in range(0, len(conv_ids), CHUNK):
        total_unconf += (
            sb.table("messages")
            .select("id", count="exact")
            .in_("conversation_id", conv_ids[i : i + CHUNK])
            .eq("role", "assistant")
            .gte("created_at", failure_start)
            .in_("delivery_status", list(UNCONFIRMED_STATUSES))
            .execute()
            .count
            or 0
        )

    leads = {m["lead_id"] for m in eligible}
    print("=" * 72)
    print("DRY-RUN — recuperação de disparos do João (SOMENTE LEITURA)")
    print("=" * 72)
    print(f"  agora (UTC)................: {_iso(now)}")
    print(f"  início da falha (sexta)...: {failure_start}")
    print(f"  janela de sessão..........: {window_hours}h  (corte {_iso(now - timedelta(hours=window_hours))})")
    print(f"  canal do João.............: {JOAO_CHANNEL_ID}")
    print("-" * 72)
    print(f"  disparos não-confirmados desde a queda ...: {total_unconf}")
    print(f"  ELEGÍVEIS após R1 (sem resposta) ∩ R2 (janela aberta): {len(eligible)} msgs / {len(leads)} leads")
    print("-" * 72)
    for m in eligible:
        print(
            f"  lead={m['lead_id']}  msg={m['id']}  status={m['delivery_status']}  "
            f"disparo={m['created_at']}  última_inbound={_iso(m['last_inbound_at'])}  "
            f"({m['hours_since_last_inbound']}h atrás)"
        )
    if not eligible:
        print("  (nenhum disparo elegível — ver relatório)")
    print("=" * 72)
    return eligible


async def do_resend(sb, eligible: list[dict]) -> None:
    """Reenvio real via MetaCloudClient.send_text para o wa_id do lead, com o conteúdo
    original do disparo. Só é chamado sob --execute --yes e sobre R1∩R2."""
    if not eligible:
        print("Nada a reenviar (0 elegíveis). Encerrando sem tocar em produção.")
        return
    if len(eligible) > MAX_RESEND:
        raise SystemExit(f"ABORTADO: {len(eligible)} > teto {MAX_RESEND}. Revisar manualmente.")

    from app.whatsapp.meta import MetaCloudClient  # import tardio: só no caminho real

    channel = (
        sb.table("channels").select("provider_config").eq("id", JOAO_CHANNEL_ID).single().execute().data
    )
    provider = MetaCloudClient(channel["provider_config"])

    sent = 0
    for m in eligible:
        lead = sb.table("leads").select("wa_id, phone").eq("id", m["lead_id"]).single().execute().data
        to = (lead or {}).get("wa_id") or (lead or {}).get("phone")
        body = (m.get("content") or "").strip()
        if not to or not body:
            print(f"  pulado lead={m['lead_id']} (sem wa_id/phone ou conteúdo vazio)")
            continue
        resp = await provider.send_text(to, body)
        wamid = None
        try:
            wamid = resp["messages"][0]["id"]
        except Exception:
            pass
        sb.table("messages").insert(
            {
                "conversation_id": m["conversation_id"],
                "lead_id": m["lead_id"],
                "role": "assistant",
                "content": body,
                "sent_by": "recovery",
                "wamid": wamid,
                "delivery_status": "accepted",
                "metadata": {"recovery_of": m["id"], "reason": "joao_outage_20260703"},
            }
        ).execute()
        sent += 1
        print(f"  reenviado lead={m['lead_id']} to={to} wamid={wamid}")
    print(f"CONCLUÍDO: {sent} disparo(s) reenviado(s).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--failure-start", default=DEFAULT_FAILURE_START)
    ap.add_argument("--window-hours", type=int, default=SESSION_WINDOW_HOURS)
    ap.add_argument("--execute", action="store_true", help="executa o reenvio real (senão dry-run)")
    ap.add_argument("--yes", action="store_true", help="confirmação obrigatória junto com --execute")
    args = ap.parse_args()

    sb = _sb()
    eligible = print_dry_run(sb, args.failure_start, args.window_hours)

    if not args.execute:
        print("\nMODO DRY-RUN. Nada foi alterado. Para reenviar: --execute --yes")
        return
    if not args.yes:
        raise SystemExit("--execute exige --yes para confirmar o reenvio real.")
    asyncio.run(do_resend(sb, eligible))


if __name__ == "__main__":
    main()
