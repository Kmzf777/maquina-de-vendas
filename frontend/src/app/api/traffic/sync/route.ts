import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function POST() {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/sync-google-ads`, { method: "POST", cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "sync_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "sync_unreachable" }, { status: 502 });
  }
}
