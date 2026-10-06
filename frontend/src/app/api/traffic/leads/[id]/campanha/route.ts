// Proxy admin-only: atribui (ou remove) a campanha de origem de um lead no /trafego.
// O e-mail de quem atribuiu sai do JWT no backend, não do corpo — o cliente não escolhe o "por".
import type { NextRequest } from "next/server";
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.text();
  return adminProxy(`/api/traffic/leads/${encodeURIComponent(id)}/campanha`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
