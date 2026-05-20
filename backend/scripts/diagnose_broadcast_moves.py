"""
Diagnóstico: verifica se leads dos últimos 4 disparos foram movidos de Kanban.
Fase 1: LEITURA APENAS.
"""
import os, sys

with open(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from supabase import create_client
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

EXCLUDE_PHONE = "5534988861441"

# ── 1. Últimos broadcasts não-draft ─────────────────────────────────────────
broadcasts = (
    sb.table("broadcasts")
    .select("id, name, status, move_to_stage_id, created_at")
    .neq("status", "draft")
    .order("created_at", desc=True)
    .limit(10)
    .execute()
).data

# ── 2. Filtrar broadcasts que contêm apenas lead de teste ──────────────────
def only_test_lead(bid):
    bls = sb.table("broadcast_leads").select("leads!inner(phone)").eq("broadcast_id", bid).execute().data
    phones = [bl["leads"]["phone"] for bl in bls if bl.get("leads")]
    return all(EXCLUDE_PHONE in p for p in phones) and len(phones) > 0

relevant = []
for b in broadcasts:
    if len(relevant) >= 4:
        break
    if only_test_lead(b["id"]):
        print(f"[IGNORADO — só teste] {b['name']}")
    else:
        relevant.append(b)

print(f"\n{'='*65}")
print(f"ANALISANDO {len(relevant)} BROADCASTS")
print(f"{'='*65}")

# ── 3. Checar coluna deal_moved_at (migration pode não ter rodado) ──────────
has_deal_moved_at = True
try:
    sb.table("broadcast_leads").select("deal_moved_at").limit(1).execute()
except Exception:
    has_deal_moved_at = False
    print("\n⚠ AVISO: coluna deal_moved_at não existe. Migration não foi rodada.\n")

# ── 4. Para cada broadcast, listar leads não movidos ──────────────────────
needs_move = []   # lista de dicts para o script de fix

for b in relevant:
    bid = b["id"]
    mts = b.get("move_to_stage_id")
    created = b["created_at"][:16]
    print(f"\n▶ {b['name']}")
    print(f"  id: {bid}  |  criado: {created}")
    print(f"  move_to_stage_id: {mts or '(não configurado)'}")

    if not mts:
        print("  → Sem move configurado. OK.")
        continue

    # Buscar target stage
    ts = sb.table("pipeline_stages").select("label, pipeline_id, pipelines(name)").eq("id", mts).single().execute().data
    if not ts:
        print(f"  ✗ Stage alvo {mts} não encontrado!")
        continue
    target_label    = ts.get("label", "?")
    target_pipeline = (ts.get("pipelines") or {}).get("name", "?")
    target_pip_id   = ts.get("pipeline_id")
    print(f"  Destino: {target_pipeline} › {target_label}")

    # Buscar broadcast_leads sent/delivered
    cols = "id, lead_id, status, sent_at" + (", deal_moved_at" if has_deal_moved_at else "")
    bls = (
        sb.table("broadcast_leads")
        .select(f"{cols}, leads(name, phone)")
        .eq("broadcast_id", bid)
        .in_("status", ["sent", "delivered"])
        .execute()
    ).data

    total = len(bls)
    if has_deal_moved_at:
        moved_count = sum(1 for bl in bls if bl.get("deal_moved_at"))
        not_moved_bls = [bl for bl in bls if not bl.get("deal_moved_at")]
    else:
        moved_count = 0
        not_moved_bls = bls

    print(f"  Total sent/delivered: {total}  |  deal_moved_at OK: {moved_count}  |  Pendentes: {len(not_moved_bls)}")

    if not not_moved_bls:
        print("  ✓ Todos os leads foram movidos (deal_moved_at preenchido).")
        continue

    print(f"\n  Verificando deals reais de {len(not_moved_bls)} leads pendentes:")
    for bl in not_moved_bls:
        lead = bl.get("leads") or {}
        lead_id = bl["lead_id"]
        phone   = lead.get("phone", "?")
        lname   = lead.get("name") or phone

        # Deals na pipeline alvo
        deals = (
            sb.table("deals")
            .select("id, stage_id, pipeline_id, stage, updated_at")
            .eq("lead_id", lead_id)
            .eq("pipeline_id", target_pip_id)
            .execute()
        ).data

        already_correct = [d for d in deals if d.get("stage_id") == mts]
        wrong_stage     = [d for d in deals if d.get("stage_id") != mts]

        if already_correct:
            status_str = "⚠ DEAL JÁ NA ETAPA CERTA (deal_moved_at NULL — só tracking falhou)"
        elif deals:
            stages = [d.get("stage_id") for d in deals]
            status_str = f"✗ NÃO MOVIDO — stage_id atual: {stages}"
            needs_move.append({
                "bl_id": bl["id"], "lead_id": lead_id, "name": lname, "phone": phone,
                "move_to_stage_id": mts, "target_pipeline_id": target_pip_id,
                "broadcast_id": bid, "deals": deals,
            })
        else:
            status_str = "✗ SEM DEAL na pipeline alvo"
            needs_move.append({
                "bl_id": bl["id"], "lead_id": lead_id, "name": lname, "phone": phone,
                "move_to_stage_id": mts, "target_pipeline_id": target_pip_id,
                "broadcast_id": bid, "deals": [],
            })

        print(f"    {lname} ({phone}): {status_str}")

# ── 5. Resumo ────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"RESUMO FINAL")
print(f"{'='*65}")
print(f"Leads que precisam de ação: {len(needs_move)}")
for item in needs_move:
    print(f"  - {item['name']} ({item['phone']})  lead_id={item['lead_id']}")
    if item["deals"]:
        print(f"    deals existentes na pipeline: {[d['id'] for d in item['deals']]}")
    else:
        print(f"    sem deal na pipeline alvo → precisa criar")
