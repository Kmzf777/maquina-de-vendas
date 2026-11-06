// Proxy admin-only do detalhe de campanha pela primeira ou pela última origem (F5, jornada do
// lead). O backend exige o JWT de admin (jornada_router -> exigir_admin): o adminProxy repassa.
import { adminProxy } from "@/app/api/valeria-flow/_shared";
import { jornadaCampaignQuery } from "@/lib/traffic-jornada";

export async function GET(req: Request) {
  return adminProxy(`/api/traffic/jornada/campaign?${jornadaCampaignQuery(req.url)}`);
}
