import { adminProxy } from "./_shared";

/**
 * GET /api/valeria-flow — o fluxo inteiro (registry + overrides já mesclados
 * pelo backend). Ver `./_shared.ts` para por que esta rota, ao contrário de todo
 * outro proxy do repo, repassa o Bearer da sessão admin.
 */
export async function GET() {
  return adminProxy("/api/valeria-flow");
}
