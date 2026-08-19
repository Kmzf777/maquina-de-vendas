import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

// Devolve a URL de consentimento do Bling. Admin-only: quem inicia o OAuth
// grava o refresh_token da conta inteira.
export async function GET() {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  try {
    const resp = await fetch(`${backend()}/api/bling/oauth/authorize`, { cache: "no-store" });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) return Response.json(body ?? { error: "unavailable" }, { status: resp.status });
    return Response.json(body);
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
