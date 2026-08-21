import type { NextRequest } from "next/server";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ order_id: string }> }
) {
  const { order_id } = await params;
  const body = await req.json();
  try {
    const resp = await fetch(`${backend()}/api/bling/orders/${encodeURIComponent(order_id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    // Repassa o status TAL QUAL: o modal distingue 200 (alterado), 202
    // (indisponibilidade transitória, sem job — reenviar basta), 409 (contato
    // não resolvido) e 422 (recusa de validação do Bling, tipicamente pedido
    // já faturado — aí quem decide o que fazer é o modal, não este proxy).
    return Response.json(await resp.json(), { status: resp.status });
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
