import { getCurrentUser } from "@/lib/supabase/pipeline-access";

// Proxy admin-only de GET /api/conversions/ads (aba "Conversões enviadas" do /trafego).
const PARAMS = ["period", "date_from", "date_to", "platform", "stage", "status"] as const;

export async function GET(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const qs = PARAMS.filter((k) => searchParams.get(k))
    .map((k) => `${k}=${encodeURIComponent(searchParams.get(k) as string)}`)
    .join("&");
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/conversions/ads${qs ? `?${qs}` : ""}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "conversions_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "conversions_unreachable" }, { status: 502 });
  }
}
