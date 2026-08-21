const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

/**
 * Desfaz o vinculo lead-contato (a proxima venda volta a resolucao por
 * documento). O modal manda JSON; o endpoint do FastAPI
 * (`POST /api/bling/contacts/unlink`) recebe `lead_id` como QUERY STRING —
 * mesma traducao que `contacts/link/route.ts` ja faz.
 */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const leadId = String(body?.lead_id ?? "");
  if (!leadId) {
    return Response.json({ error: "lead_id e obrigatorio" }, { status: 400 });
  }

  const url = `${backend()}/api/bling/contacts/unlink?lead_id=${encodeURIComponent(leadId)}`;
  try {
    const resp = await fetch(url, { method: "POST", cache: "no-store" });
    return Response.json(await resp.json().catch(() => ({})), { status: resp.status });
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
