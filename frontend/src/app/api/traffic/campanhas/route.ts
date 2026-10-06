// Proxy admin-only: campanhas com gasto nos últimos 120 dias (select da atribuição manual).
// Usa o adminProxy do valeria-flow porque o endpoint do backend exige o JWT de admin
// (traffic_router.exigir_admin) — ele grava/expõe dado e o backend é público.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function GET() {
  return adminProxy("/api/traffic/campanhas");
}
