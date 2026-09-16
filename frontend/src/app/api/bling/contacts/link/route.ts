const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

/**
 * Confirma manualmente o contato do Bling escolhido pelo vendedor (fluxo do 409).
 *
 * O modal manda JSON; o endpoint do FastAPI (`POST /api/bling/contacts/link`)
 * recebe `lead_id` e `contact_id` como QUERY STRING — são parâmetros escalares,
 * não um modelo Pydantic. Mandar como corpo faria o backend responder 422 sem o
 * vendedor entender por quê, então a tradução acontece aqui.
 */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const leadId = String(body?.lead_id ?? "");
  const contactId = Number(body?.contact_id);
  // account chega no CORPO (o modal manda JSON), mas o backend deste endpoint
  // le como query string -- mesma traducao que lead_id/contact_id ja fazem.
  // Sem default sintetico aqui: ausente, o backend aplica o dele sozinho.
  const account = body?.account ? String(body.account) : "";
  if (!leadId || !Number.isFinite(contactId)) {
    return Response.json({ error: "lead_id e contact_id sao obrigatorios" }, { status: 400 });
  }

  const url =
    `${backend()}/api/bling/contacts/link` +
    `?lead_id=${encodeURIComponent(leadId)}&contact_id=${contactId}` +
    (account ? `&account=${encodeURIComponent(account)}` : "");
  try {
    const resp = await fetch(url, { method: "POST", cache: "no-store" });
    return Response.json(await resp.json().catch(() => ({})), { status: resp.status });
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
