import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function GET(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const channel = searchParams.get("channel") || "";
  const campaign = searchParams.get("campaign") || "";
  const period = searchParams.get("period") || "30d";
  const mode = searchParams.get("mode") || "lead";
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  const qs = new URLSearchParams({ channel, campaign, period, mode }).toString();
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/leads?${qs}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "leads_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "leads_unreachable" }, { status: 502 });
  }
}
