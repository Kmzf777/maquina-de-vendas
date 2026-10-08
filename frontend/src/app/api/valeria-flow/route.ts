import { type NextRequest } from "next/server";
import { adminProxy, queryDoFluxo } from "./_shared";

/**
 * GET /api/valeria-flow — o fluxo inteiro (registry + overrides já mesclados
 * pelo backend). Ver `./_shared.ts` para por que esta rota, ao contrário de todo
 * outro proxy do repo, repassa o Bearer da sessão admin. `?flow_id=` escolhe a versão
 * (v1 sem ele; `valeria_botoes_v2` para a vitrine).
 */
export async function GET(request: NextRequest) {
  return adminProxy(`/api/valeria-flow${queryDoFluxo(request)}`);
}
