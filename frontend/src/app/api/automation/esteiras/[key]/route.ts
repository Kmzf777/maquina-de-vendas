import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

/**
 * PUT /api/automation/esteiras/{key}
 *
 * Proxy puro para o FastAPI. Existe porque o catch-all `/api/automation/[...path]`
 * só encaminha GET e POST — um PUT cairia em 405 antes de chegar ao backend.
 *
 * O status do upstream é repassado sem tradução, de propósito: o backend recusa
 * `ativa: true` com 400 quando o gatilho ainda não tem etapa, e essa mensagem precisa
 * chegar inteira à tela (a UI já desabilita o clique, mas o 400 é a rede de segurança).
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ key: string }> }
) {
  const { key } = await params;
  const body = await request.text();

  try {
    const upstream = await fetch(
      `${FASTAPI_URL}/api/automation/esteiras/${encodeURIComponent(key)}`,
      { method: "PUT", headers: { "Content-Type": "application/json" }, body }
    );
    const payload = await upstream.json().catch(() => ({}));
    return NextResponse.json(payload, { status: upstream.status });
  } catch {
    return NextResponse.json({ error: "Backend indisponível" }, { status: 502 });
  }
}
