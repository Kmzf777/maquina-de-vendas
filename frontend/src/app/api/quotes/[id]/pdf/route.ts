import { NextResponse, type NextRequest } from "next/server";
import { backendUrl } from "@/lib/quotes/backend";
import { guardaDeOrcamento } from "@/lib/quotes/quotes-scope-route";

/**
 * Download do PDF do orcamento — proxy BINARIO.
 *
 * A unica rota deste diretorio que nao pode passar por `.json()`. O corpo e um
 * `application/pdf`; ler como JSON levantaria de imediato, e o caminho
 * "corrigido" obvio — ler como texto e reenviar — corromperia o arquivo em
 * silencio, porque o decode UTF-8 substitui todo byte invalido por U+FFFD e o
 * PDF chegaria no disco do vendedor com o tamanho errado e ilegivel. Por isso
 * `arrayBuffer()`, que nao interpreta byte nenhum.
 *
 * Os dois headers vem do backend em vez de serem remontados aqui porque o
 * `filename` do `Content-Disposition` depende do numero da proposta, que so o
 * backend conhece — e ele pode ser nulo (o numero vem de um GET best-effort),
 * caso em que o nome cai no id. Reconstruir o header no Next exigiria buscar o
 * orcamento so para descobrir o nome do arquivo.
 *
 * O caminho de ERRO volta como JSON de proposito: quando o backend responde 404
 * ou 500, o corpo e `{"detail": ...}`, e repassar isso com `Content-Type:
 * application/pdf` faria o navegador baixar um "PDF" que e uma mensagem de erro.
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
    const resp = await fetch(`${backendUrl()}/api/quotes/${encodeURIComponent(id)}/pdf`, {
      cache: "no-store",
    });

    if (!resp.ok) {
      const detalhe = await resp.text().catch(() => "");
      return NextResponse.json(
        { error: detalhe || "Não foi possível gerar o PDF." },
        { status: resp.status },
      );
    }

    const corpo = await resp.arrayBuffer();
    const headers = new Headers();
    headers.set("Content-Type", resp.headers.get("Content-Type") || "application/pdf");
    const disposition = resp.headers.get("Content-Disposition");
    if (disposition) headers.set("Content-Disposition", disposition);
    // O PDF e montado na hora e reflete o orcamento no instante do clique;
    // qualquer cache intermediario devolveria a versao anterior a uma edicao.
    headers.set("Cache-Control", "no-store");

    return new NextResponse(corpo, { status: 200, headers });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
