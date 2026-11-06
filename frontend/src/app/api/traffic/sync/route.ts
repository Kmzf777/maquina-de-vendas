// Proxy admin-only: dispara o sync do investimento (Google + Meta) sob demanda (botão Atualizar).
// Repassa o JWT do admin (adminProxy): o backend exige `exigir_admin` desde a frente F1.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function POST() {
  return adminProxy("/api/traffic/sync-ads", { method: "POST" });
}
