import { type NextRequest } from "next/server";
import { adminProxy } from "../_shared";

/**
 * POST /api/valeria-flow/activate — cria um `agent_profiles` novo e REPONTA o
 * canal escolhido para ele. É por causa desta rota que `./_shared.ts` existe:
 * sem o Bearer admin, isto seria uma tomada de canal alcançável de fora.
 */
export async function POST(request: NextRequest) {
  const body = await request.json();
  return adminProxy("/api/valeria-flow/activate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
