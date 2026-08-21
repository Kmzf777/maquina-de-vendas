import type { NextRequest } from "next/server";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

/**
 * Busca no ESPELHO local de contatos do Bling (tabela `bling_contacts`), nunca
 * na API do Bling — é por isso que pode disparar a cada tecla digitada.
 */
export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  const q = sp.get("q") || "";
  const limit = sp.get("limit") || "20";
  try {
    const resp = await fetch(
      `${backend()}/api/bling/contacts/search?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(limit)}`,
      { cache: "no-store" }
    );
    if (!resp.ok) return Response.json({ error: "contacts_search_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
