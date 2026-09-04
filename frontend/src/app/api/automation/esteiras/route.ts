import { NextResponse } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

/**
 * GET /api/automation/esteiras
 *
 * Proxy puro para `backend/app/campaigns/esteiras_router.py`, que é a fonte de verdade do
 * contrato. A rota NÃO enriquece nem reinterpreta o payload: `campaign_id`, `gatilho` e
 * `relogio` vêm de lá.
 *
 * Houve, por um tempo, um fallback que resolvia `campaign_id` por `(name, env_tag)` no
 * Supabase. Saiu de propósito: renomear a campanha no builder é exatamente o que esta tela
 * convida a fazer, e o fallback quebraria em silêncio no dia em que alguém renomeasse —
 * levando junto a frase que separa as duas esteiras de "Novo" (o filtro de último falante).
 *
 * Existe apesar do catch-all `/api/automation/[...path]` porque traduz falha de rede para
 * um JSON que a tela sabe mostrar, em vez de repassar a página de erro do Next.
 */
export async function GET() {
  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/automation/esteiras`, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Backend indisponível" }, { status: 502 });
  }

  const payload = await upstream.json().catch(() => null);
  if (!upstream.ok || !payload || !Array.isArray(payload.esteiras)) {
    return NextResponse.json(payload ?? { error: "Resposta inválida do backend" }, {
      status: upstream.ok ? 502 : upstream.status,
    });
  }
  return NextResponse.json(payload);
}
