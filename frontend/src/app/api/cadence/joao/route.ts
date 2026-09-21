import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

const UPSTREAM = `${FASTAPI_URL}/api/cadence/joao`;

/**
 * Proxy da SOBREPOSIÇÃO das cadências do João (`backend/app/follow_up/api.py`).
 *
 * O corpo da resposta viaja INTACTO, com o STATUS do upstream. É a linha mais
 * importante deste arquivo: a recusa de ligar uma cadência chega como
 * `400 {"detail": {"problemas": [...]}}`, e é essa lista — template por template,
 * com a linha e o toque de cada um — que a tela precisa mostrar. Resumir aqui para
 * `{error: "..."}`, ou normalizar o status para 200, reproduziria exatamente o erro
 * de 16/09/2026 no builder de campanhas: o backend recusava certo, a interface ficava
 * muda, e ninguém descobriu até produção.
 */
export async function PUT(req: NextRequest) {
  try {
    const upstream = await fetch(UPSTREAM, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: await req.text(),
      cache: "no-store",
    });
    const texto = await upstream.text();
    let corpo: unknown;
    try {
      corpo = JSON.parse(texto);
    } catch {
      corpo = { error: texto || `backend respondeu ${upstream.status}` };
    }
    return NextResponse.json(corpo, { status: upstream.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
