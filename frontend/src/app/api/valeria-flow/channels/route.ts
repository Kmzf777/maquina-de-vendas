import { adminProxy } from "../_shared";

/** GET /api/valeria-flow/channels — canais, perfil atual de cada um, aviso de perfil compartilhado. */
export async function GET() {
  return adminProxy("/api/valeria-flow/channels");
}
