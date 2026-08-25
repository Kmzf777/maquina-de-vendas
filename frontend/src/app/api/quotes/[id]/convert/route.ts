import { NextResponse, type NextRequest } from "next/server";
import { backendUrl } from "@/lib/quotes/backend";
import { guardaDeOrcamento } from "@/lib/quotes/quotes-scope-route";

/**
 * "Converter em venda" — proxy para o FastAPI.
 *
 * A operacao mais cara da tela e a unica irreversivel: o backend cria o pedido
 * de venda no Bling, grava `sales` + `sale_items`, move o deal para
 * `fechado_ganho` e so entao marca o orcamento como convertido, que passa a ser
 * imutavel.
 *
 * Nenhum retry automatico aqui, nem no cliente. Repetir um POST que talvez tenha
 * chegado produziria um segundo pedido no ERP — o `409 already_converted` do
 * backend defende contra a segunda chamada BEM-SUCEDIDA, mas nao contra uma
 * primeira que tenha se perdido depois de criar o pedido. Timeout de rede tem
 * que virar erro na tela para o vendedor conferir no Bling antes de tentar de
 * novo, e nao uma retentativa silenciosa.
 *
 * `201` traz `{sale_id, bling_order_id, situacao_sync}`. `situacao_sync: false`
 * significa que a venda existe e o PATCH de situacao no Bling falhou — e por
 * isso e um 201 e nao um erro: desfazer a venda seria pior que a proposta ficar
 * com a situacao velha no ERP.
 */
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  // Propriedade antes de qualquer coisa: sem isto o UUID e a unica
  // credencial necessaria para agir sobre orcamento alheio.
  const guarda = await guardaDeOrcamento(id);
  if (!guarda.ok) return guarda.resposta;
  try {
    const resp = await fetch(`${backendUrl()}/api/quotes/${encodeURIComponent(id)}/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    return NextResponse.json(await resp.json(), { status: resp.status });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
