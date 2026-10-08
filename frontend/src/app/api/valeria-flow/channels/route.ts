import { type NextRequest } from "next/server";
import { adminProxy, queryDoFluxo } from "../_shared";

/** GET /api/valeria-flow/channels — canais, perfil atual de cada um, aviso de perfil compartilhado. */
export async function GET(request: NextRequest) {
  return adminProxy(`/api/valeria-flow/channels${queryDoFluxo(request)}`);
}
