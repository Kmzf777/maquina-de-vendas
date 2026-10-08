import { type NextRequest } from "next/server";
import { adminProxy, queryDoFluxo } from "../_shared";

type Params = { params: Promise<{ nodeId: string }> };

/** PUT /api/valeria-flow/{nodeId} — grava `corpo`/`rotulos`; devolve o item mesclado. */
export async function PUT(request: NextRequest, { params }: Params) {
  const { nodeId } = await params;
  const body = await request.json();
  return adminProxy(`/api/valeria-flow/${encodeURIComponent(nodeId)}${queryDoFluxo(request)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** DELETE /api/valeria-flow/{nodeId} — apaga o override; devolve o item no default do registry. */
export async function DELETE(request: NextRequest, { params }: Params) {
  const { nodeId } = await params;
  return adminProxy(`/api/valeria-flow/${encodeURIComponent(nodeId)}${queryDoFluxo(request)}`, {
    method: "DELETE",
  });
}
