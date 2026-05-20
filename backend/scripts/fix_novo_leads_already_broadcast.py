"""
Remediação: move deals stuck em "Novo" para "Já Chamado" no pipeline "Reposicao - Joao"
quando o lead já recebeu um disparo anteriormente.

Causa: bug em produção (master) no worker de broadcast — SELECT+UPDATE(limit 1) movia
apenas o deal mais recente. Deals mais antigos do mesmo lead ficaram em "Novo" e o lead
continuava aparecendo para novos disparos → spam.

MODO DE USO:
  1. Diagnóstico (somente leitura):
       python fix_novo_leads_already_broadcast.py

  2. Aplicar fix:
       DRY_RUN=false python fix_novo_leads_already_broadcast.py
       # ou edite DRY_RUN = False abaixo
"""
import os
import sys

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

# ── carrega .env ─────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
with open(_env_path, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from supabase import create_client  # noqa: E402

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

PIPELINE_NAME = "Reposição - João"
SOURCE_STAGE_LABEL = "Novo"
TARGET_STAGE_LABEL = "Já chamado"

print(f"{'='*65}")
print(f"REMEDIACAO: {PIPELINE_NAME}  |  {SOURCE_STAGE_LABEL} -> {TARGET_STAGE_LABEL}")
print(f"MODO: {'DRY RUN (nenhuma alteração será feita)' if DRY_RUN else '⚡ APLICANDO ALTERAÇÕES'}")
print(f"{'='*65}\n")

# ── 1. Localizar pipeline ─────────────────────────────────────────────────────
pipeline_row = (
    sb.table("pipelines")
    .select("id, name")
    .eq("name", PIPELINE_NAME)
    .limit(1)
    .execute()
).data

if not pipeline_row:
    print(f"✗ Pipeline '{PIPELINE_NAME}' não encontrado. Verifique o nome exato no banco.")
    sys.exit(1)

pipeline = pipeline_row[0]
pipeline_id = pipeline["id"]
print(f"Pipeline encontrado: {pipeline['name']}  (id: {pipeline_id})")

# ── 2. Buscar stages Novo e Já Chamado ────────────────────────────────────────
stages = (
    sb.table("pipeline_stages")
    .select("id, label")
    .eq("pipeline_id", pipeline_id)
    .execute()
).data

stage_map = {s["label"]: s["id"] for s in stages}
print(f"Stages disponíveis: {list(stage_map.keys())}\n")

source_stage_id = stage_map.get(SOURCE_STAGE_LABEL)
target_stage_id = stage_map.get(TARGET_STAGE_LABEL)

if not source_stage_id:
    print(f"✗ Stage '{SOURCE_STAGE_LABEL}' não encontrado na pipeline. Stages: {list(stage_map.keys())}")
    sys.exit(1)
if not target_stage_id:
    print(f"✗ Stage '{TARGET_STAGE_LABEL}' não encontrado na pipeline. Stages: {list(stage_map.keys())}")
    sys.exit(1)

print(f"Stage '{SOURCE_STAGE_LABEL}': {source_stage_id}")
print(f"Stage '{TARGET_STAGE_LABEL}': {target_stage_id}\n")

# ── 3. Buscar todos os deals em "Novo" nessa pipeline ─────────────────────────
deals_in_novo = (
    sb.table("deals")
    .select("id, lead_id, updated_at, leads(name, phone)")
    .eq("pipeline_id", pipeline_id)
    .eq("stage_id", source_stage_id)
    .execute()
).data

print(f"Deals atualmente em '{SOURCE_STAGE_LABEL}': {len(deals_in_novo)}\n")

if not deals_in_novo:
    print("✓ Nenhum deal em 'Novo'. Nada a fazer.")
    sys.exit(0)

# ── 4. Para cada lead, verificar se já recebeu algum disparo ──────────────────
to_move = []       # (deal_id, lead_id, lead_name, phone, qtd_broadcasts)
already_clean = [] # leads sem histórico de disparo

lead_ids_checked = set()
for deal in deals_in_novo:
    lead_id = deal["lead_id"]
    if lead_id in lead_ids_checked:
        # mesmo lead com vários deals — já verificamos
        to_move.append((deal["id"], lead_id, deal.get("leads", {}).get("name") or "?",
                        deal.get("leads", {}).get("phone") or "?", "já contado"))
        continue
    lead_ids_checked.add(lead_id)

    # Checar se o lead tem broadcast_leads com status sent/delivered
    bls = (
        sb.table("broadcast_leads")
        .select("id, broadcast_id, status, sent_at")
        .eq("lead_id", lead_id)
        .in_("status", ["sent", "delivered"])
        .execute()
    ).data

    lead_name = (deal.get("leads") or {}).get("name") or "?"
    phone     = (deal.get("leads") or {}).get("phone") or "?"

    if bls:
        to_move.append((deal["id"], lead_id, lead_name, phone, len(bls)))
    else:
        already_clean.append((deal["id"], lead_id, lead_name, phone))

# ── 5. Relatório ──────────────────────────────────────────────────────────────
print(f"{'─'*65}")
print(f"DIAGNÓSTICO")
print(f"{'─'*65}")
print(f"  Deals em 'Novo' com disparo anterior: {len(to_move)}")
print(f"  Deals em 'Novo' sem disparo anterior: {len(already_clean)}")
print()

if to_move:
    print("Deals a mover → 'Já Chamado':")
    for deal_id, lead_id, name, phone, n_bl in to_move:
        tag = f"{n_bl} disparo(s)" if isinstance(n_bl, int) else n_bl
        print(f"  [{tag}] {name} ({phone})  deal={deal_id}")

if already_clean:
    print("\nDeals sem histórico de disparo (permanecem em 'Novo'):")
    for deal_id, lead_id, name, phone in already_clean:
        print(f"  {name} ({phone})  deal={deal_id}")

# ── 6. Aplicar fix ────────────────────────────────────────────────────────────
if not to_move:
    print("\n✓ Nenhum deal para mover.")
    sys.exit(0)

if DRY_RUN:
    print(f"\n[DRY RUN] {len(to_move)} deal(s) seriam movidos para '{TARGET_STAGE_LABEL}'.")
    print("Para aplicar: DRY_RUN=false python fix_novo_leads_already_broadcast.py")
    sys.exit(0)

print(f"\nAplicando fix — movendo {len(to_move)} deal(s) para '{TARGET_STAGE_LABEL}'...")

from datetime import datetime, timezone  # noqa: E402

moved = 0
errors = 0
for deal_id, lead_id, name, phone, _ in to_move:
    try:
        result = (
            sb.table("deals")
            .update({
                "stage_id": target_stage_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", deal_id)
            .eq("stage_id", source_stage_id)  # guard: só move se ainda está em Novo
            .execute()
        )
        if result.data:
            print(f"  ✓ Movido: {name} ({phone})")
            moved += 1
        else:
            print(f"  ⚠ Sem alteração (já movido?): {name} ({phone})")
    except Exception as e:
        print(f"  ✗ Erro ao mover {name} ({phone}): {e}")
        errors += 1

print(f"\n{'='*65}")
print(f"RESULTADO: {moved} movidos, {errors} erros, {len(to_move) - moved - errors} sem alteração")
print(f"{'='*65}")
