import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

// Devolve a URL de consentimento do Bling. Admin-only: quem inicia o OAuth
// grava o refresh_token da conta inteira.
export async function GET(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const { searchParams } = new URL(req.url);
  // Qual conta o admin esta conectando/reconectando. Sem default sintetico:
  // ausente, o backend aplica o dele (config.DEFAULT_ACCOUNT) sozinho.
  const account = searchParams.get("account");
  const url = `${backend()}/api/bling/oauth/authorize${
    account ? `?account=${encodeURIComponent(account)}` : ""
  }`;
  try {
    const resp = await fetch(url, { cache: "no-store" });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) return Response.json(body ?? { error: "unavailable" }, { status: resp.status });
    return Response.json(body);
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
