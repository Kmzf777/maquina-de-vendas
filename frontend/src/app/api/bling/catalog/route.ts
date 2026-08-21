import type { NextRequest } from "next/server";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

/**
 * Catalogo do ESPELHO local de produtos do Bling (tabela `bling_products`),
 * nunca da API do Bling — a tela de produtos pagina e filtra livremente.
 */
export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  const params = new URLSearchParams();
  const q = sp.get("q");
  const situacao = sp.get("situacao");
  if (q) params.set("q", q);
  if (situacao) params.set("situacao", situacao);
  params.set("page", sp.get("page") || "1");
  params.set("limit", sp.get("limit") || "50");

  try {
    const resp = await fetch(`${backend()}/api/bling/catalog?${params}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "catalog_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
