import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

// Importacao historica de pedidos. Admin-only e sob demanda: e um job longo,
// que percorre janelas de meses inteiros no ERP.
export async function POST(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const raw = Number(new URL(req.url).searchParams.get("months"));
  const months = Number.isFinite(raw) && raw > 0 ? Math.min(36, Math.trunc(raw)) : 12;
  try {
    const resp = await fetch(`${backend()}/api/bling/backfill?months=${months}`, {
      method: "POST",
      cache: "no-store",
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) return Response.json(body ?? { error: "backfill_failed" }, { status: resp.status });
    return Response.json(body);
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
