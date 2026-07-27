"""Reagenda os `handoff_rescue` que morreram no backstop `ai_disabled` (regressão 15/07/2026).

CONTEXTO
--------
`encaminhar_humano` desliga a IA (`ai_enabled=False`) e, no mesmo passo, agenda um
`handoff_rescue`: 15 min depois, se o lead NÃO tiver procurado o João por conta própria,
o número do João dispara o template `automacao_valeria_to_joao`.

Em 15/07/2026 ~11:51 entrou em `follow_up/scheduler.py` a "rede de segurança de parada",
que roda para QUALQUER job_type antes do roteador dedicado e cancela quando o lead está
marcado para parar — inclusive por `ai_disabled`. Como é o próprio handoff que desliga a
IA, todo `handoff_rescue` passou a nascer condenado:

    último envio bem-sucedido ... 15/07 11:21:35
    1º cancelamento ai_disabled . 15/07 11:51:09   (30 min depois)

De lá até o fix (27/07), ZERO resgates enviados. O lead recebia o cartão do João e, se não
tomasse a iniciativa, nunca mais ouvia falar da empresa.

O fix (`_STOP_REASON_EXEMPT_JOB_TYPES`) já está em produção e verificado: job
360d0858-016d-481c-a06b-e71aa49460c7 disparou em 27/07 16:16:11 — o primeiro em 12 dias.
Mas os jobs já cancelados não voltam sozinhos: este script os reagenda.

O QUE ELE FAZ
-------------
Seleciona leads que, na janela informada:
  * receberam handoff no canal da Valéria (mensagem `sent_by='handoff'`); E
  * NÃO enviaram nenhuma mensagem ao canal do João depois desse handoff.

E insere para cada um um `follow_up_jobs` novo (`job_type='handoff_rescue'`, `status='pending'`)
com `fire_at` no horário pedido. Quem executa é o worker de sempre, pelo caminho de sempre
(`_process_handoff_rescue`) — este script NÃO manda mensagem.

Por que reagendar em vez de disparar direto: o handler dedicado revalida, no momento do
envio, se o lead procurou o João nos últimos 15 min. Um lead que aparecer durante a noite
NÃO recebe o template. Disparar direto perderia essa checagem.

REDES DE SEGURANÇA
------------------
  * DRY-RUN por padrão. Só `--execute --yes` grava.
  * Idempotência por `metadata.recovery_batch`: rodar 2x não duplica.
  * Pula lead que já tenha `handoff_rescue` pending (não empilha).
  * Exclui opt_out / blacklisted / wrong_number (o backstop também cancelaria, mas melhor
    nem criar o job).
  * Teto duro `--max` (default 200).
  * `--env-tag` explícito: `get_due_followups` filtra por ele. Rodar com `.env.local`
    (IS_DEV_ENV=true) geraria jobs `dev` que produção jamais coletaria — por isso o default
    aqui é "production" e o valor efetivo é impresso antes de gravar.

EXECUÇÃO EM PRODUÇÃO (27/07/2026)
---------------------------------
Rodado em duas passadas, ambas com fire_at = 2026-07-28 09:00 BRT:
  * janela do apagão (--since 2026-07-22T20:48:00Z) ....  78 jobs
  * coorte da regressão (--since 2026-07-15T14:51:00Z) . 100 jobs
Total: 178 jobs, 178 leads distintos, 1 job por lead (sem duplicata — a 2ª passada
pulou os 78 da 1ª via `ja_tem_rescue_pending`).

NÃO reagendados de propósito — 5 leads com handoff ANTERIOR à regressão e sem resgate:
2 são leads de teste (5521900000090/92), 1 número UK cancelado em auditoria manual
(63 dias) e 2 falharam com `meta_permanent_error_404` do bug de locale pt_BR (41-42
dias). Nenhum é vítima desta regressão e o template seria anacrônico.

USO (no container/venv do backend, com env de PRODUÇÃO)
------------------------------------------------------
    # 1) conferir o que seria criado (não grava nada)
    python -m scripts.schedule_handoff_rescue_recovery_2026_07_27

    # 2) criar os jobs para amanhã 09:00 BRT
    python -m scripts.schedule_handoff_rescue_recovery_2026_07_27 --execute --yes

    # coorte anterior (regressão 15/07 até o início do apagão)
    python -m scripts.schedule_handoff_rescue_recovery_2026_07_27 \
        --since 2026-07-15T14:51:00Z --until 2026-07-22T20:48:00Z
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

_BRT = timezone(timedelta(hours=-3))

from supabase import create_client

VALERIA_CHANNEL_ID = "6e51629d-f095-4a4e-9e26-46a8da225a89"
JOAO_CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd"
JOAO_PHONE_NUMBER_ID = "1049315514934778"

# Locale APROVADO na Meta: automacao_valeria_to_joao só existe em `en` (corpo é PT).
# pt_BR dá 404 #132001. Mesma fonte de verdade de follow_up/service.schedule_handoff_rescue.
TEMPLATE_NAME = "automacao_valeria_to_joao"
TEMPLATE_LANG = "en"

# Início do apagão de gemini-2.5-flash (última resposta real da Valéria).
DEFAULT_SINCE = "2026-07-22T20:48:00Z"  # 17:48 BRT
# Amanhã 09:00 BRT = 12:00 UTC. Terça-feira, dentro da janela do rescue (09h-20h, seg-sex).
DEFAULT_FIRE_AT = "2026-07-28T12:00:00Z"

BATCH_TAG = "handoff_rescue_recovery_20260727"
DEFAULT_MAX = 200
PAGE = 1000


def _sb():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _all_rows(query_fn) -> list[dict]:
    """Pagina qualquer select (PostgREST corta em 1000 linhas por padrão)."""
    out, offset = [], 0
    while True:
        rows = query_fn(offset, offset + PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        offset += PAGE


def _conv_map(sb, channel_id: str) -> dict[str, str]:
    """conversation_id -> lead_id para um canal."""
    rows = _all_rows(lambda a, b: sb.table("conversations")
                     .select("id, lead_id").eq("channel_id", channel_id).range(a, b))
    return {r["id"]: r["lead_id"] for r in rows}


def _collect(sb, since: str, until: str | None) -> list[dict]:
    """Leads com handoff na janela e SEM mensagem ao João depois dele."""
    val_convs = _conv_map(sb, VALERIA_CHANNEL_ID)
    joao_convs = _conv_map(sb, JOAO_CHANNEL_ID)

    # 1) handoffs na janela (canal Valéria) -> primeiro handoff por lead
    def _handoffs(a, b):
        q = (sb.table("messages")
             .select("lead_id, conversation_id, created_at")
             .eq("sent_by", "handoff").gte("created_at", since))
        if until:
            q = q.lt("created_at", until)
        return q.order("created_at").range(a, b)

    primeiro: dict[str, dict] = {}
    for m in _all_rows(_handoffs):
        if m["conversation_id"] not in val_convs:
            continue  # handoff de outro canal
        primeiro.setdefault(m["lead_id"], m)  # ordenado por created_at → o 1º vence

    if not primeiro:
        return []

    # 2) inbounds do lead no canal do João (todos), para descartar quem procurou
    def _joao_inbounds(a, b):
        return (sb.table("messages").select("lead_id, conversation_id, created_at")
                .eq("role", "user").gte("created_at", since).range(a, b))

    contato_joao: dict[str, str] = {}  # lead_id -> created_at mais recente
    for m in _all_rows(_joao_inbounds):
        if m["conversation_id"] not in joao_convs:
            continue
        lid = m["lead_id"]
        if lid not in contato_joao or m["created_at"] > contato_joao[lid]:
            contato_joao[lid] = m["created_at"]

    alvo = {
        lid: h for lid, h in primeiro.items()
        if not (lid in contato_joao and contato_joao[lid] > h["created_at"])
    }
    if not alvo:
        return []

    # 3) dados do lead + flags de bloqueio
    leads = _all_rows(lambda a, b: sb.table("leads")
                      .select("id, phone, name, opt_out, metadata, ai_enabled")
                      .in_("id", list(alvo.keys())).range(a, b))

    # 4) jobs handoff_rescue já pending (não empilhar) e já criados por este batch
    jobs = _all_rows(lambda a, b: sb.table("follow_up_jobs")
                     .select("lead_id, status, metadata")
                     .eq("job_type", "handoff_rescue")
                     .in_("lead_id", list(alvo.keys())).range(a, b))
    pendentes = {j["lead_id"] for j in jobs if j.get("status") == "pending"}
    ja_no_batch = {
        j["lead_id"] for j in jobs
        if (j.get("metadata") or {}).get("recovery_batch") == BATCH_TAG
    }

    out = []
    for lead in leads:
        meta = lead.get("metadata") or {}
        motivo_skip = None
        if lead.get("opt_out"):
            motivo_skip = "opt_out"
        elif meta.get("blacklisted_at"):
            motivo_skip = "blacklisted"
        elif meta.get("wrong_number_at"):
            motivo_skip = "wrong_number"
        elif lead["id"] in pendentes:
            motivo_skip = "ja_tem_rescue_pending"
        elif lead["id"] in ja_no_batch:
            motivo_skip = "ja_criado_neste_batch"
        out.append({
            "lead": lead,
            "handoff": alvo[lead["id"]],
            "skip": motivo_skip,
        })
    out.sort(key=lambda r: r["handoff"]["created_at"])
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", default=DEFAULT_SINCE, help="início da janela de handoffs (ISO UTC)")
    p.add_argument("--until", default=None, help="fim da janela de handoffs (ISO UTC)")
    p.add_argument("--fire-at", default=DEFAULT_FIRE_AT, help="quando disparar (ISO UTC)")
    p.add_argument("--stagger-seconds", type=int, default=0,
                   help="espaçamento entre jobs (0 = todos no mesmo instante; o worker já "
                        "coleta 10 por tick de 30s, então a entrega sai em lotes de 10)")
    p.add_argument("--env-tag", default="production", choices=["production", "dev"])
    p.add_argument("--max", type=int, default=DEFAULT_MAX, help="teto duro anti-spam")
    p.add_argument("--execute", action="store_true", help="grava de verdade")
    p.add_argument("--yes", action="store_true", help="confirma o --execute")
    args = p.parse_args()

    sb = _sb()
    rows = _collect(sb, args.since, args.until)
    elegiveis = [r for r in rows if not r["skip"]]
    pulados = [r for r in rows if r["skip"]]

    fire_at = datetime.fromisoformat(args.fire_at.replace("Z", "+00:00"))

    print(f"janela handoffs : {args.since} -> {args.until or 'agora'}")
    print(f"fire_at         : {fire_at.isoformat()} "
          f"({fire_at.astimezone(_BRT):%d/%m %H:%M} BRT)")
    print(f"env_tag         : {args.env_tag}")
    print(f"template        : {TEMPLATE_NAME} ({TEMPLATE_LANG}) via phone_number_id {JOAO_PHONE_NUMBER_ID}")
    print(f"batch           : {BATCH_TAG}")
    print("-" * 78)
    print(f"handoffs sem contato ao João : {len(rows)}")
    print(f"  elegíveis (jobs a criar)   : {len(elegiveis)}")
    print(f"  pulados                    : {len(pulados)}")
    for motivo in sorted({r["skip"] for r in pulados}):
        print(f"      {motivo}: {sum(1 for r in pulados if r['skip'] == motivo)}")
    print("-" * 78)

    for r in elegiveis[:15]:
        lead = r["lead"]
        print(f"  {lead.get('name') or '(sem nome)':<28} {lead['phone']:<15} "
              f"handoff {r['handoff']['created_at'][:16]}")
    if len(elegiveis) > 15:
        print(f"  ... e mais {len(elegiveis) - 15}")

    if len(elegiveis) > args.max:
        print(f"\nABORTADO: {len(elegiveis)} elegíveis excede o teto --max={args.max}.")
        return

    if not (args.execute and args.yes):
        print("\nDRY-RUN — nada gravado. Use --execute --yes para criar os jobs.")
        return

    criados = 0
    for i, r in enumerate(elegiveis):
        lead, hoff = r["lead"], r["handoff"]
        quando = fire_at + timedelta(seconds=i * args.stagger_seconds)
        job = {
            "conversation_id": hoff["conversation_id"],
            "lead_id": lead["id"],
            "channel_id": VALERIA_CHANNEL_ID,
            "sequence": 1,
            "fire_at": quando.isoformat(),
            "status": "pending",
            "env_tag": args.env_tag,
            "job_type": "handoff_rescue",
            "metadata": {
                "lead_phone": lead["phone"],
                "lead_name": lead.get("name") or "",
                "joao_phone_number_id": JOAO_PHONE_NUMBER_ID,
                "template_name": TEMPLATE_NAME,
                "language_code": TEMPLATE_LANG,
                "recovery_batch": BATCH_TAG,
                "original_handoff_at": hoff["created_at"],
            },
        }
        try:
            sb.table("follow_up_jobs").insert(job).execute()
            criados += 1
        except Exception as exc:
            print(f"  FALHA ao criar job p/ {lead['phone']}: {exc}")

    print(f"\n{criados} job(s) handoff_rescue criado(s) para {fire_at.isoformat()}.")
    print("O worker dispara pelo caminho normal (_process_handoff_rescue), que revalida "
          "se o lead procurou o João nos últimos 15 min antes de enviar.")


if __name__ == "__main__":
    main()
