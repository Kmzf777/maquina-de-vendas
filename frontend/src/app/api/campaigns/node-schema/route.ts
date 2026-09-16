import { NextResponse } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

/**
 * GET /api/campaigns/node-schema — proxy para `backend/app/campaigns/router.py`.
 *
 * POR QUE ESTA ROTA PRECISA EXISTIR
 * ─────────────────────────────────
 * O contrato dos nós é servido pelo FastAPI, mas quem o consome é o builder, que roda
 * no NAVEGADOR e só alcança o Next. Sem este arquivo, `fetch("/api/campaigns/node-schema")`
 * cai em `src/app/api/campaigns/[id]/route.ts` com `id="node-schema"` — o Supabase
 * recusa o uuid inválido e a resposta é 404. O inspector degradaria para sempre (sem
 * campo nenhum), e a única pista seria um 404 no console.
 *
 * É a mesma armadilha de ordem de rota que o backend documenta em
 * `test_node_schema_endpoint_2026_09_16.py` (lá a rota estática precisa ser declarada
 * ANTES de `/{campaign_id}`); aqui o App Router resolve pela especificidade — segmento
 * literal vence segmento dinâmico — desde que o segmento literal exista.
 *
 * O contrato é estático por deploy (é dado puro em `node_registry.py`, sem I/O), então
 * a resposta pode ser cacheada pelo navegador por alguns minutos: a tela busca uma vez
 * por carregamento e várias abas do builder não precisam bater no backend cada uma.
 *
 * Backend fora do ar vira JSON de erro, não a página de erro do Next: quem chama
 * (`lib/node-schema.ensureNodeSchema`) trata a falha devolvendo `null`, e o inspector
 * mostra "carregando o contrato" em vez de quebrar.
 */
export async function GET() {
  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/campaigns/node-schema`, {
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ error: "Backend indisponível" }, { status: 502 });
  }

  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, {
    status: upstream.status,
    headers: upstream.ok ? { "Cache-Control": "private, max-age=300" } : undefined,
  });
}
