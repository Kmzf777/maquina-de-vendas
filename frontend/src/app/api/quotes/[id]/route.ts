import { NextResponse, type NextRequest } from "next/server";
import { backendUrl } from "@/lib/quotes/backend";
import { guardaDeOrcamento } from "@/lib/quotes/quotes-scope-route";

/**
 * Leitura e edicao de UM orcamento — proxy puro para o FastAPI.
 *
 * Diferente da listagem, que consulta o Supabase direto: aqui o backend e quem
 * tem que responder, porque o PUT nao e um UPDATE de linha — ele reenvia a
 * proposta inteira para o Bling (`PUT /propostas-comerciais/{id}`) e so entao
 * grava. Fazer o Next escrever direto criaria uma segunda fonte de verdade que
 * divergiria do ERP no primeiro erro de rede.
 *
 * O status volta TAL QUAL. O que a tela faz com cada um:
 *   200 — salvo; recarrega a lista.
 *   409 `quote_converted` — o orcamento virou venda e travou. A tela nem chega
 *        aqui no caminho normal (`podeEditar` esconde o botao), mas duas abas
 *        abertas produzem exatamente esse choque, e um 500 generico deixaria o
 *        vendedor achando que o sistema caiu.
 *   422 — validacao do Bling; a mensagem e o unico caminho para saber o que ele
 *        recusou.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  // Propriedade antes de qualquer coisa: sem isto o UUID e a unica
  // credencial necessaria para agir sobre orcamento alheio.
  const guarda = await guardaDeOrcamento(id);
  if (!guarda.ok) return guarda.resposta;
  try {
    const resp = await fetch(`${backendUrl()}/api/quotes/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    return NextResponse.json(await resp.json(), { status: resp.status });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}

export async function PUT(
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
    const resp = await fetch(`${backendUrl()}/api/quotes/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return NextResponse.json(await resp.json(), { status: resp.status });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
