import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

// Sincroniza os espelhos locais (produtos, contatos, formas, vendedores).
// Admin-only: consome cota da API do Bling (3 req/s) e reescreve os espelhos.
export async function POST(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const full = new URL(req.url).searchParams.get("full") === "1";
  try {
    const resp = await fetch(`${backend()}/api/bling/sync?full=${full}`, {
      method: "POST",
      cache: "no-store",
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) return Response.json(body ?? { error: "sync_failed" }, { status: resp.status });
    return Response.json(body);
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
