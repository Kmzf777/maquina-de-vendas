import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

/**
 * POST /api/campaigns/{id}/activate
 *
 * Proxy puro para `backend/app/campaigns/router.py` (`POST /api/campaigns/{id}/activate`),
 * que agora é a ÚNICA fonte de verdade da validação de ativação (12 regras: campos
 * obrigatórios do registro de nós, integridade de grafo, canal, template aprovado com o
 * status real da Meta). A checagem de gatilho/next_node_id e o bloqueio de campanha de
 * sistema (`isSystemCampaign`) que existiam aqui viraram duplicação do que o FastAPI já
 * cobre (`_reject_system_campaign` + validação de nós) — duplicá-las é exatamente a
 * doença que este projeto trata, então saíram.
 *
 * Status e corpo do upstream são repassados sem tradução, de propósito: um 400 aqui é a
 * validação recusando a ativação, com `detail.problemas[]` (cada item com
 * `no_id`/`codigo`/`mensagem` — a tela usa `no_id` para destacar o nó culpado no canvas).
 * Engolir o 400 e devolver 200 destruiria a trava inteira.
 *
 * Falha de rede vira JSON que a tela sabe mostrar, em vez da página de erro do Next —
 * mesmo tratamento (e mesmo motivo) de `automation/esteiras/route.ts`.
 */
export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${FASTAPI_URL}/api/campaigns/${encodeURIComponent(id)}/activate`,
      { method: "POST", headers: { "Content-Type": "application/json" } },
    );
  } catch {
    return NextResponse.json({ error: "Backend indisponível" }, { status: 502 });
  }

  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, { status: upstream.status });
}
