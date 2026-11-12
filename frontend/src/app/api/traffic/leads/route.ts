// Proxy admin-only do /trafego (leads). Repassa o JWT do admin (adminProxy): o backend exige
// `exigir_admin` em todas as rotas de tráfego desde a frente F1 (06/11/2026) — o /leads
// devolve nome e telefone de lead e ficava aberto a quem chamasse o backend direto.
// Modo padrão "sale" (por venda), igual ao backend e à página.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams;
  const params: Record<string, string> = {
    channel: sp.get("channel") || "",
    campaign: sp.get("campaign") || "",
    period: sp.get("period") || "30d",
    mode: sp.get("mode") || "periodo",
  };
  const dateFrom = sp.get("date_from");
  const dateTo = sp.get("date_to");
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  return adminProxy(`/api/traffic/leads?${new URLSearchParams(params).toString()}`);
}
