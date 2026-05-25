"""
Limpeza: corrige telefones duplicados na tabela leads.

Um telefone duplicado é aquele onde a primeira metade é idêntica à segunda
(ex: "1198115400211981154002" = "11981154002" × 2).

MODO DE USO:
  1. Diagnóstico (somente leitura):
       python fix_duplicated_phones.py

  2. Aplicar fix:
       DRY_RUN=false python fix_duplicated_phones.py
"""
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

# ── carrega .env ─────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
with open(_env_path, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from supabase import create_client  # noqa: E402

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

print(f"{'='*65}")
print("LIMPEZA: telefones duplicados em leads")
print(f"MODO: {'DRY RUN (nenhuma alteração será feita)' if DRY_RUN else '⚡ APLICANDO ALTERAÇÕES'}")
print(f"{'='*65}\n")

# ── 1. Varrer leads em lotes ──────────────────────────────────────────────────
BATCH_SIZE = 1000
offset = 0
total_scanned = 0
affected: list[dict] = []

print("Escaneando leads...", flush=True)
while True:
    rows = (
        sb.table("leads")
        .select("id, phone")
        .range(offset, offset + BATCH_SIZE - 1)
        .execute()
        .data
    )
    if not rows:
        break
    for row in rows:
        phone = row.get("phone") or ""
        n = len(phone)
        if n > 13 and n % 2 == 0:
            half = n // 2
            if phone[:half] == phone[half:]:
                affected.append({
                    "id": row["id"],
                    "bad_phone": phone,
                    "good_phone": phone[:half],
                })
    total_scanned += len(rows)
    offset += BATCH_SIZE
    if len(rows) < BATCH_SIZE:
        break

# ── 2. Relatório ──────────────────────────────────────────────────────────────
print(f"Leads escaneados : {total_scanned}")
print(f"Telefones duplicados encontrados: {len(affected)}\n")

if not affected:
    print("✓ Nenhum telefone duplicado encontrado. Banco limpo.")
    sys.exit(0)

print("Registros afetados:")
for item in affected:
    print(f"  id={item['id']}  {item['bad_phone']}  →  {item['good_phone']}")

# ── 3. Aplicar fix ────────────────────────────────────────────────────────────
if DRY_RUN:
    print(f"\n[DRY RUN] {len(affected)} registro(s) seriam corrigidos.")
    print("Para aplicar: DRY_RUN=false python fix_duplicated_phones.py")
    sys.exit(0)

print(f"\nAplicando fix em {len(affected)} registro(s)...")

fixed = 0
errors = 0
for item in affected:
    try:
        result = (
            sb.table("leads")
            .update({"phone": item["good_phone"]})
            .eq("id", item["id"])
            .eq("phone", item["bad_phone"])  # guard: só atualiza se ainda está errado
            .execute()
        )
        if result.data:
            print(f"  ✓  {item['bad_phone']}  →  {item['good_phone']}")
            fixed += 1
        else:
            print(f"  ⚠  Sem alteração (já corrigido?): id={item['id']}")
    except Exception as e:
        print(f"  ✗  Erro id={item['id']}: {e}")
        errors += 1

print(f"\n{'='*65}")
print(f"RESULTADO: {fixed} corrigidos, {errors} erros")
print(f"{'='*65}")
