import { NextResponse, type NextRequest } from "next/server";
import { backendUrl } from "@/lib/quotes/backend";
import { guardaDeOrcamento } from "@/lib/quotes/quotes-scope-route";

/**
 * "Marcar aprovado / não aprovado" — proxy para o FastAPI.
 *
 * Nao e um UPDATE de coluna: o backend valida a transicao e espelha a situacao
 * no Bling via `PATCH /propostas-comerciais/{id}/situacoes`. Por isso a resposta
 * traz `situacao_sync` junto do `status` — o CRM pode ter gravado o novo estado
 * enquanto o ERP recusou a mudanca, e a tela precisa poder avisar em vez de
 * fingir que os dois lados concordam.
 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  // Propriedade antes de qualquer coisa: sem isto o UUID e a unica
  // credencial necessaria para agir sobre orcamento alheio.
  const guarda = await guardaDeOrcamento(id);
  if (!guarda.ok) return guarda.resposta;
  const body = await request.json();
  try {
    const resp = await fetch(`${backendUrl()}/api/quotes/${encodeURIComponent(id)}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return NextResponse.json(await resp.json(), { status: resp.status });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
