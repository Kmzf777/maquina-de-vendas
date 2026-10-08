// Proxy admin-only de GET /api/conversions/dashboard (seção "Conversões (Ads)" do Dashboard).
// Usa o adminProxy porque o endpoint do backend exige o JWT de admin (traffic_router.exigir_admin):
// o payload traz receita de vendas e o backend é público — a checagem não pode ficar só aqui.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function GET() {
  return adminProxy("/api/conversions/dashboard");
}
