// Proxy admin-only de GET /api/conversions/ads (aba "Conversões enviadas" do /trafego).
// Usa o adminProxy do valeria-flow porque o endpoint do backend exige o JWT de admin
// (traffic_router.exigir_admin): a lista expõe nome de lead e valor de venda, e o backend é público.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

const PARAMS = ["period", "date_from", "date_to", "platform", "stage", "status"] as const;

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const qs = PARAMS.filter((k) => searchParams.get(k))
    .map((k) => `${k}=${encodeURIComponent(searchParams.get(k) as string)}`)
    .join("&");
  return adminProxy(`/api/conversions/ads${qs ? `?${qs}` : ""}`);
}
