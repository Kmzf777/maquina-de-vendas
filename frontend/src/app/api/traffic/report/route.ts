import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function GET(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const period = searchParams.get("period") || "30d";
  const mode = searchParams.get("mode") || "lead";
  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const extra = `${dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : ""}${dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : ""}`;
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/report?period=${encodeURIComponent(period)}&mode=${encodeURIComponent(mode)}${extra}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "report_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "report_unreachable" }, { status: 502 });
  }
}
