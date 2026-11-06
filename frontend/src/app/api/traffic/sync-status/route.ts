// Proxy admin-only: última rodada do sync de investimento por plataforma (ok/falha/aviso, quando
// e o motivo), para a linha embaixo do botão Atualizar do /trafego.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function GET() {
  return adminProxy("/api/traffic/sync-status");
}
